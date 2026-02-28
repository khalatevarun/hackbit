from __future__ import annotations

from .base import AgentResult, BaseAgent


class SleepAgent(BaseAgent):
    template_name = "sleep"

    SYSTEM_PROMPT = """You are a sleep accountability agent. You monitor a user's sleep habits.
Given the user's recent logs, goal config, and cross-domain context,
determine the user's sleep status and what action to take.

Return JSON with:
- status: "monitoring" | "concerned" | "intervention_needed"
- next_action: "monitor" | "nudge" | "call" | "escalate"
- reasoning: brief explanation
- confidence: 0.0-1.0
- message_to_user: optional caring message (null if just monitoring)
- broadcast: optional message to broadcast to other agents about sleep status (null if fine)

Consider:
- Be calm and caring, like a concerned parent
- Prioritize rest over everything else
- If sleep is chronically poor, recommend other agents ease off their demands
- Track bedtime consistency, not just duration
"""

    def analyze(self, user_id: str, goal_id: str, config: dict) -> AgentResult:
        target_hours = config.get("target_hours", 8)
        target_bedtime = config.get("target_bedtime", "23:00")

        logs = self.get_logs(user_id, goal_id, days=7)
        log_texts = [l["content"][:120] for l in logs[:10]]

        context = self.get_cross_context(
            user_id,
            "What's affecting user's sleep? Stress, late activities, workout timing",
        )
        context_summary = "\n".join(c["content"][:120] for c in context[:4] if c.get("content"))

        peer_states = self.get_peer_states(user_id, goal_id)

        assessment = self.llm_assess(
            self.SYSTEM_PROMPT,
            f"""Goal: {target_hours}h sleep, bedtime by {target_bedtime}
Recent logs: {log_texts}
Context: {context_summary[:400]}
Peers: {peer_states[:400]}

How is the user's sleep?""",
        )

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
                f"Sleep agent detected '{result.status}': {result.reasoning}",
                confidence=result.confidence,
            )

        broadcast = assessment.get("broadcast")
        if broadcast:
            from shared.supabase_client import create_agent_message
            create_agent_message(
                user_id=user_id,
                from_agent=f"sleep:{goal_id}",
                message=broadcast,
                goal_id=goal_id,
            )

        return result
