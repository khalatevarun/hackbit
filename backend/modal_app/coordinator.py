from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from typing import Callable

from shared import supabase_client as db
from shared import telegram_client


# ---------------------------------------------------------------------------
# Priority engine -- replaces hardcoded TEMPLATE_PRIORITY
# ---------------------------------------------------------------------------

PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2}
SEVERITY_ORDER = {"escalate": 0, "call": 1, "nudge": 2, "monitor": 3}

ACTION_TO_LABEL: dict[str, str] = {
    "monitor": "on track",
    "nudge": "watch this",
    "call": "needs attention",
    "escalate": "off track",
}


def _sort_by_priority(agent_states: list[dict]) -> list[dict]:
    """Sort agent states by goal priority (critical first), then by severity."""
    def key(s):
        goal = s.get("goals") or {}
        priority = goal.get("priority", "normal")
        action = (s.get("state") or {}).get("next_action", "monitor")
        return (PRIORITY_ORDER.get(priority, 2), SEVERITY_ORDER.get(action, 3))
    return sorted(agent_states, key=key)


def _get_agent_name(goal_info: dict) -> str:
    return goal_info.get("agent_name") or goal_info.get("name", "Goal")


HELP_TEXT = (
    "*hackbitz*\n\n"
    "Here's what I can do:\n\n"
    "- Just tell me anything -- how you slept, if you worked out, what you spent. I'll keep track.\n"
    "- /list -- See all your active goals and their status.\n"
    "- /confused -- I'll name the ONE thing that matters most right now.\n"
    "- /plan -- Today's top priorities given what's going on.\n"
    "- /checkin -- Full fresh analysis of everything. Takes about 60s.\n"
    "- /addgoal <description> -- Add a new goal in plain language.\n"
    "- /deletegoal -- List your goals to remove one.\n"
    "- /reset -- Wipe all your data and start fresh.\n"
    "- /help -- This message.\n\n"
    "I'll reach out when something needs your attention. Otherwise, I stay quiet."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Parse JSON from LLM output, stripping markdown fences if present."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n?", text)
    if fence:
        text = text[fence.end():]
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
        raise


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
            label = r.get("flavor_label", "*Read*")
            msg += f"\n\n{label}\n[{title}]({url})"
        if snippet:
            msg += f'\n_{snippet[:150]}_'
    return msg


def _send_telegram(user_id: str, text: str) -> bool:
    chat_id = db.get_telegram_chat_id(user_id)
    if not chat_id:
        print(f"[coordinator] No telegram_chat_id for user {user_id[:8]} -- skipping send")
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
        agent_name = _get_agent_name(goal_info)
        goal_name = goal_info.get("name", agent_name)
        priority = goal_info.get("priority", "normal")
        next_action = state.get("next_action", "monitor")
        context = state.get("context_summary", "")[:150]
        lines.append(f"- {agent_name} ({goal_name}): {next_action}, priority={priority}. {context}")
    return "\n".join(lines) if lines else "No active goals."


def _get_exa_topics(goal_info: dict) -> list[str]:
    """Extract domain_topics from goal config, falling back to goal name."""
    config = goal_info.get("config") or {}
    topics = config.get("domain_topics")
    if topics and isinstance(topics, list):
        return topics
    return [goal_info.get("name", "wellness")]


# ---------------------------------------------------------------------------
# Pattern & win detection
# ---------------------------------------------------------------------------

def _check_patterns(user_id: str, agent_states: list[dict]) -> dict:
    """Detect 3+ tick concerning patterns and win flips in agent states."""
    patterns = []
    wins = []
    concerning = ("nudge", "call", "escalate")

    for s in agent_states:
        state = s.get("state", {})
        state_history: list[dict] = s.get("state_history") or []
        goal_info = s.get("goals") or {}
        agent_name = _get_agent_name(goal_info)
        goal_id = s["goal_id"]
        current_action = state.get("next_action", "monitor")
        context_summary = state.get("context_summary", "")
        priority = goal_info.get("priority", "normal")

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
                    "agent_name": agent_name,
                    "severity": severity,
                    "context_summary": context_summary,
                    "priority": priority,
                })

        if len(state_history) >= 4 and current_action == "monitor":
            pre_current = state_history[-4:-1]
            if all(e.get("next_action") in concerning for e in pre_current):
                wins.append({"goal_id": goal_id, "agent_name": agent_name})

    return {"patterns": patterns, "wins": wins}


