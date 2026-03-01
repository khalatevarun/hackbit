from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from typing import Callable

from shared import supabase_client as db
from shared import telegram_client


# ---------------------------------------------------------------------------
# Agent persona definitions — label, emoji, header, voice
# ---------------------------------------------------------------------------

AGENT_PERSONAS: dict[str, dict] = {
    "sleep": {
        "label": "Sleep",
        "emoji": "🌙",
        "header": "🌙 *Sleep*",
        "voice": "I've gone through your sleep updates and",
    },
    "fitness": {
        "label": "Fitness",
        "emoji": "🏃",
        "header": "🏃 *Fitness*",
        "voice": "I've looked at your fitness logs and",
    },
    "money": {
        "label": "Budget",
        "emoji": "💰",
        "header": "💰 *Budget*",
        "voice": "I've been through your spending and",
    },
    "social": {
        "label": "Social",
        "emoji": "🤝",
        "header": "🤝 *Social*",
        "voice": "I've gone through your recent updates and",
    },
    "short_lived": {
        "label": "Focus",
        "emoji": "📚",
        "header": "📚 *Focus*",
        "voice": "I've looked at where you are with your deadline and",
    },
    "custom": {
        "label": "Focus",
        "emoji": "📚",
        "header": "📚 *Focus*",
        "voice": "I've looked at where you are with your deadline and",
    },
    "coordinator": {
        "label": "hackbitz",
        "emoji": "⚡",
        "header": "⚡ *hackbitz*",
        "voice": "I've looked at everything going on and",
    },
}

# Priority order for tiebreaking when multiple agents are concerned
TEMPLATE_PRIORITY = ["sleep", "fitness", "money", "social", "short_lived", "custom"]

# next_action → human-readable status for /status
ACTION_TO_STATUS: dict[str, str] = {
    "monitor": "✅ on track",
    "nudge": "⚠️ watch this",
    "call": "⚠️ needs attention",
    "escalate": "🔴 off track",
}

