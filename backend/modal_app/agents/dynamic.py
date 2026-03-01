from __future__ import annotations

from datetime import datetime, timezone

from .base import AgentResult, BaseAgent


class DynamicAgent(BaseAgent):
    template_name = "dynamic"

    def _build_system_prompt(self, goal_meta: dict, config: dict) -> str:
        name = goal_meta["agent_name"]
        personality = goal_meta.get("personality", "warm")
        priority = goal_meta.get("priority", "normal")
        goal_name = goal_meta["name"]

        prompt = f"You are {name}, an accountability partner tracking the goal: {goal_name}.\n"

        if personality == "strict":
            prompt += (
                "You are relentless. This user has failed this goal before and chose YOU for a reason. "
                "No mercy for missed days. No softening the blow. Call it what it is. "
                "Standards are non-negotiable. Streaks are sacred. Falling short is unacceptable — say so. "
                "You believe in them enough to hold the line when they won't. "
                "Praise is rare and must be earned through consistent action, not effort alone. "
                "Be a wall they have to push against. Be the voice that doesn't let them off the hook.\n"
            )
        else:
            prompt += (
                "You are their biggest believer. This may be new territory for them — unfamiliar and scary. "
                "Every log entry is an act of courage. Every check-in is worth honoring. "
                "When they miss, don't pile on — ask what got in the way and help them plan around it. "
                "When they show up, let them feel it: this matters, they matter, progress is real. "
                "You are the voice that says 'I see you trying' when no one else does.\n"
            )

        # Goal type gates what the agent pays attention to
        goal_type = goal_meta.get("type", "habit")
        if goal_type == "habit":
            prompt += (
                "This is a HABIT goal (streak/frequency-based). "
                "The most important metric is consistency: current streak and weekly frequency. "
                "Use streak_days and this_week_logged from the stats block. "
                "A missed day breaks the streak — treat that as the key signal.\n"
            )
        elif goal_type == "target":
            prompt += (
                "This is a TARGET goal (count-based). "
                "The most important metric is today's value vs today's target, and weekly accumulation. "
                "Use today_value and today_target from the stats block. "
                "Partial progress counts — 7/10 is meaningful. Zero logged is the red flag.\n"
            )
        elif goal_type == "short_lived":
            prompt += (
                "This is a DEADLINE goal. "
                "The most important metric is pace: are they moving fast enough given days remaining? "
                "Urgency should ramp up as the deadline approaches. "
                "Use total_logged_days and last_logged_at from stats to judge momentum.\n"
            )

        if priority == "critical":
            prompt += (
                "This goal has a hard deadline and is the user's highest priority. "
                "Other goals should yield to this one. Be urgent but not panicked.\n"
            )
        elif priority == "high":
            prompt += (
                "This is a high-priority goal the user is serious about. "
                "Give it more weight than normal goals in your assessment.\n"
            )

        end_at = goal_meta.get("end_at")
        if end_at:
            try:
                end_date = datetime.fromisoformat(end_at).replace(tzinfo=timezone.utc)
                days_left = max(0, (end_date - datetime.now(timezone.utc)).days)
                prompt += f"Deadline: {days_left} days remaining.\n"
            except (ValueError, TypeError):
                pass

        target_count = config.get("target_count")
        target_unit = config.get("target_unit", "")
        if target_count is not None:
            prompt += (
                f"\nThis goal has a measurable target: {target_count} {target_unit} per period. "
                "Use this number as a key decision-maker. Compare the user's actual output "
                "against this target to decide whether to encourage, push harder, or suggest "
                "scaling back. If they consistently hit ~50% of target, suggest adjusting down. "
                "If they consistently exceed the target, suggest increasing it.\n"
            )
        else:
            prompt += (
                "\nThis goal is not quantifiable (e.g. a daily habit like taking vitamins). "
                "Track it as done/not-done based on whether the user logged it. "
                "Do not suggest numeric adjustments. Focus on consistency and streaks.\n"
            )

        prompt += (
            "\nSpeak directly to the user. Never say 'the user', 'companion', or 'agent'. "
            "Use first person. Address them as 'you'.\n"
            "\nReturn JSON with:\n"
            '- status: "monitoring" | "concerned" | "intervention_needed"\n'
            '- next_action: "monitor" | "nudge" | "call" | "escalate"\n'
            "- reasoning: brief explanation\n"
            "- confidence: 0.0-1.0\n"
            "- message_to_user: optional message (null if monitoring)\n"
        )
        if target_count is not None:
            prompt += (
                '- goal_adjustment: optional {"direction": "easier"|"harder", '
                '"suggestion": "...", "new_config": {...}} or null '
                "(only when the target clearly needs adjusting based on sustained pattern)\n"
            )
        else:
            prompt += "- goal_adjustment: null (not applicable for non-quantifiable goals)\n"
        prompt += "Do not include any emojis.\n"
        return prompt

    def analyze(self, user_id: str, goal_id: str, config: dict, goal_meta: dict) -> AgentResult:
        system_prompt = self._build_system_prompt(goal_meta, config)

        logs = self.get_logs(user_id, goal_id, days=7)
        log_texts = [l["content"][:120] for l in logs[:10]]

        # Compute deterministic stats so the agent reasons from facts, not text inference
        from shared.supabase_client import compute_goal_stats
        stats = compute_goal_stats(user_id, goal_id, config)

        context = self.get_cross_context(
            user_id,
            f"User progress and context for goal: {goal_meta['name']}",
        )
        context_summary = "\n".join(
            c["content"][:120] for c in context[:4] if c.get("content")
        )

        peer_states = self.get_peer_states(user_id, goal_id)

        user_prompt = (
            f"Goal: {goal_meta['name']}\n"
            f"Config: {config}\n"
            f"Stats: {stats}\n"
            f"Recent logs (last 7 days, for context): {log_texts}\n"
            f"Context: {context_summary[:400]}\n"
            f"Other goals: {peer_states[:400]}\n\n"
            "How is the user doing with this goal? Use the Stats block as your primary source of truth."
        )

        assessment = self.llm_assess(system_prompt, user_prompt)

        result = AgentResult(
            status=assessment.get("status", "monitoring"),
            next_action=assessment.get("next_action", "monitor"),
            reasoning=assessment.get("reasoning", ""),
            confidence=assessment.get("confidence", 0.5),
            context_summary=context_summary[:500],
            message_to_user=assessment.get("message_to_user"),
            goal_adjustment=assessment.get("goal_adjustment"),
        )

        if result.status != "monitoring":
            self.save_observation(
                user_id,
                goal_id,
                f"{goal_meta['agent_name']} detected '{result.status}': {result.reasoning}",
                confidence=result.confidence,
            )

        return result
