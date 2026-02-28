from __future__ import annotations

from .base import AgentResult, BaseAgent


class MoneyAgent(BaseAgent):
    template_name = "money"

    SYSTEM_PROMPT = """You are a spending accountability agent. You monitor a user's spending patterns.
Given the user's recent logs, goal config, and cross-domain context,
analyze spending patterns and detect anomalies.

Return JSON with:
- status: "monitoring" | "anomaly_detected" | "pattern_concern"
- next_action: "monitor" | "nudge" | "call" | "escalate"
- reasoning: brief explanation
- confidence: 0.0-1.0
- message_to_user: optional non-judgmental observation (null if just monitoring)

Consider:
- Be anxious but non-judgmental — focus on patterns, not amounts
- Look for stress-spending correlations
- If other agents report stress/poor sleep, connect those dots
- Never shame, just observe and gently flag
"""

    def analyze(self, user_id: str, goal_id: str, config: dict) -> AgentResult:
        budget = config.get("weekly_budget")
        categories = config.get("watch_categories", [])

        logs = self.get_logs(user_id, goal_id, days=14)
        log_texts = [l["content"] for l in logs]

        context = self.get_cross_context(
            user_id,
            "Is user stressed? Emotional state, sleep quality, recent life events",
        )
        context_summary = "\n".join(c["content"] for c in context if c.get("content"))

        prompt = f"""Goal config: weekly budget={budget}, watch categories={categories}
Recent spending/activity logs (last 14 days): {log_texts}
Cross-domain context: {context_summary}

Analyze the user's spending patterns."""

        assessment = self.llm_assess(self.SYSTEM_PROMPT, prompt)

        result = AgentResult(
            status=assessment.get("status", "monitoring"),
            next_action=assessment.get("next_action", "monitor"),
            reasoning=assessment.get("reasoning", ""),
            confidence=assessment.get("confidence", 0.5),
            context_summary=context_summary[:500],
            message_to_user=assessment.get("message_to_user"),
        )

        if result.status != "monitoring":
            self.save_observation(
                user_id, goal_id,
                f"Money agent detected '{result.status}': {result.reasoning}",
                confidence=result.confidence,
            )

        return result