HELP_TEXT = (
    "⚡ *hackbitz*\n\n"
    "I've gone through your goals and I'm here to help. Here's what I can do:\n\n"
    "• Just tell me anything — how you slept, if you worked out, what you spent. I'll keep track.\n"
    "• `/status` — Quick health check across all your goals.\n"
    "• `/confused` — I'll name the ONE thing that matters most right now.\n"
    "• `/plan` — Today's top priorities given what's going on.\n"
    "• `/checkin` — Full fresh analysis of everything. Takes ~60s.\n"
    "• `/addgoal <description>` — Add a new goal in plain language.\n"
    "• `/deletegoal` — List your goals to remove one.\n"
    "• `/reset` — Wipe all your data and start fresh.\n"
    "• `/help` — This message.\n\n"
    "I'll reach out when something needs your attention. Otherwise, I stay quiet."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Parse JSON from LLM output, stripping markdown fences if present.
    Falls back to regex extraction of the first {...} block if direct parse fails.
    """
    text = text.strip()
    # Strip markdown fences
    fence = re.match(r"^```(?:json)?\s*\n?", text)
    if fence:
        text = text[fence.end():]
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # LLM added preamble/postamble — find the first complete JSON object
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
        raise


def _get_persona(template: str) -> dict:
    return AGENT_PERSONAS.get(template, AGENT_PERSONAS["coordinator"])


def _build_telegram_message(
    header: str,
    body: str,
    exa_results: list[dict] | None = None,
) -> str:
    """Build formatted Telegram message with a labeled header and optional Exa content links."""
    msg = f"{header}\n\n{body}"
    if not exa_results:
        return msg
    for r in exa_results:
        intro = r.get("intro", "")
        title = r.get("title", "")
        url = r.get("url", "")
        snippet = r.get("snippet", "")
        if intro:
            msg += f"\n\n{intro}\n[{title}]({url})"
        else:
            label = r.get("flavor_label", "📖 *Read*")
            msg += f"\n\n{label}\n[{title}]({url})"
        if snippet:
            msg += f'\n_{snippet[:150]}_'
    return msg


def _send_telegram(user_id: str, text: str) -> bool:
    chat_id = db.get_telegram_chat_id(user_id)
    if not chat_id:
        print(f"[coordinator] No telegram_chat_id for user {user_id[:8]} — skipping send")
        return False
    return telegram_client.send_message(chat_id, text)


def _log_intervention(
    user_id: str,
    intervention_type: str,
    reason: str,
    triggered_by: list[str],
    goal_id: str | None = None,
) -> str | None:
    """Create an intervention record and return its ID."""
    intervention = db.create_intervention(
        user_id=user_id,
        intervention_type=intervention_type,
        reason=reason,
        scheduled_for=datetime.now(timezone.utc).isoformat(),
        triggered_by=triggered_by,
        goal_id=goal_id,
    )
    return intervention.get("id")



def _build_states_summary(agent_states: list[dict]) -> str:
    """Human-readable summary of all agent states for LLM context."""
    lines = []
    for s in agent_states:
        state = s.get("state", {})
        goal_info = s.get("goals") or {}
        template = goal_info.get("agent_template", "unknown")
        goal_name = goal_info.get("name", template)
        next_action = state.get("next_action", "monitor")
        context = state.get("context_summary", "")[:150]
        lines.append(f"- {template.capitalize()} ({goal_name}): {next_action}. {context}")
    return "\n".join(lines) if lines else "No active goals."


# ---------------------------------------------------------------------------
# Pattern & win detection
# ---------------------------------------------------------------------------

def _check_patterns(user_id: str, agent_states: list[dict]) -> dict:
    """Detect 3+ tick concerning patterns and win flips in agent states.

    Returns:
        {
            "patterns": [{goal_id, template, severity, context_summary}, ...],
            "wins":     [{goal_id, template}, ...],
        }
    """
    patterns = []
    wins = []
    concerning = ("nudge", "call", "escalate")

    for s in agent_states:
        state = s.get("state", {})
        state_history: list[dict] = s.get("state_history") or []
        goal_info = s.get("goals") or {}
        template = goal_info.get("agent_template", "unknown")
        goal_id = s["goal_id"]
        current_action = state.get("next_action", "monitor")
        context_summary = state.get("context_summary", "")

        # Pattern: last 3 state_history entries all concerning
        if len(state_history) >= 3:
            last_3 = state_history[-3:]
            if all(e.get("next_action") in concerning for e in last_3):
                severity = (
                    "escalate"
                    if any(e.get("next_action") == "escalate" for e in last_3)
                    else "nudge"
                )
                patterns.append({
                    "goal_id": goal_id,
                    "template": template,
                    "severity": severity,
                    "context_summary": context_summary,
                })

        # Win: was in pattern (3 entries before current all concerning), now monitoring
        if len(state_history) >= 4 and current_action == "monitor":
            pre_current = state_history[-4:-1]
            if all(e.get("next_action") in concerning for e in pre_current):
                wins.append({"goal_id": goal_id, "template": template})

    return {"patterns": patterns, "wins": wins}


# ---------------------------------------------------------------------------
# Public command handlers (called directly from webhook, synchronous)
# ---------------------------------------------------------------------------

def handle_status_command(user_id: str) -> str:
    """Build /status response — no LLM needed."""
    agent_states = db.get_agent_states_for_user(user_id)
    if not agent_states:
        return "⚡ *hackbitz*\n\nNo active goals found."

    lines = ["⚡ *hackbitz*\n"]
    for s in agent_states:
        state = s.get("state", {})
        goal_info = s.get("goals") or {}
        template = goal_info.get("agent_template", "unknown")
        goal_name = goal_info.get("name", template)
        next_action = state.get("next_action", "monitor")
        status_label = ACTION_TO_STATUS.get(next_action, "monitoring")
        persona = _get_persona(template)
        lines.append(f"{persona['emoji']} {goal_name} — {status_label}")

    return "\n".join(lines)


def handle_confused_command(user_id: str, llm_fn: Callable[..., str]) -> str:
    """Build /confused response: ONE thing to focus on right now."""
    agent_states = db.get_agent_states_for_user(user_id)
    states_summary = _build_states_summary(agent_states)

    system_prompt = (
        "You are hackbitz — you look across everything happening in a person's life. "
        "Speak directly to them like a decisive helpful friend. "
        "Use phrases like 'I've looked at everything going on', 'Here's what I think you should focus on today', "
        "'Let me help you cut through this'. "
        "Be decisive. Name ONE thing to focus on right now and explain why briefly. "
        "3-4 sentences max. Never say 'the user', 'companion', or 'agent'."
    )
    user_prompt = (
        f"Current goal states:\n{states_summary}\n\n"
        "What's the ONE most important thing to focus on right now and why?"
    )

    body = llm_fn(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        0.5,
    )
    return _build_telegram_message("⚡ *hackbitz*", body)


def handle_plan_command(user_id: str, llm_fn: Callable[..., str]) -> str:
    """Build /plan response: today's top 3 priorities."""
    agent_states = db.get_agent_states_for_user(user_id)
    states_summary = _build_states_summary(agent_states)

    system_prompt = (
        "You are hackbitz. "
        "Speak directly to them like a decisive helpful friend. "
        "Use phrases like 'Here's what I think you should tackle today', 'Let me help you prioritize'. "
        "Give an ordered list of today's top 3 priorities given what you know. "
        "Be specific and realistic. Max 3 items. "
        "Never say 'the user', 'companion', or 'agent'."
    )
    user_prompt = (
        f"Current goal states:\n{states_summary}\n\nList today's top 3 priorities."
    )

    body = llm_fn(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        0.5,
    )
    return _build_telegram_message("⚡ *hackbitz*", body)


def _parse_and_create_goal(description: str, user_id: str, llm_fn: Callable[..., str]) -> dict:
    """Parse free-text goal description via LLM and create the goal in DB."""
    system_prompt = (
        "Extract a structured goal from the user's description. "
        "Return ONLY valid JSON with these fields:\n"
        "- name: short goal name (5-8 words)\n"
        "- agent_template: one of: fitness, sleep, money, social, short_lived\n"
        "- type: one of: habit, target, short_lived\n"
        "- config: object with template-specific fields:\n"
        "  - sleep: {\"target_hours\": N, \"target_bedtime\": \"HH:MM\"}\n"
        "  - fitness: {\"frequency_per_week\": N, \"target\": \"description\"}\n"
        "  - money: {\"weekly_budget\": N, \"watch_categories\": [\"...\"]}\n"
        "  - social: {\"min_social_per_week\": N}\n"
        "  - short_lived: {\"end_date\": \"YYYY-MM-DD\", \"success_criteria\": \"...\"}\n"
        "- end_at: ISO datetime string or null\n"
        "Return only the JSON object, no explanation."
    )

    raw = llm_fn(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Goal description: {description}"},
        ],
        0.3,
    )

    parsed = _extract_json(raw)

    # Normalize end_at: LLM often returns "YYYY-MM-DD"; Postgres needs full ISO timestamptz
    end_at = parsed.get("end_at")
    if end_at and isinstance(end_at, str):
        # "2026-03-01" → "2026-03-01T00:00:00+00:00"
        if re.match(r"^\d{4}-\d{2}-\d{2}$", end_at.strip()):
            end_at = f"{end_at.strip()}T00:00:00+00:00"
    else:
        end_at = None

    return db.create_goal(
        user_id=user_id,
        name=parsed.get("name", description[:50]),
        goal_type=parsed.get("type", "habit"),
        agent_template=parsed.get("agent_template", "short_lived"),
        config=parsed.get("config", {}),
        end_at=end_at,
    )


