from __future__ import annotations

import json
import os
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
        "voice": "I've noticed your sleep has been",
    },
    "fitness": {
        "label": "Fitness",
        "emoji": "🏃",
        "header": "🏃 *Fitness*",
        "voice": "I can see you haven't been keeping up with",
    },
    "money": {
        "label": "Budget",
        "emoji": "💰",
        "header": "💰 *Budget*",
        "voice": "I've been tracking your spending",
    },
    "social": {
        "label": "Social",
        "emoji": "🤝",
        "header": "🤝 *Social*",
        "voice": "I've noticed you've been pulling away",
    },
    "short_lived": {
        "label": "Focus",
        "emoji": "📚",
        "header": "📚 *Focus*",
        "voice": "I've been watching your deadline",
    },
    "custom": {
        "label": "Focus",
        "emoji": "📚",
        "header": "📚 *Focus*",
        "voice": "I've been watching your deadline",
    },
    "coordinator": {
        "label": "hackbitz",
        "emoji": "⚡",
        "header": "⚡ *hackbitz*",
        "voice": "I've looked at everything",
    },
}

# Priority order for tiebreaking when multiple agents are concerned
TEMPLATE_PRIORITY = ["sleep", "fitness", "money", "social", "short_lived", "custom"]

# next_action → human-readable status for /status
ACTION_TO_STATUS: dict[str, str] = {
    "monitor": "on track",
    "nudge": "needs attention",
    "call": "needs attention",
    "escalate": "concerned",
}

HELP_TEXT = (
    "⚡ *hackbitz*\n\n"
    "Here's what I can do:\n\n"
    "• Just tell me anything — how you slept, if you worked out, what you spent. I'll keep track.\n"
    "• `/status` — Quick health check across all your goals.\n"
    "• `/confused` — I'll name the ONE thing that matters most right now.\n"
    "• `/plan` — Today's top priorities given what's going on.\n"
    "• `/help` — This message.\n\n"
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
    return json.loads(text)


def _get_persona(template: str) -> dict:
    return AGENT_PERSONAS.get(template, AGENT_PERSONAS["coordinator"])


def _build_telegram_message(header: str, body: str, exa_result: dict | None = None) -> str:
    """Build formatted Telegram message with a labeled header and optional Exa content."""
    msg = f"{header}\n\n{body}"
    if exa_result:
        flavor_label = exa_result.get("flavor_label", "📖 *Read*")
        title = exa_result.get("title", "")
        url = exa_result.get("url", "")
        snippet = exa_result.get("snippet", "")
        msg += f"\n\n{flavor_label}\n[{title}]({url})"
        if snippet:
            msg += f'\n"{snippet[:200]}"'
    return msg


def _send_telegram(text: str) -> bool:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat_id:
        print("[coordinator] TELEGRAM_CHAT_ID not set — skipping send")
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
        "Write in first person ('I've looked at everything...'). "
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
        "You are hackbitz. Write in first person. "
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
    if source_goal_id:
        for s in agent_states:
            if s["goal_id"] == source_goal_id:
                matched_state = s
                break

    if not matched_state:
        return {"decision": "no_action", "reason": "no matching goal state"}

    state = matched_state.get("state", {})
    goal_info = matched_state.get("goals") or {}
    template = goal_info.get("agent_template", "unknown")
    goal_name = goal_info.get("name", template)
    next_action = state.get("next_action", "monitor")
    context_summary = state.get("context_summary", "")

    # Monitoring → silence is the feature
    if next_action == "monitor":
        return {"decision": "no_action", "reason": "agent monitoring — no message needed"}

    # Dedup: skip if this goal already had an intervention in the last 6h
    recent = db.get_recent_interventions(user_id, goal_id=source_goal_id, hours=6)
    if recent:
        return {"decision": "no_action", "reason": "dedup: recent intervention for this goal"}

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
        f"You are the {persona['label']} companion — {persona['voice']}. "
        "Write in first person ('I noticed...', 'I've been tracking...', 'I can see...'). "
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

    # Exa only for escalate (lighter flavors for reactive context)
    exa_result = None
    if next_action == "escalate":
        topics = exa_client.DOMAIN_TOPICS.get(template, ["wellness"])
        topic = random.choice(topics)
        last_flavor = (matched_state.get("state_history") or [{}])[-1].get("exa_flavor")
        exa_result = exa_client.search_content_varied(
            topic,
            flavor=random.choice(exa_client.LIGHT_FLAVORS),
            last_flavor=last_flavor,
        )

    telegram_text = _build_telegram_message(header, body, exa_result)
    intervention_id = _log_intervention(
        user_id,
        next_action,
        f"Reactive log: {context_summary[:100]}",
        [template],
        goal_id=source_goal_id,
    )
    sent = _send_telegram(telegram_text)
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
            f"You are the {persona['label']} companion. "
            "Write in first person. 1 warm sentence celebrating a win. "
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
        _send_telegram(_build_telegram_message(persona["header"], body))

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
            "Write in first person ('I've looked at everything...', 'I've been watching...'). "
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
        exa_result = exa_client.search_content_varied(
            random.choice(topics),
            flavor=random.choice(exa_client.ALL_FLAVORS),
        )
        telegram_text = _build_telegram_message("⚡ *hackbitz*", body, exa_result)
        intervention_id = _log_intervention(
            user_id,
            "pattern_multi",
            f"Multi-pattern: {[p['template'] for p in patterns]}",
            [p["template"] for p in patterns],
        )
        sent = _send_telegram(telegram_text)
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
            f"You are the {persona['label']} companion — {persona['voice']}. "
            "Write in first person. "
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
        flavors = exa_client.LIGHT_FLAVORS if severity == "nudge" else exa_client.ALL_FLAVORS
        exa_result = exa_client.search_content_varied(
            random.choice(topics),
            flavor=random.choice(flavors),
        )
        telegram_text = _build_telegram_message(persona["header"], body, exa_result)
        intervention_id = _log_intervention(
            user_id,
            severity,
            f"Pattern: {template} {severity}",
            [template],
        )
        sent = _send_telegram(telegram_text)
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
        f"You are the {persona['label']} companion. "
        "Write in first person. 1 warm sentence celebrating a win. "
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

    _send_telegram(_build_telegram_message(persona["header"], body))
    return {"decision": "win", "template": template}
