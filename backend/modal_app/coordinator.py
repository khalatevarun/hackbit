from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Callable

from shared import supabase_client as db
from shared import supermemory_client as mem


COORDINATOR_SYSTEM_PROMPT = """You are the Coordinator Agent for LifeOS. Multiple goal-specific agents are monitoring a user.
Your job is to:
1. Review all agent states and their requested actions
2. Identify conflicts (e.g., fitness agent wants to push hard, sleep agent says user needs rest)
3. Prioritize interventions (sleep/health > stress > fitness > money)
4. Decide which agent should lead the intervention and how
5. Craft a unified, coherent response

Return JSON with:
- decision: "no_action" | "approve_single" | "coordinate"
- lead_agent: the goal name that should lead (null if no_action)
- action: "nudge" | "call" | "text" | "escalate" (null if no_action)
- reasoning: why this decision was made
- instructions: dict mapping goal_name -> specific instruction for that agent
- unified_message: a single message to send to the user combining all relevant agents' insights (null if no_action)

You MUST respond with valid JSON only. No other text."""


def _extract_json(text: str) -> dict:
    """Parse JSON from LLM output, stripping markdown fences if present."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n?", text)
    if fence:
        text = text[fence.end():]
        text = re.sub(r"\n?```\s*$", "", text)
    return json.loads(text)


def coordinate_for_user(
    user_id: str,
    llm_fn: Callable[..., str] | None = None,
) -> dict | None:
    """Run coordinator logic for a single user. Returns decision dict or None."""
    agent_states = db.get_agent_states_for_user(user_id)
    if not agent_states:
        return None

    action_requests = []
    for s in agent_states:
        state = s.get("state", {})
        next_action = state.get("next_action", "monitor")
        if next_action in ("nudge", "call", "escalate"):
            goal_info = s.get("goals", {})
            action_requests.append({
                "goal_id": s["goal_id"],
                "goal_name": goal_info.get("name", "unknown"),
                "agent_template": goal_info.get("agent_template", "unknown"),
                "next_action": next_action,
                "reasoning": state.get("context_summary", ""),
                "confidence": state.get("confidence", 0.5),
                "pattern": state.get("pattern_detected"),
            })

    if not action_requests:
        return {"decision": "no_action"}

    if len(action_requests) == 1:
        req = action_requests[0]
        decision = {
            "decision": "approve_single",
            "lead_agent": req["goal_name"],
            "action": req["next_action"],
            "reasoning": f"Single agent ({req['agent_template']}) requesting {req['next_action']}: {req['reasoning']}",
            "instructions": {req["goal_name"]: f"Proceed with {req['next_action']}"},
        }
        _log_decision(user_id, decision, action_requests)
        return decision

    # Multiple agents want to act — use LLM to coordinate
    full_context = mem.search_memories(
        query=f"Complete situation for user. Multiple agents concerned: {[r['goal_name'] for r in action_requests]}",
        user_id=user_id,
        limit=15,
    )
    context_text = "\n".join(c["content"] for c in full_context if c.get("content"))

    states_summary = json.dumps(action_requests, indent=2, default=str)

    messages = [
        {"role": "system", "content": COORDINATOR_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""Agent states requesting intervention:
{states_summary}

Full user context from memory:
{context_text}

Who should intervene and how? Resolve any conflicts.""",
        },
    ]

    raw = llm_fn(messages, 0.3)
    decision = _extract_json(raw)
    _log_decision(user_id, decision, action_requests)
    return decision


def _log_decision(
    user_id: str,
    decision: dict,
    action_requests: list[dict],
) -> None:
    """Persist the coordinator's decision to DB and Supermemory."""
    db.create_agent_message(
        user_id=user_id,
        from_agent="coordinator",
        message=f"Decision: {decision.get('decision')}. Lead: {decision.get('lead_agent')}. "
                f"Action: {decision.get('action')}. Reasoning: {decision.get('reasoning')}",
        context=decision,
    )

    if decision.get("decision") != "no_action" and decision.get("action"):
        triggered_by = [r["goal_name"] for r in action_requests]
        db.create_intervention(
            user_id=user_id,
            intervention_type=decision["action"],
            reason=decision.get("reasoning", ""),
            scheduled_for=datetime.now(timezone.utc).isoformat(),
            triggered_by=triggered_by,
        )

    mem.add_memory(
        content=f"Coordinator decision: {decision.get('reasoning', '')}",
        user_id=user_id,
        metadata={
            "agent_template": "coordinator",
            "decision": decision.get("decision", ""),
            "lead_agent": decision.get("lead_agent", ""),
        },
    )
