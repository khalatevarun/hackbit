from __future__ import annotations

from .base import AgentResult, BaseAgent


class FitnessAgent(BaseAgent):
    template_name = "fitness"

    SYSTEM_PROMPT = """You are a fitness accountability agent. You monitor a user's workout habits.
Given the user's recent logs, goal config, and cross-domain context (sleep, stress, etc.),
determine the user's status and what action to take.

Return JSON with:
- status: "monitoring" | "concerned" | "intervention_needed"
- next_action: "monitor" | "nudge" | "call" | "escalate"
- reasoning: brief explanation
- confidence: 0.0-1.0
- message_to_user: optional motivational/check-in message (null if just monitoring)

Consider:
- If sleep is poor, be gentler (suggest light activity instead of intense workout)
- If stress is high, acknowledge it and suggest exercise as stress relief, not obligation
- Celebrate consistency and wins enthusiastically
"""

    def analyze(self, user_id: str, goal_id: str, config: dict) -> AgentResult:
        freq = config.get("frequency_per_week", 3)
        activity = config.get("target", "workout")

        logs = self.get_logs(user_id, goal_id, days=7)
        log_texts = [l["content"] for l in logs]

        context = self.get_cross_context(
            user_id,
            f"User's sleep quality, stress level, and emotional state this week",
        )
        context_summary = "\n".join(c["content"] for c in context if c.get("content"))

        assessment = self.llm_assess(
            self.SYSTEM_PROMPT,
            f"""Goal: {activity} {freq}x per week
Recent activity logs (last 7 days): {log_texts}
Cross-domain context: {context_summary}

How is the user doing with their fitness goal?""",
        )

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
                f"Fitness agent detected '{result.status}': {result.reasoning}",
                confidence=result.confidence,
            )

        return result
