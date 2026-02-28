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
        log_texts = [l["content"] for l in logs]

        # Also check user-wide logs for emotional signals
        all_logs = self.get_logs(user_id, goal_id=None, days=7)
        all_log_texts = [l["content"] for l in all_logs]

        context = self.get_cross_context(
            user_id,
            "User's emotional state, stress mentions, isolation patterns, other agents' concerns",
        )
        context_summary = "\n".join(c["content"] for c in context if c.get("content"))

        # Check messages from other agents
        from shared.supabase_client import get_agent_messages
        other_agent_msgs = get_agent_messages(user_id, limit=20)
        agent_concerns = [
            m["message"] for m in other_agent_msgs
            if m.get("to_agent") in (None, f"social:{goal_id}")
        ]

        prompt = f"""Goal: maintain at least {min_social} social activities per week
Social activity logs (last 14 days): {log_texts}
All recent logs (last 7 days, for emotional signals): {all_log_texts}
Other agents' concerns/messages: {agent_concerns}
Cross-domain context: {context_summary}

How is the user's social and emotional wellbeing?"""

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
                f"Social agent detected '{result.status}': {result.reasoning}",
                confidence=result.confidence,
            )

        return result
