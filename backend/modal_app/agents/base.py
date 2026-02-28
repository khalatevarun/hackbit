from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable

from shared import supabase_client as db
from shared import supermemory_client as mem


class AgentResult:
    def __init__(
        self,
        status: str,
        next_action: str,
        reasoning: str,
        confidence: float = 0.5,
        context_summary: str = "",
        message_to_user: str | None = None,
        content_suggestions: list[dict] | None = None,
    ):
        self.status = status
        self.next_action = next_action
        self.reasoning = reasoning
        self.confidence = confidence
        self.context_summary = context_summary
        self.message_to_user = message_to_user
        self.content_suggestions = content_suggestions or []

    def to_state(self) -> dict:
        return {
            "last_checkin": datetime.now(timezone.utc).isoformat(),
            "pattern_detected": self.status if self.status != "monitoring" else None,
            "confidence": self.confidence,
            "context_summary": self.context_summary,
            "next_action": self.next_action,
            "next_action_time": datetime.now(timezone.utc).isoformat(),
        }


def _extract_json(text: str) -> dict:
    """Parse JSON from LLM output, stripping markdown fences if present."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n?", text)
    if fence:
        text = text[fence.end():]
        text = re.sub(r"\n?```\s*$", "", text)
    return json.loads(text)


class BaseAgent(ABC):
    template_name: str = "base"

    def __init__(self, llm_fn: Callable[..., str] | None = None):
        self._llm_fn = llm_fn

    @abstractmethod
    def analyze(self, user_id: str, goal_id: str, config: dict) -> AgentResult:
        ...

    def get_logs(self, user_id: str, goal_id: str | None, days: int = 7) -> list[dict]:
        return db.get_recent_logs(user_id, goal_id=goal_id, days=days)

    def get_cross_context(self, user_id: str, query: str) -> list[dict]:
        return mem.search_memories(query=query, user_id=user_id, limit=8)

    def save_observation(
        self,
        user_id: str,
        goal_id: str,
        observation: str,
        confidence: float = 0.5,
    ) -> None:
        mem.add_agent_observation(
            user_id=user_id,
            goal_id=goal_id,
            agent_template=self.template_name,
            observation=observation,
            confidence=confidence,
        )

    def get_peer_states(self, user_id: str, exclude_goal_id: str) -> str:
        """Return a formatted summary of what other agents are currently thinking."""
        states = db.get_agent_states_for_user(user_id)
        lines = []
        for s in states:
            if s["goal_id"] == exclude_goal_id:
                continue
            state = s.get("state", {})
            goal_info = s.get("goals") or {}
            template = goal_info.get("agent_template", "unknown")
            goal_name = goal_info.get("name", "unknown goal")
            next_action = state.get("next_action", "monitor")
            pattern = state.get("pattern_detected", "")
            confidence = state.get("confidence", 0.0)
            context = state.get("context_summary", "")
            summary = f"- {template.capitalize()} companion ({goal_name}): {next_action}"
            if confidence:
                summary += f" (confidence {confidence:.2f})"
            if pattern:
                summary += f" — \"{pattern}\""
            if context:
                summary += f". Context: {context[:150]}"
            lines.append(summary)
        if not lines:
            return "No other companions have recent states."
        return "\n".join(lines)

    def llm_assess(self, system_prompt: str, user_prompt: str) -> dict:
        """Run an LLM assessment via the Modal GPU service and parse JSON."""
        messages = [
            {
                "role": "system",
                "content": system_prompt + "\n\nYou MUST respond with valid JSON only. No other text.",
            },
            {"role": "user", "content": user_prompt},
        ]
        raw = self._llm_fn(messages, 0.3)
        return _extract_json(raw)