def handle_addgoal_command(description: str, user_id: str, llm_fn: Callable[..., str]) -> str:
    """Handle /addgoal command — parse free text and create a goal."""
    if not description.strip():
        return (
            "⚡ *hackbitz*\n\n"
            "Tell me what goal you want to add. Example:\n"
            "`/addgoal I want to sleep 8 hours, in bed by 11pm`"
        )
    try:
        goal = _parse_and_create_goal(description.strip(), user_id, llm_fn)
        goal_name = goal.get("name", description[:50])
        return f"⚡ *hackbitz*\n\n✅ Added: {goal_name}. I'll start keeping an eye on this."
    except Exception as e:
        import traceback
        print(f"[coordinator] addgoal error: {e}")
        traceback.print_exc()
        return "⚡ *hackbitz*\n\nSomething went wrong adding that goal. Try again?"


def handle_deletegoal_list_command(user_id: str) -> str:
    """Handle /deletegoal (no args) — list active goals numbered."""
    goals = db.get_active_goals(user_id=user_id)
    if not goals:
        return "⚡ *hackbitz*\n\nYou don't have any active goals right now."

    goals_sorted = sorted(goals, key=lambda g: g.get("created_at", ""))
    lines = [
        "⚡ *hackbitz*\n",
        "Here are your active goals. Reply with /deletegoal <number> to remove one:\n",
    ]
    for i, g in enumerate(goals_sorted, 1):
        template = g.get("agent_template", "custom")
        persona = _get_persona(template)
        lines.append(f"{i}. {g['name']} {persona['emoji']}")
    return "\n".join(lines)


