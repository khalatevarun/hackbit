from __future__ import annotations

from datetime import datetime, timezone

from .base import AgentResult, BaseAgent


class ShortLivedAgent(BaseAgent):
    template_name = "short_lived"

    SYSTEM_PROMPT = """You are a deadline-focused accountability agent for a short-term goal.
The user has a time-bounded objective. Your job is to track progress and nudge
as the deadline approaches.

Given the user's recent logs, goal config (including deadline and success criteria),
and cross-domain context, assess their progress.

Return JSON with:
- status: "on_track" | "behind" | "at_risk" | "completed"
- next_action: "monitor" | "nudge" | "call" | "escalate"
- reasoning: brief explanation
- confidence: 0.0-1.0
- days_remaining: number
- progress_estimate: 0.0-1.0 (how close to completion)
- message_to_user: optional encouraging/urgent message based on timeline (null if on track)

Consider:
- As deadline gets closer, urgency should increase
- If < 2 days remain and progress is low, escalate
- Be encouraging but realistic about time pressure
- Acknowledge stress from other domains but keep focus on the deadline
"""

    def analyze(self, user_id: str, goal_id: str, config: dict) -> AgentResult:
        end_date_str = config.get("end_date")
        success_criteria = config.get("success_criteria", "Complete the goal")

        days_remaining = None
        if end_date_str:
            end_date = datetime.fromisoformat(end_date_str).replace(tzinfo=timezone.utc)
            days_remaining = max(0, (end_date - datetime.now(timezone.utc)).days)

        logs = self.get_logs(user_id, goal_id, days=14)
        log_texts = [l["content"][:120] for l in logs[:10]]

        context = self.get_cross_context(
            user_id,
            "User progress on short-term goal, stress level, competing priorities",
        )
        context_summary = "\n".join(c["content"][:120] for c in context[:4] if c.get("content"))

        peer_states = self.get_peer_states(user_id, goal_id)

        prompt = f"""Goal: {success_criteria}
Days remaining: {days_remaining if days_remaining is not None else 'unknown'} (end: {end_date_str or 'not set'})
Recent logs: {log_texts}
Context: {context_summary[:400]}
Peers: {peer_states[:400]}

How is the user progressing toward their deadline?"""

        assessment = self.llm_assess(self.SYSTEM_PROMPT, prompt)

        next_action = assessment.get("next_action", "monitor")
        content_suggestions: list[dict] = []

        result = AgentResult(
            status=assessment.get("status", "on_track"),
            next_action=next_action,
            reasoning=assessment.get("reasoning", ""),
            confidence=assessment.get("confidence", 0.5),
            context_summary=context_summary[:500],
            message_to_user=assessment.get("message_to_user"),
            content_suggestions=content_suggestions,
        )

        if result.status not in ("on_track", "completed"):
            self.save_observation(
                user_id, goal_id,
                f"Short-lived agent: '{result.status}' with {days_remaining} days left. {result.reasoning}",
                confidence=result.confidence,
            )

        return result
