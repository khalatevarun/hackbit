from __future__ import annotations

from .base import AgentResult, BaseAgent


class SocialAgent(BaseAgent):
    template_name = "social"

    SYSTEM_PROMPT = """You are a social/emotional accountability agent. You monitor a user's social activity and emotional state.
Given the user's recent logs, goal config, and cross-domain context,
assess their social health and emotional wellbeing.

Return JSON with:
- status: "monitoring" | "concerned" | "intervention_needed"
- next_action: "monitor" | "nudge" | "call" | "escalate"
- reasoning: brief explanation
- confidence: 0.0-1.0
- message_to_user: optional warm, empathetic message (null if just monitoring)

Consider:
- Be warm and empathetic, non-intrusive but persistent
- Look for isolation patterns (cancelled plans, no social mentions)
- Connect dots from other agents (stress-spending, poor sleep, skipped workouts)
- Weight stress/emotional mentions higher than activity counts
- If multiple other agents are concerned, take that seriously
"""

    def analyze(self, user_id: str, goal_id: str, config: dict) -> AgentResult:
        min_social = config.get("min_social_per_week", 2)

        logs = self.get_logs(user_id, goal_id, days=14)
        log_texts = [l["content"][:120] for l in logs[:8]]

        # Also check user-wide logs for emotional signals
        all_logs = self.get_logs(user_id, goal_id=None, days=7)
        all_log_texts = [l["content"][:100] for l in all_logs[:6]]

        context = self.get_cross_context(
            user_id,
            "User's emotional state, stress mentions, isolation patterns, other agents' concerns",
        )
        context_summary = "\n".join(c["content"][:120] for c in context[:4] if c.get("content"))

        peer_states = self.get_peer_states(user_id, goal_id)

        prompt = f"""Goal: {min_social} social activities/week
Social logs: {log_texts}
All recent logs: {all_log_texts}
Context: {context_summary[:400]}
Peers: {peer_states[:400]}

How is the user's social and emotional wellbeing?"""

        assessment = self.llm_assess(self.SYSTEM_PROMPT, prompt)

        next_action = assessment.get("next_action", "monitor")
        content_suggestions: list[dict] = []

        result = AgentResult(
            status=assessment.get("status", "monitoring"),
            next_action=next_action,
            reasoning=assessment.get("reasoning", ""),
            confidence=assessment.get("confidence", 0.5),
            context_summary=context_summary[:500],
            message_to_user=assessment.get("message_to_user"),
            content_suggestions=content_suggestions,
        )

        if result.status != "monitoring":
            self.save_observation(
                user_id, goal_id,
                f"Social agent detected '{result.status}': {result.reasoning}",
                confidence=result.confidence,
            )

        return result