def handle_deletegoal_number_command(user_id: str, number: int) -> str:
    """Handle /deletegoal <number> — deactivate goal by list position."""
    goals = db.get_active_goals(user_id=user_id)
    if not goals:
        return "⚡ *hackbitz*\n\nYou don't have any active goals right now."

    goals_sorted = sorted(goals, key=lambda g: g.get("created_at", ""))
    if number < 1 or number > len(goals_sorted):
        return (
            f"⚡ *hackbitz*\n\n"
            f"I don't see a goal with that number. You have {len(goals_sorted)} active goal(s)."
        )

    goal = goals_sorted[number - 1]
    db.deactivate_goal(goal["id"])
    return f"⚡ *hackbitz*\n\nRemoved: {goal['name']}. I'll stop tracking this."


# ---------------------------------------------------------------------------
# Main coordinator entrypoint
# ---------------------------------------------------------------------------

def coordinate_for_user(
    user_id: str,
    llm_fn: Callable[..., str] | None = None,
    mode: str = "pattern_check",
    source_goal_id: str | None = None,
    trigger_log: str | None = None,
) -> dict | None:
    """Run coordinator logic for a single user.

    Modes:
    - reactive_log:   User sent a text log. Respond on behalf of the matching agent.
    - pattern_check:  Cron tick. Check for 3+ tick patterns and send if threshold crossed.
    - win:            An agent just flipped from pattern to monitoring; celebrate.
    """
    if mode == "reactive_log":
        return _handle_reactive_log(user_id, llm_fn, source_goal_id, trigger_log)
    elif mode == "pattern_check":
        return _handle_pattern_check(user_id, llm_fn)
    elif mode == "win":
        return _handle_win(user_id, llm_fn, source_goal_id)
    elif mode == "checkin":
        return _handle_checkin(user_id, llm_fn)
    else:
        return {"decision": "no_action", "reason": f"unknown mode: {mode}"}


# ---------------------------------------------------------------------------
# Internal mode handlers
# ---------------------------------------------------------------------------