# ---------------------------------------------------------------------------
# Public command handlers (called directly from webhook, synchronous)
# ---------------------------------------------------------------------------

def handle_list_command(user_id: str) -> str:
    """Build /list response -- no LLM needed."""
    goals = db.get_active_goals(user_id=user_id)
    if not goals:
        return "*hackbitz*\n\nNo active goals. Add some with /addgoal."

    agent_states = db.get_agent_states_for_user(user_id)
    state_map = {s["goal_id"]: s for s in agent_states}

    goals_sorted = sorted(goals, key=lambda g: g.get("created_at", ""))
    lines = ["*hackbitz*\n", "Your goals:\n"]
    for i, g in enumerate(goals_sorted, 1):
        agent_name = g.get("agent_name", "Goal")
        goal_name = g.get("name", "")
        priority = g.get("priority", "normal")

        s = state_map.get(g["id"])
        if s:
            action = (s.get("state") or {}).get("next_action", "monitor")
            status_label = ACTION_TO_LABEL.get(action, "on track")
        else:
            status_label = "just started"

        line = f"{i}. {agent_name} -- {goal_name} -- {status_label}"
        if priority in ("high", "critical"):
            line += f" [{priority}]"
        lines.append(line)
    return "\n".join(lines)


def handle_confused_command(user_id: str, llm_fn: Callable[..., str]) -> str:
    """Build /confused response: ONE thing to focus on right now."""
    agent_states = db.get_agent_states_for_user(user_id)
    states_summary = _build_states_summary(_sort_by_priority(agent_states))

    system_prompt = (
        "You are hackbitz -- you look across everything happening in a person's life. "
        "Speak directly to them like a decisive helpful friend. "
        "Be decisive. Name ONE thing to focus on right now and explain why briefly. "
        "3-4 sentences max. Never say 'the user', 'companion', or 'agent'. "
        "Do not include any emojis."
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
    return _build_telegram_message("*hackbitz*", body)


def handle_plan_command(user_id: str, llm_fn: Callable[..., str]) -> str:
    """Build /plan response: today's top 3 priorities."""
    agent_states = db.get_agent_states_for_user(user_id)
    states_summary = _build_states_summary(_sort_by_priority(agent_states))

    system_prompt = (
        "You are hackbitz. "
        "Speak directly to them like a decisive helpful friend. "
        "Give an ordered list of today's top 3 priorities given what you know. "
        "Be specific and realistic. Max 3 items. "
        "Never say 'the user', 'companion', or 'agent'. "
        "Do not include any emojis."
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
    return _build_telegram_message("*hackbitz*", body)


def _parse_and_create_goal(description: str, user_id: str, llm_fn: Callable[..., str]) -> dict:
    """Parse free-text goal description via LLM and create the goal in DB."""
    system_prompt = (
        "Extract a structured goal from the user's description. "
        "Return ONLY valid JSON with these fields:\n"
        "- name: short goal name (5-8 words)\n"
        "- agent_name: a concise, unique persona name for this goal (1-2 words, e.g. 'Leetcode', 'Sleep', 'CUDA', 'Guitar', 'Thesis'). "
        "This is how the bot will identify itself when talking about this goal.\n"
        "- agent_template: one of: fitness, sleep, money, social, short_lived, custom\n"
        "- type: one of: habit, target, short_lived\n"
        "- has_deadline: boolean -- true if the description mentions a specific deadline or date\n"
        "- config: object with:\n"
        "  - domain_topics: list of 2-3 search terms relevant to this goal domain (e.g. ['leetcode', 'competitive programming', 'algorithms'])\n"
        "  - target_count: number or null -- measurable numeric target if present (e.g. 10 for '10 problems', 8 for '8 hours sleep'). null for binary habits like 'take vitamins'.\n"
        "  - target_unit: string or null -- unit for target_count ('problems', 'hours', 'km'). null when target_count is null.\n"
        "  - frequency_per_week: number or null\n"
        "  - Any other template-specific fields (target_hours, weekly_budget, success_criteria, etc.)\n"
        "- end_at: ISO datetime string or null\n"
        "Return only the JSON object, no explanation. Do not include any emojis."
    )

    raw = llm_fn(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Goal description: {description}"},
        ],
        0.3,
    )

    parsed = _extract_json(raw)

    end_at = parsed.get("end_at")
    if end_at and isinstance(end_at, str):
        if re.match(r"^\d{4}-\d{2}-\d{2}$", end_at.strip()):
            end_at = f"{end_at.strip()}T00:00:00+00:00"
    else:
        end_at = None

    has_deadline = parsed.get("has_deadline", False)
    personality = "strict" if has_deadline else "warm"
    priority = "critical" if has_deadline else "normal"

    return db.create_goal(
        user_id=user_id,
        name=parsed.get("name", description[:50]),
        goal_type=parsed.get("type", "habit"),
        agent_template=parsed.get("agent_template", "custom"),
        config=parsed.get("config", {}),
        end_at=end_at,
        agent_name=parsed.get("agent_name", parsed.get("name", description[:20])),
        personality=personality,
        priority=priority,
    )


def handle_addgoal_command(description: str, user_id: str, llm_fn: Callable[..., str]) -> tuple[dict | None, str]:
    """Handle /addgoal command -- parse free text and create a goal.

    Returns (goal_dict_or_None, response_text).
    The caller decides whether to send follow-up questions based on the goal.
    """
    if not description.strip():
        return (None, (
            "*hackbitz*\n\n"
            "Tell me what goal you want to add. Example:\n"
            "`/addgoal I want to sleep 8 hours, in bed by 11pm`"
        ))
    try:
        goal = _parse_and_create_goal(description.strip(), user_id, llm_fn)
        return (goal, "")
    except Exception as e:
        import traceback
        print(f"[coordinator] addgoal error: {e}")
        traceback.print_exc()
        return (None, "*hackbitz*\n\nSomething went wrong adding that goal. Try again?")


def handle_deletegoal_list_command(user_id: str) -> str:
    """Handle /deletegoal (no args) -- list active goals numbered."""
    goals = db.get_active_goals(user_id=user_id)
    if not goals:
        return "*hackbitz*\n\nYou don't have any active goals right now."

    goals_sorted = sorted(goals, key=lambda g: g.get("created_at", ""))
    lines = [
        "*hackbitz*\n",
        "Here are your active goals. Reply with /deletegoal <number> to remove one:\n",
    ]
    for i, g in enumerate(goals_sorted, 1):
        agent_name = g.get("agent_name", "Goal")
        lines.append(f"{i}. {agent_name} -- {g['name']}")
    return "\n".join(lines)


def handle_deletegoal_number_command(user_id: str, number: int) -> str:
    """Handle /deletegoal <number> -- deactivate goal by list position."""
    goals = db.get_active_goals(user_id=user_id)
    if not goals:
        return "*hackbitz*\n\nYou don't have any active goals right now."

    goals_sorted = sorted(goals, key=lambda g: g.get("created_at", ""))
    if number < 1 or number > len(goals_sorted):
        return (
            f"*hackbitz*\n\n"
            f"I don't see a goal with that number. You have {len(goals_sorted)} active goal(s)."
        )

    goal = goals_sorted[number - 1]
    db.deactivate_goal(goal["id"])
    agent_name = goal.get("agent_name", "Goal")
    return f"*hackbitz*\n\nRemoved: {agent_name} -- {goal['name']}. I'll stop tracking this."


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
    """Run coordinator logic for a single user."""
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

    matched_state = None
    goal_name_for_ack = None
    agent_name_for_ack = None
    if source_goal_id:
        for s in agent_states:
            if s["goal_id"] == source_goal_id:
                matched_state = s
                break
        if not matched_state:
            goals = db.get_active_goals(user_id=user_id)
            goal_info = next((g for g in goals if g["id"] == source_goal_id), None)
            if goal_info:
                goal_name_for_ack = goal_info.get("name")
                agent_name_for_ack = goal_info.get("agent_name", "Goal")

    if not matched_state:
        if goal_name_for_ack:
            _send_telegram(user_id, f"*hackbitz*\n\nGot it -- logged under _{goal_name_for_ack}_. I'll factor this in.")
        else:
            _send_telegram(user_id, "*hackbitz*\n\nGot it, noted.")
        return {"decision": "ack", "reason": "no agent state yet -- sent ack"}

    state = matched_state.get("state", {})
    goal_info = matched_state.get("goals") or {}
    agent_name = _get_agent_name(goal_info)
    goal_name = goal_info.get("name", agent_name)
    next_action = state.get("next_action", "monitor")
    context_summary = state.get("context_summary", "")
    personality = goal_info.get("personality", "warm")

    if next_action == "monitor":
        _send_telegram(user_id, f"*{agent_name}*\n\nGot it, logged. You're on track with _{goal_name}_ -- keep it up.")
        return {"decision": "ack", "reason": "agent monitoring -- sent brief ack"}

    recent = db.get_recent_interventions(user_id, goal_id=source_goal_id, hours=6)
    if recent:
        _send_telegram(user_id, f"*hackbitz*\n\nLogged under _{goal_name}_.")
        return {"decision": "ack", "reason": "dedup -- sent brief ack"}

    header = f"*{agent_name}*"

    if next_action in ("nudge", "call"):
        length_instruction = "Write 1-2 warm sentences. Start from what they said."
    else:
        length_instruction = "Write a brief paragraph (3-4 sentences max). Be warm but direct."

    personality_instruction = (
        "Be strict and direct. No sugarcoating."
        if personality == "strict"
        else "Be warm and encouraging."
    )

    system_prompt = (
        f"You are {agent_name}. "
        "Speak directly to the user like a helpful friend. "
        f"{personality_instruction} "
        "Address them as 'you'. "
        "Never say 'the user', 'companion', or 'agent'. "
        "Never start your message with a label or heading. "
        "Do not include any emojis. "
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

    exa_results = []
    if next_action in ("nudge", "call", "escalate"):
        topics = _get_exa_topics(goal_info)
        exa_results = exa_client.search_content_multi(
            topics, trigger_log=trigger_log, count=3,
        )

    telegram_text = _build_telegram_message(header, body, exa_results or None)
    intervention_id = _log_intervention(
        user_id,
        next_action,
        f"Reactive log: {context_summary[:100]}",
        [agent_name],
        goal_id=source_goal_id,
    )
    sent = _send_telegram(user_id, telegram_text)
    if sent and intervention_id:
        db.mark_intervention_executed(intervention_id)

    return {"decision": "reactive_log", "agent_name": agent_name, "action": next_action}


def _handle_pattern_check(user_id: str, llm_fn: Callable[..., str]) -> dict:
    """Check for 3+ tick patterns and wins; send messages if thresholds are crossed."""
    from shared import exa_client

    agent_states = db.get_agent_states_for_user(user_id)
    if not agent_states:
        return {"decision": "no_action", "reason": "no agent states"}

    # Check for goal adjustments and send suggestions
    for s in agent_states:
        state = s.get("state", {})
        adjustment = state.get("goal_adjustment")
        if adjustment:
            goal_info = s.get("goals") or {}
            agent_name = _get_agent_name(goal_info)
            suggestion = adjustment.get("suggestion", "")
            goal_id = s["goal_id"]
            chat_id = db.get_telegram_chat_id(user_id)
            if chat_id and suggestion:
                direction = adjustment.get("direction", "easier")
                text = f"*{agent_name}*\n\n{suggestion}"
                buttons = [
                    [
                        {"text": f"Yes, adjust", "callback_data": f"adjust:yes:{goal_id}"},
                        {"text": "Keep as is", "callback_data": f"adjust:no:{goal_id}"},
                    ]
                ]
                telegram_client.send_message_with_buttons(chat_id, text, buttons)

    result = _check_patterns(user_id, agent_states)
    patterns = result.get("patterns", [])
    wins = result.get("wins", [])

    for win in wins:
        agent_name = win["agent_name"]
        system_prompt = (
            f"You are {agent_name}. "
            "Speak directly to them like a warm, encouraging friend. "
            "1 warm sentence celebrating a win. "
            "Never say 'the user', 'companion', or 'agent'. "
            "Do not include any emojis."
        )
        body = llm_fn(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"The {agent_name} goal just bounced back after a rough patch. Celebrate warmly in one sentence."},
            ],
            0.8,
        )
        _send_telegram(user_id, _build_telegram_message(f"*{agent_name}*", body))

    if not patterns:
        return {"decision": "win_message" if wins else "no_action", "wins": len(wins)}

    recent = db.get_recent_interventions(user_id, hours=6)
    if recent:
        return {"decision": "no_action", "reason": "dedup: recent intervention within 6h"}

    if len(patterns) >= 2:
        # Sort patterns by priority
        patterns_sorted = sorted(
            patterns,
            key=lambda p: PRIORITY_ORDER.get(p.get("priority", "normal"), 2),
        )
        primary = patterns_sorted[0]
        others = [p["agent_name"] for p in patterns_sorted if p["agent_name"] != primary["agent_name"]]
        patterns_summary = "\n".join(
            f"- {p['agent_name']}: {p['severity']}, priority={p.get('priority', 'normal')}. {p.get('context_summary', '')[:100]}"
            for p in patterns_sorted
        )

        system_prompt = (
            "You are hackbitz -- you look across everything happening in a person's life. "
            "Speak directly to them like a decisive helpful friend. "
            "Be decisive. Name ONE thing to focus on. "
            "Say explicitly that the others can wait. "
            "3-4 sentences max. Never say 'the user', 'companion', or 'agent'. "
            "Do not include any emojis."
        )
        user_prompt = (
            f"Multiple areas need attention:\n{patterns_summary}\n\n"
            f"The highest priority is {primary['agent_name']}. "
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

        primary_goal_info = None
        for s in agent_states:
            if s["goal_id"] == primary["goal_id"]:
                primary_goal_info = s.get("goals") or {}
                break
        topics = _get_exa_topics(primary_goal_info) if primary_goal_info else ["wellness"]
        exa_results = exa_client.search_content_multi(topics, count=3)
        telegram_text = _build_telegram_message("*hackbitz*", body, exa_results or None)
        intervention_id = _log_intervention(
            user_id,
            "pattern_multi",
            f"Multi-pattern: {[p['agent_name'] for p in patterns]}",
            [p["agent_name"] for p in patterns],
        )
        sent = _send_telegram(user_id, telegram_text)
        if sent and intervention_id:
            db.mark_intervention_executed(intervention_id)
    else:
        pattern = patterns[0]
        agent_name = pattern["agent_name"]
        severity = pattern["severity"]
        context_summary = pattern.get("context_summary", "")

        system_prompt = (
            f"You are {agent_name}. "
            "Speak directly to them like a helpful friend. "
            "2-3 direct, warm sentences. No labels, no hedging. "
            "Never say 'the user', 'companion', or 'agent'. "
            "Do not include any emojis."
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

        pattern_goal_info = None
        for s in agent_states:
            if s["goal_id"] == pattern["goal_id"]:
                pattern_goal_info = s.get("goals") or {}
                break
        topics = _get_exa_topics(pattern_goal_info) if pattern_goal_info else ["wellness"]
        exa_results = exa_client.search_content_multi(topics, count=3)
        telegram_text = _build_telegram_message(f"*{agent_name}*", body, exa_results or None)
        intervention_id = _log_intervention(
            user_id,
            severity,
            f"Pattern: {agent_name} {severity}",
            [agent_name],
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
    agent_name = _get_agent_name(goal_info)

    system_prompt = (
        f"You are {agent_name}. "
        "Speak directly to them like a warm, encouraging friend. "
        "1 warm sentence celebrating a win. "
        "Never say 'the user', 'companion', or 'agent'. "
        "Do not include any emojis."
    )
    body = llm_fn(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"The {agent_name} goal just bounced back after a rough patch. Celebrate warmly in one sentence."},
        ],
        0.8,
    )

    _send_telegram(user_id, _build_telegram_message(f"*{agent_name}*", body))
    return {"decision": "win", "agent_name": agent_name}


def _handle_checkin(user_id: str, llm_fn: Callable[..., str]) -> dict:
    """Full life snapshot for /checkin -- structured output."""
    from shared import exa_client

    agent_states = db.get_agent_states_for_user(user_id)
    if not agent_states:
        _send_telegram(user_id, "*hackbitz*\n\nNo active goals found. Add some with /addgoal to get started.")
        return {"decision": "checkin", "goals": 0}

    sorted_states = _sort_by_priority(agent_states)
    states_summary = _build_states_summary(sorted_states)

    # Get recent logs for streak estimation
    all_logs = db.get_recent_logs(user_id, days=14, limit=100)
    log_summary = []
    for s in sorted_states:
        goal_info = s.get("goals") or {}
        goal_id = s["goal_id"]
        goal_logs = [l for l in all_logs if l.get("goal_id") == goal_id]
        log_dates = [l.get("created_at", "")[:10] for l in goal_logs]
        log_summary.append(f"- {_get_agent_name(goal_info)}: {len(goal_logs)} logs in 14 days, dates: {log_dates[:10]}")

    system_prompt = (
        "You are hackbitz. Return ONLY valid JSON. Do not include any emojis.\n"
        "Analyze the goal states and logs and return:\n"
        "{\n"
        '  "goals": [\n'
        "    {\n"
        '      "name": "agent_name of the goal",\n'
        '      "status": "on_track" | "watch" | "off_track",\n'
        '      "one_liner": "brief status in 5-10 words",\n'
        '      "streak_days": number or 0,\n'
        '      "streak_label": "5-day streak" or "streak broken" or ""\n'
        "    }\n"
        "  ],\n"
        '  "top_priority": "1-2 sentence actionable advice",\n'
        '  "overall_vibe": "mostly_good" | "mixed" | "rough"\n'
        "}"
    )
    user_prompt = (
        f"Goal states:\n{states_summary}\n\n"
        f"Log activity:\n" + "\n".join(log_summary) + "\n\n"
        "Analyze and return the structured JSON."
    )

    raw = llm_fn(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        0.3,
    )

    try:
        checkin_data = _extract_json(raw)
    except (json.JSONDecodeError, ValueError):
        _send_telegram(user_id, _build_telegram_message("*hackbitz*", raw))
        return {"decision": "checkin", "goals": len(agent_states)}

    goals_data = checkin_data.get("goals", [])
    top_priority = checkin_data.get("top_priority", "")

    going_well = [g for g in goals_data if g.get("status") == "on_track"]
    needs_attention = [g for g in goals_data if g.get("status") in ("watch", "off_track")]

    lines = ["*hackbitz -- Check-in*\n"]

    if going_well:
        lines.append("Going well:")
        for g in going_well:
            lines.append(f"- {g['name']} -- {g.get('one_liner', '')}")
        lines.append("")

    if needs_attention:
        lines.append("Needs attention:")
        for g in needs_attention:
            lines.append(f"- {g['name']} -- {g.get('one_liner', '')}")
        lines.append("")

    streaks = [g for g in goals_data if g.get("streak_label")]
    if streaks:
        lines.append("Streaks:")
        for g in streaks:
            lines.append(f"- {g['name']}: {g['streak_label']}")
        lines.append("")

    if top_priority:
        lines.append(f"hackbitz says:\n{top_priority}")

    msg = "\n".join(lines)

    # Exa for top concern
    exa_results = []
    if needs_attention:
        top_concern_name = needs_attention[0].get("name", "")
        for s in sorted_states:
            goal_info = s.get("goals") or {}
            if _get_agent_name(goal_info) == top_concern_name:
                topics = _get_exa_topics(goal_info)
                exa_results = exa_client.search_content_multi(topics, count=3)
                break

    telegram_text = _build_telegram_message("", msg, exa_results or None) if exa_results else msg
    _send_telegram(user_id, telegram_text)
    return {"decision": "checkin", "goals": len(agent_states)}


# ---------------------------------------------------------------------------
# Nightly summary
# ---------------------------------------------------------------------------

def handle_nightly_summary(user_id: str, llm_fn: Callable[..., str]) -> dict:
    """Coordinated evening wrap-up from hackbitz -- one message summarizing all agents."""
    from shared import exa_client

    agent_states = db.get_agent_states_for_user(user_id)
    if not agent_states:
        return {"decision": "no_action", "reason": "no agent states"}

    sorted_states = _sort_by_priority(agent_states)
    states_summary = _build_states_summary(sorted_states)

    today_logs = db.get_recent_logs(user_id, days=1, limit=50)
    log_by_goal: dict[str, int] = {}
    for l in today_logs:
        gid = l.get("goal_id")
        if gid:
            log_by_goal[gid] = log_by_goal.get(gid, 0) + 1

    activity_summary = []
    for s in sorted_states:
        goal_info = s.get("goals") or {}
        agent_name = _get_agent_name(goal_info)
        priority = goal_info.get("priority", "normal")
        count = log_by_goal.get(s["goal_id"], 0)
        activity_summary.append(f"- {agent_name} (priority={priority}): {count} logs today")

    system_prompt = (
        "You are hackbitz. Write an evening wrap-up message. "
        "Speak directly to the user. Be concise and honest. "
        "For each goal, write ONE line about today's progress. "
        "If a critical/high-priority goal needs attention, say so firmly. "
        "If a normal-priority goal should yield to a critical one, say that explicitly. "
        "End with 'Tomorrow's focus:' naming ONE priority. "
        "Never say 'the user', 'companion', or 'agent'. "
        "Do not include any emojis."
    )
    user_prompt = (
        f"Goal states:\n{states_summary}\n\n"
        f"Today's activity:\n" + "\n".join(activity_summary) + "\n\n"
        "Write the evening wrap-up."
    )

    body = llm_fn(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        0.5,
    )

    # Exa for top concern
    exa_results = []
    concerning = ("nudge", "call", "escalate")
    for s in sorted_states:
        state = s.get("state", {})
        if state.get("next_action") in concerning:
            topics = _get_exa_topics(s.get("goals") or {})
            exa_results = exa_client.search_content_multi(topics, count=2)
            break

    telegram_text = _build_telegram_message("*hackbitz -- Evening wrap-up*", body, exa_results or None)
    sent = _send_telegram(user_id, telegram_text)

    if sent:
        _log_intervention(
            user_id,
            "nightly_summary",
            "Coordinated evening wrap-up",
            ["hackbitz"],
        )

    return {"decision": "nightly_summary", "goals": len(agent_states)}


# ---------------------------------------------------------------------------
# Nudge and log-check message generation
# ---------------------------------------------------------------------------

def generate_nudge_message(goal: dict, user_id: str, llm_fn: Callable[..., str]) -> str:
    """Generate a motivational nudge message for a goal."""
    agent_name = goal.get("agent_name", "Goal")
    goal_name = goal.get("name", "")
    personality = goal.get("personality", "warm")

    personality_instruction = (
        "Be strict and direct. No sugarcoating. Push them."
        if personality == "strict"
        else "Be warm and encouraging. Motivate gently."
    )

    system_prompt = (
        f"You are {agent_name}. "
        f"{personality_instruction} "
        "Write a 1-2 sentence reminder/nudge about their goal. "
        "Never say 'the user', 'companion', or 'agent'. "
        "Do not include any emojis."
    )
    body = llm_fn(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Send a reminder about: {goal_name}"},
        ],
        0.7,
    )
    return f"*{agent_name}*\n\n{body}"


def generate_logcheck_message(goal: dict) -> str:
    """Generate a log-check message for a goal (no LLM needed)."""
    agent_name = goal.get("agent_name", "Goal")
    goal_name = goal.get("name", "")
    personality = goal.get("personality", "warm")

    if personality == "strict":
        return f"*{agent_name}*\n\nDid you do it? Log your progress on _{goal_name}_. No excuses."
    return f"*{agent_name}*\n\nHow did it go with _{goal_name}_ today? Log your progress so I can help."