def _handle_reactive_log(
    user_id: str,
    llm_fn: Callable[..., str],
    source_goal_id: str | None,
    trigger_log: str | None,
) -> dict:
    """Respond to a user log on behalf of the matching agent."""
    from shared import exa_client

    agent_states = db.get_agent_states_for_user(user_id)

    # Find the agent state matching source_goal_id
    matched_state = None
    goal_name_for_ack = None
    if source_goal_id:
        for s in agent_states:
            if s["goal_id"] == source_goal_id:
                matched_state = s
                break
        # Even if no state, try to get the goal name for the ack
        if not matched_state:
            goals = db.get_active_goals(user_id=user_id)
            goal_info = next((g for g in goals if g["id"] == source_goal_id), None)
            if goal_info:
                goal_name_for_ack = goal_info.get("name")

    if not matched_state:
        if goal_name_for_ack:
            _send_telegram(user_id, f"⚡ *hackbitz*\n\nGot it — logged under _{goal_name_for_ack}_. I'll factor this in.")
        else:
            _send_telegram(user_id, "⚡ *hackbitz*\n\nGot it, noted.")
        return {"decision": "ack", "reason": "no agent state yet — sent ack"}

    state = matched_state.get("state", {})
    goal_info = matched_state.get("goals") or {}
    template = goal_info.get("agent_template", "unknown")
    goal_name = goal_info.get("name", template)
    next_action = state.get("next_action", "monitor")
    context_summary = state.get("context_summary", "")

    # Monitoring → brief ack instead of silence
    if next_action == "monitor":
        persona = _get_persona(template)
        _send_telegram(user_id, f"{persona['header']}\n\nGot it, logged. You're on track with _{goal_name}_ — keep it up.")
        return {"decision": "ack", "reason": "agent monitoring — sent brief ack"}

    # Dedup: skip full response if this goal already had an intervention in the last 6h,
    # but still ack
    recent = db.get_recent_interventions(user_id, goal_id=source_goal_id, hours=6)
    if recent:
        _send_telegram(user_id, f"⚡ *hackbitz*\n\nLogged under _{goal_name}_.")
        return {"decision": "ack", "reason": "dedup — sent brief ack"}

    persona = _get_persona(template)
    header = persona["header"]

    if next_action in ("nudge", "call"):
        length_instruction = (
            "Write 1-2 warm sentences. Start from what they said, not from your analysis."
        )
    else:  # escalate
        length_instruction = (
            "Write a brief paragraph (3-4 sentences max). Be warm but direct about the pattern."
        )

    system_prompt = (
        f"You are the {persona['label']} — {persona['voice']}. "
        "Speak directly to them like a helpful friend. "
        "Use phrases like 'I've gone through your updates', 'Let me help you with this', "
        "'Here's what I think you should do', 'I can see what's happening'. "
        "Address them as 'you'. "
        "Never say 'the user', 'companion', or 'agent'. "
        "Never start your message with a label or category heading. "
        f"{length_instruction}"
    )
    user_prompt = (
        f"The user just said: \"{trigger_log or 'logged something'}\"\n"
        f"Goal: {goal_name}\n"
        f"Assessment: {context_summary[:300]}\n"
        f"Severity: {next_action}\n\n"
        "Respond to what they said. Begin from their words."
    )

    body = llm_fn(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        0.7,
    )

    # Exa for nudge + call + escalate (monitor stays silent)
    exa_results = []
    if next_action in ("nudge", "call", "escalate"):
        topics = exa_client.DOMAIN_TOPICS.get(template, ["wellness"])
        topic = random.choice(topics)
        exa_results = exa_client.search_content_multi(
            topic, template, trigger_log=trigger_log, count=3,
        )

    telegram_text = _build_telegram_message(header, body, exa_results or None)
    intervention_id = _log_intervention(
        user_id,
        next_action,
        f"Reactive log: {context_summary[:100]}",
        [template],
        goal_id=source_goal_id,
    )
    sent = _send_telegram(user_id, telegram_text)
    if sent and intervention_id:
        db.mark_intervention_executed(intervention_id)

    return {"decision": "reactive_log", "template": template, "action": next_action}


def _handle_pattern_check(user_id: str, llm_fn: Callable[..., str]) -> dict:
    """Check for 3+ tick patterns and wins; send messages if thresholds are crossed."""
    from shared import exa_client

    agent_states = db.get_agent_states_for_user(user_id)
    if not agent_states:
        return {"decision": "no_action", "reason": "no agent states"}

    result = _check_patterns(user_id, agent_states)
    patterns = result.get("patterns", [])
    wins = result.get("wins", [])

    # --- Win messages (bypass dedup — they're rare and positive) ---
    for win in wins:
        template = win["template"]
        persona = _get_persona(template)
        system_prompt = (
            f"You are the {persona['label']}. "
            "Speak directly to them like a warm, encouraging friend. "
            "1 warm sentence celebrating a win. "
            "Never say 'the user', 'companion', or 'agent'."
        )
        body = llm_fn(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"The {persona['label'].lower()} goal just bounced back after a rough patch. "
                        "Celebrate this win warmly in one sentence."
                    ),
                },
            ],
            0.8,
        )
        _send_telegram(user_id, _build_telegram_message(persona["header"], body))

    if not patterns:
        return {
            "decision": "win_message" if wins else "no_action",
            "wins": len(wins),
        }

    # --- Pattern dedup: global 6h check ---
    recent = db.get_recent_interventions(user_id, hours=6)
    if recent:
        return {"decision": "no_action", "reason": "dedup: recent intervention within 6h"}

    # --- Multiple agents concerned → coordinator (hackbitz) simplification ---
    if len(patterns) >= 2:
        # Highest-priority concern leads the message
        primary = sorted(
            patterns,
            key=lambda p: TEMPLATE_PRIORITY.index(p["template"])
            if p["template"] in TEMPLATE_PRIORITY
            else 99,
        )[0]
        others = [p["template"] for p in patterns if p["template"] != primary["template"]]
        patterns_summary = "\n".join(
            f"- {p['template'].capitalize()}: {p['severity']}. {p.get('context_summary', '')[:100]}"
            for p in patterns
        )

        system_prompt = (
            "You are hackbitz — you look across everything happening in a person's life. "
            "Speak directly to them like a decisive helpful friend. "
            "Use phrases like 'I've looked at everything going on', 'Here's what I think you should focus on', "
            "'Let me help you prioritize this'. "
            "Be decisive. Name ONE thing to focus on. "
            "Say explicitly that the others can wait. "
            "3-4 sentences max. Never say 'the user', 'companion', or 'agent'."
        )
        user_prompt = (
            f"Multiple areas need attention:\n{patterns_summary}\n\n"
            f"The highest priority is {primary['template']}. "
            f"The others ({', '.join(others)}) can wait. "
            "Name the ONE thing. Tell them the rest can wait."
        )

        body = llm_fn(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            0.5,
        )

        topics = exa_client.DOMAIN_TOPICS.get(primary["template"], ["wellness"])
        exa_results = exa_client.search_content_multi(
            random.choice(topics), primary["template"], count=3,
        )
        telegram_text = _build_telegram_message("⚡ *hackbitz*", body, exa_results or None)
        intervention_id = _log_intervention(
            user_id,
            "pattern_multi",
            f"Multi-pattern: {[p['template'] for p in patterns]}",
            [p["template"] for p in patterns],
        )
        sent = _send_telegram(user_id, telegram_text)
        if sent and intervention_id:
            db.mark_intervention_executed(intervention_id)

    # --- Single agent pattern → that agent speaks ---
    else:
        pattern = patterns[0]
        template = pattern["template"]
        persona = _get_persona(template)
        severity = pattern["severity"]
        context_summary = pattern.get("context_summary", "")

        system_prompt = (
            f"You are the {persona['label']} — {persona['voice']}. "
            "Speak directly to them like a helpful friend. "
            "Use phrases like 'I've gone through your updates', 'Let me help you with this', "
            "'I can see what's happening here'. "
            "2-3 direct, warm sentences. No labels, no hedging. "
            "Never say 'the user', 'companion', or 'agent'."
        )
        user_prompt = (
            f"Pattern detected: {severity} for 3+ consecutive checks.\n"
            f"Context: {context_summary[:300]}\n\n"
            "Write 2-3 direct, warm sentences about this pattern."
        )

        body = llm_fn(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            0.6,
        )

        topics = exa_client.DOMAIN_TOPICS.get(template, ["wellness"])
        exa_results = exa_client.search_content_multi(
            random.choice(topics), template, count=3,
        )
        telegram_text = _build_telegram_message(persona["header"], body, exa_results or None)
        intervention_id = _log_intervention(
            user_id,
            severity,
            f"Pattern: {template} {severity}",
            [template],
        )
        sent = _send_telegram(user_id, telegram_text)
        if sent and intervention_id:
            db.mark_intervention_executed(intervention_id)

    return {"decision": "pattern_detected", "patterns": len(patterns), "wins": len(wins)}


def _handle_win(
    user_id: str,
    llm_fn: Callable[..., str],
    goal_id: str | None,
) -> dict:
    """Send a standalone win celebration message (bypasses dedup)."""
    if not goal_id:
        return {"decision": "no_action", "reason": "no goal_id for win"}

    agent_states = db.get_agent_states_for_user(user_id)
    matched = next((s for s in agent_states if s["goal_id"] == goal_id), None)
    if not matched:
        return {"decision": "no_action", "reason": "goal state not found"}

    goal_info = matched.get("goals") or {}
    template = goal_info.get("agent_template", "unknown")
    persona = _get_persona(template)

    system_prompt = (
        f"You are the {persona['label']}. "
        "Speak directly to them like a warm, encouraging friend. "
        "1 warm sentence celebrating a win. "
        "Never say 'the user', 'companion', or 'agent'."
    )
    body = llm_fn(
        [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"The {persona['label'].lower()} goal just bounced back after a rough patch. "
                    "Celebrate warmly in one sentence."
                ),
            },
        ],
        0.8,
    )

    _send_telegram(user_id, _build_telegram_message(persona["header"], body))
    return {"decision": "win", "template": template}


def _handle_checkin(user_id: str, llm_fn: Callable[..., str]) -> dict:
    """Full life snapshot for /checkin — runs after agents have refreshed states."""
    from shared import exa_client

    agent_states = db.get_agent_states_for_user(user_id)
    if not agent_states:
        _send_telegram(user_id, "⚡ *hackbitz*\n\nNo active goals found. Add some with /addgoal to get started.")
        return {"decision": "checkin", "goals": 0}

    states_summary = _build_states_summary(agent_states)

    system_prompt = (
        "You are hackbitz — you look across everything happening in a person's life. "
        "Speak directly to them like a decisive, caring friend who just ran a full check-in. "
        "Use phrases like 'I've just gone through everything', 'Here's where things stand', "
        "'Let me tell you what I see'. "
        "Give a 'state of your life' summary — 2-3 sentences covering all areas, "
        "name what's going well, then name the ONE thing that needs attention most. "
        "Be warm but direct. Never say 'the user', 'companion', or 'agent'."
    )
    user_prompt = (
        f"Current goal states:\n{states_summary}\n\n"
        "Give a full check-in: what's going well, what needs attention, and the one priority."
    )

    body = llm_fn(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        0.5,
    )

    # Find top concern for Exa
    concerning = ("nudge", "call", "escalate")
    top_concern = None
    top_context = ""
    for template in TEMPLATE_PRIORITY:
        for s in agent_states:
            goal_info = s.get("goals") or {}
            if goal_info.get("agent_template") == template:
                state = s.get("state", {})
                if state.get("next_action") in concerning:
                    top_concern = template
                    top_context = state.get("context_summary", "")
                    break
        if top_concern:
            break

    exa_results = []
    if top_concern:
        topics = exa_client.DOMAIN_TOPICS.get(top_concern, ["wellness"])
        exa_results = exa_client.search_content_multi(
            random.choice(topics), top_concern, count=3,
        )

    telegram_text = _build_telegram_message("⚡ *hackbitz*", body, exa_results or None)
    _send_telegram(user_id, telegram_text)
    return {"decision": "checkin", "goals": len(agent_states)}
