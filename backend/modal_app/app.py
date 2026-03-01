"""
LifeOS Modal App — Main entrypoint.

Everything runs on Modal: cron scheduling and parallel agent execution.
LLM inference is handled by Groq API (free tier, near-instant responses).

Each tick:
1. Loads all active goals from Supabase
2. For each goal, runs the appropriate agent template in parallel
3. Runs pattern detection per user — sends Telegram only if threshold crossed
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import modal

app = modal.App("lifeos-agents")

# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

agent_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "supabase",
        "supermemory",
        "python-dotenv",
        "fastapi[standard]",
        "groq",
        "exa-py",
        "requests",
    )
    .add_local_dir(
        Path(__file__).resolve().parent.parent / "shared",
        remote_path="/root/shared",
    )
    .add_local_dir(
        Path(__file__).resolve().parent / "agents",
        remote_path="/root/modal_app/agents",
    )
    .add_local_file(
        Path(__file__).resolve().parent / "coordinator.py",
        remote_path="/root/modal_app/coordinator.py",
    )
    .add_local_file(
        Path(__file__).resolve().parent / "__init__.py",
        remote_path="/root/modal_app/__init__.py",
    )
)

secrets = [
    modal.Secret.from_name("lifeos-secrets"),
]

# ---------------------------------------------------------------------------
# LLM call — Groq API (free tier, near-instant, no GPU needed)
# ---------------------------------------------------------------------------

# Agents use 8b (500K tokens/day free) — fast and cheap
GROQ_AGENT_MODEL = "llama-3.1-8b-instant"
# Coordinator uses 70b (100K tokens/day) — only runs once per tick per user
GROQ_COORDINATOR_MODEL = "llama-3.3-70b-versatile"


def _llm_call(messages: list[dict], temperature: float = 0.3) -> str:
    """LLM call for agents — uses fast 8b model."""
    import os
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model=GROQ_AGENT_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=1024,
    )
    return response.choices[0].message.content


def _llm_call_coordinator(messages: list[dict], temperature: float = 0.3) -> str:
    """LLM call for coordinator — uses 70b model for better reasoning."""
    import os
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model=GROQ_COORDINATOR_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=1024,
    )
    return response.choices[0].message.content

# ---------------------------------------------------------------------------
# Agent registry + helpers
# ---------------------------------------------------------------------------

AGENT_REGISTRY = {
    "fitness": "modal_app.agents.fitness.FitnessAgent",
    "sleep": "modal_app.agents.sleep.SleepAgent",
    "money": "modal_app.agents.money.MoneyAgent",
    "social": "modal_app.agents.social.SocialAgent",
    "short_lived": "modal_app.agents.short_lived.ShortLivedAgent",
    "custom": "modal_app.agents.short_lived.ShortLivedAgent",
}


def _import_agent(dotted_path: str):
    module_path, class_name = dotted_path.rsplit(".", 1)
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)

# ---------------------------------------------------------------------------
# User data wipe
# ---------------------------------------------------------------------------

def _wipe_user_data(user_id: str) -> None:
    """Delete all Supabase + Supermemory data for a user."""
    import os
    import requests as http_requests
    from shared import supabase_client as _db

    client = _db.get_client()
    for table in ["agent_messages", "agent_states", "interventions", "user_logs", "goals"]:
        client.table(table).delete().eq("user_id", user_id).execute()

    api_key = os.environ.get("SUPERMEMORY_API_KEY", "")
    if api_key:
        tag = f"user:{user_id}"
        try:
            http_requests.delete(
                f"https://api.supermemory.ai/v3/container-tags/{tag}",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=15,
            )
        except Exception as e:
            print(f"[reset] Supermemory wipe failed for {user_id[:8]}: {e}")

    print(f"[reset] Wiped all data for user {user_id[:8]}")


# ---------------------------------------------------------------------------
# Modal functions
# ---------------------------------------------------------------------------

@app.function(image=agent_image, secrets=secrets, timeout=120)
def run_agent_for_goal(goal: dict) -> dict:
    """Run the appropriate agent template for a single goal."""
    sys.path.insert(0, "/root")

    goal_id = goal["id"]
    user_id = goal["user_id"]
    template = goal["agent_template"]
    config = goal.get("config", {})

    try:
        agent_cls = _import_agent(AGENT_REGISTRY.get(template, AGENT_REGISTRY["custom"]))
        agent = agent_cls(llm_fn=_llm_call)

        print(f"[{template}:{goal_id[:8]}] Starting analysis ...")
        result = agent.analyze(user_id, goal_id, config)
        print(f"[{template}:{goal_id[:8]}] Done — status={result.status}, action={result.next_action}")

        from shared import supabase_client as db
        db.upsert_agent_state(user_id, goal_id, result.to_state())

        if result.message_to_user:
            db.create_agent_message(
                user_id=user_id,
                from_agent=f"{template}:{goal_id}",
                message=result.message_to_user,
                goal_id=goal_id,
            )

        return {
            "goal_id": goal_id,
            "status": result.status,
            "next_action": result.next_action,
        }
    except Exception as e:
        print(f"[{template}:{goal_id[:8]}] ERROR: {e}")
        traceback.print_exc()
        return {
            "goal_id": goal_id,
            "status": "error",
            "error": str(e),
        }


@app.function(image=agent_image, secrets=secrets, timeout=120)
def run_coordinator(
    user_id: str,
    mode: str = "pattern_check",
    source_goal_id: str | None = None,
    trigger_log: str | None = None,
) -> dict | None:
    """Run coordinator logic for a single user."""
    sys.path.insert(0, "/root")
    try:
        from modal_app.coordinator import coordinate_for_user
        return coordinate_for_user(
            user_id,
            llm_fn=_llm_call_coordinator,
            mode=mode,
            source_goal_id=source_goal_id,
            trigger_log=trigger_log,
        )
    except Exception as e:
        print(f"[coordinator:{user_id[:8]}] ERROR: {e}")
        traceback.print_exc()
        return {"decision": "error", "error": str(e)}


@app.function(
    image=agent_image,
    secrets=secrets,
    timeout=300,
    schedule=modal.Cron("*/30 * * * *"),
)
def tick():
    """Main cron tick: run all agents silently, then pattern-check per user."""
    sys.path.insert(0, "/root")
    from shared import supabase_client as db

    goals = db.get_active_goals()

    now = datetime.now(timezone.utc)
    active_goals = []
    for g in goals:
        if g.get("end_at"):
            end_at = datetime.fromisoformat(g["end_at"]).replace(tzinfo=timezone.utc)
            if end_at < now:
                db.deactivate_goal(g["id"])
                continue
        active_goals.append(g)

    if not active_goals:
        print("No active goals found. Skipping tick.")
        return

    # Run agents (silent — they update states/state_history, no Telegram)
    results = list(run_agent_for_goal.map(active_goals))
    print(f"Processed {len(results)} goals: {results}")

    # Pattern-check per user (fires Telegram only if threshold crossed)
    user_ids = list({g["user_id"] for g in active_goals})
    coord_results = list(run_coordinator.map(user_ids))
    print(f"Coordinator results: {coord_results}")


@app.function(image=agent_image, secrets=secrets, timeout=300)
@modal.fastapi_endpoint(method="POST", docs=True)
def trigger_tick():
    """HTTP endpoint to trigger a tick from the frontend."""
    sys.path.insert(0, "/root")
    from shared import supabase_client as db

    goals = db.get_active_goals()

    now = datetime.now(timezone.utc)
    active_goals = []
    for g in goals:
        if g.get("end_at"):
            end_at = datetime.fromisoformat(g["end_at"]).replace(tzinfo=timezone.utc)
            if end_at < now:
                db.deactivate_goal(g["id"])
                continue
        active_goals.append(g)

    if not active_goals:
        return {"status": "skipped", "message": "No active goals found"}

    results = list(run_agent_for_goal.map(active_goals))
    user_ids = list({g["user_id"] for g in active_goals})
    coord_results = list(run_coordinator.map(user_ids))

    return {
        "status": "ok",
        "goals_processed": len(results),
        "results": results,
        "coordinator": coord_results,
    }


@app.function(image=agent_image, secrets=secrets, timeout=300)
@modal.fastapi_endpoint(method="POST", docs=True)
def trigger_tick_for_user(body: dict):
    """HTTP endpoint to trigger a tick for a specific user (called after log save)."""
    sys.path.insert(0, "/root")
    from shared import supabase_client as db

    user_id = body.get("user_id")
    if not user_id:
        return {"status": "error", "message": "user_id required"}

    goals = db.get_active_goals(user_id=user_id)
    now = datetime.now(timezone.utc)
    active_goals = []
    for g in goals:
        if g.get("end_at"):
            end_at = datetime.fromisoformat(g["end_at"]).replace(tzinfo=timezone.utc)
            if end_at < now:
                db.deactivate_goal(g["id"])
                continue
        active_goals.append(g)

    if not active_goals:
        return {"status": "skipped", "message": "No active goals for user"}

    results = list(run_agent_for_goal.map(active_goals))
    coord_results = list(run_coordinator.map([user_id]))

    return {
        "status": "ok",
        "goals_processed": len(results),
        "results": results,
        "coordinator": coord_results,
    }


@app.function(image=agent_image, secrets=secrets, timeout=60)
@modal.fastapi_endpoint(method="POST", docs=True)
def telegram_webhook(body: dict):
    """Receive Telegram webhook updates.

    Commands → synchronous response (reads DB, calls LLM, sends Telegram).
    Text logs → classify, save, spawn background analysis.
    """
    sys.path.insert(0, "/root")
    import os
    from groq import Groq
    from shared import supabase_client as db
    from shared.telegram_client import (
        parse_webhook_update,
        send_message,
        send_message_with_buttons,
        answer_callback_query,
    )
    from modal_app.coordinator import (
        HELP_TEXT,
        handle_status_command,
        handle_confused_command,
        handle_plan_command,
        handle_addgoal_command,
        handle_deletegoal_list_command,
        handle_deletegoal_number_command,
    )

    update = parse_webhook_update(body)
    if not update:
        return {"status": "ignored"}

    chat_id = update["chat_id"]
    user_id, is_new = db.get_or_create_user_by_telegram_chat(chat_id)

    # --- Handle callback queries (inline button presses) ---
    if update["type"] == "callback":
        answer_callback_query(update["callback_query_id"])
        data = update["data"]

        # classify:confirm:<log_id>:<goal_id>
        if data.startswith("cls:c:"):
            parts = data.split(":", 3)
            if len(parts) == 4:
                log_id, goal_id = parts[2], parts[3]
                db.update_log_goal(log_id, goal_id)
                goal_info = next(
                    (g for g in db.get_active_goals(user_id=user_id) if g["id"] == goal_id),
                    None,
                )
                goal_name = goal_info["name"] if goal_info else "that goal"
                send_message(chat_id, f"⚡ *hackbitz*\n\nGot it — logged under _{goal_name}_.")
                _tick_for_user.spawn(user_id, "reactive_log", goal_id)
            return {"status": "ok", "callback": "confirm"}

        # classify:skip:<log_id>
        if data.startswith("cls:s:"):
            send_message(chat_id, "⚡ *hackbitz*\n\nSaved without linking to a goal.")
            return {"status": "ok", "callback": "skip"}

        # classify:new:<log_id>
        if data.startswith("cls:n:"):
            send_message(
                chat_id,
                "⚡ *hackbitz*\n\nSend me `/addgoal <description>` to create a new goal for this.",
            )
            return {"status": "ok", "callback": "new"}

        # reset:confirm / reset:cancel
        if data == "reset:confirm":
            _wipe_user_data(user_id)
            send_message(
                chat_id,
                "⚡ *hackbitz*\n\nDone — everything has been wiped. You're starting fresh.\n\n"
                "Use /addgoal to set up your first goal.",
            )
            return {"status": "ok", "callback": "reset_confirm"}

        if data == "reset:cancel":
            send_message(chat_id, "⚡ *hackbitz*\n\nCancelled. Your data is safe.")
            return {"status": "ok", "callback": "reset_cancel"}

        return {"status": "ignored", "reason": "unknown callback"}

    text = update.get("text", "")
    if not text:
        return {"status": "ignored"}
    if is_new:
        send_message(
            chat_id,
            "⚡ *hackbitz*\n\nHi, I'm hackbitz. Use /addgoal to add a goal, /help for commands.",
        )

    # --- Command routing ---
    if text == "/status":
        status_text = handle_status_command(user_id)
        send_message(chat_id, status_text)
        return {"status": "ok", "command": "/status"}

    if text == "/confused":
        response_text = handle_confused_command(user_id, _llm_call_coordinator)
        send_message(chat_id, response_text)
        return {"status": "ok", "command": "/confused"}

    if text == "/plan":
        response_text = handle_plan_command(user_id, _llm_call_coordinator)
        send_message(chat_id, response_text)
        return {"status": "ok", "command": "/plan"}

    if text == "/help":
        send_message(chat_id, HELP_TEXT)
        return {"status": "ok", "command": "/help"}

    if text == "/checkin":
        send_message(chat_id, "⚡ *hackbitz*\n\nOn it — checking in on everything right now. Give me a minute.")
        _tick_for_user.spawn(user_id, "checkin")
        return {"status": "ok", "command": "/checkin"}

    if text == "/deletegoal":
        response_text = handle_deletegoal_list_command(user_id)
        send_message(chat_id, response_text)
        return {"status": "ok", "command": "/deletegoal"}

    if text.startswith("/deletegoal "):
        arg = text[len("/deletegoal "):].strip()
        try:
            number = int(arg)
            response_text = handle_deletegoal_number_command(user_id, number)
        except ValueError:
            response_text = "⚡ *hackbitz*\n\nUse `/deletegoal` to see your goals, then `/deletegoal <number>` to remove one."
        send_message(chat_id, response_text)
        return {"status": "ok", "command": "/deletegoal"}

    if text.startswith("/addgoal"):
        description = text[len("/addgoal"):].strip()
        response_text = handle_addgoal_command(description, user_id, _llm_call_coordinator)
        send_message(chat_id, response_text)
        return {"status": "ok", "command": "/addgoal"}

    if text == "/reset":
        send_message_with_buttons(
            chat_id,
            "⚡ *hackbitz*\n\nThis will delete all your goals, logs, and history. Are you sure?",
            [[
                {"text": "Yes, wipe everything", "callback_data": "reset:confirm"},
                {"text": "Cancel", "callback_data": "reset:cancel"},
            ]],
        )
        return {"status": "ok", "command": "/reset"}

    if text.startswith("/"):
        return {"status": "ignored", "reason": "unknown command"}

    # --- Text log: classify → save → spawn reactive analysis ---
    classified_goal_id = None
    confidence = 0.0
    goals = db.get_active_goals(user_id=user_id)
    try:
        if goals:
            goal_list = "\n".join(
                f"- id: {g['id']} | name: \"{g['name']}\" | type: {g['agent_template']}"
                for g in goals
            )
            groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
            resp = groq_client.chat.completions.create(
                model=GROQ_AGENT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Match the user's journal entry to the most relevant active goal. "
                            "Return ONLY valid JSON: "
                            '{"goal_id": "<best matching goal id or null>", '
                            '"confidence": <0.0-1.0 how sure you are>, '
                            '"reason": "<one short phrase explaining the match>"}\n\n'
                            "Rules:\n"
                            "- Always pick the single best match if one exists, even if uncertain.\n"
                            "- confidence >= 0.7 means you're sure it fits.\n"
                            "- confidence < 0.7 means it's a guess — the user will be asked to confirm.\n"
                            "- If truly nothing fits at all, return goal_id: null with confidence: 0."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Active goals:\n{goal_list}\n\nUser message: \"{text}\"",
                    },
                ],
                temperature=0.1,
                max_tokens=128,
            )
            import json, re
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw)
            parsed = json.loads(raw)
            gid = parsed.get("goal_id")
            confidence = float(parsed.get("confidence", 0.0))
            if gid and any(g["id"] == gid for g in goals):
                classified_goal_id = gid
    except Exception as e:
        print(f"[telegram_webhook] Classification error: {e}")

    # High confidence or no goals → save and proceed
    if confidence >= 0.7 or not goals:
        log = db.create_log(
            user_id=user_id,
            content=text,
            goal_id=classified_goal_id,
            source="manual_input",
        )
        print(f"[telegram_webhook] Saved log (confident), goal_id={classified_goal_id}")
        _tick_for_user.spawn(user_id, "reactive_log", classified_goal_id, text)
        return {"status": "ok", "goal_id": classified_goal_id}

    # Low confidence → save without goal, ask user to confirm
    log = db.create_log(
        user_id=user_id,
        content=text,
        goal_id=None,
        source="manual_input",
    )
    log_id = log["id"]

    if classified_goal_id:
        goal_info = next((g for g in goals if g["id"] == classified_goal_id), None)
        goal_name = goal_info["name"] if goal_info else "Unknown"
        goal_emoji = {"sleep": "🌙", "fitness": "🏃", "money": "💰", "social": "🤝",
                      "short_lived": "📚", "custom": "📚"}.get(
            goal_info.get("agent_template", ""), "📌") if goal_info else "📌"
        buttons = [
            [{"text": f"Yes, log under {goal_emoji} {goal_name}", "callback_data": f"cls:c:{log_id}:{classified_goal_id}"}],
            [
                {"text": "Create new goal", "callback_data": f"cls:n:{log_id}"},
                {"text": "Just save it", "callback_data": f"cls:s:{log_id}"},
            ],
        ]
        send_message_with_buttons(
            chat_id,
            f"⚡ *hackbitz*\n\nThis sounds like it could be part of _{goal_name}_. Should I log it there?",
            buttons,
        )
    else:
        buttons = [
            [{"text": "Create new goal", "callback_data": f"cls:n:{log_id}"}],
            [{"text": "Just save it", "callback_data": f"cls:s:{log_id}"}],
        ]
        send_message_with_buttons(
            chat_id,
            "⚡ *hackbitz*\n\nI'm not sure which goal this belongs to. Want to create a new goal for it, or just save it as a general note?",
            buttons,
        )
    return {"status": "ok", "goal_id": None, "pending_confirmation": True}


@app.function(image=agent_image, secrets=secrets, timeout=300)
def _tick_for_user(
    user_id: str,
    mode: str = "pattern_check",
    source_goal_id: str | None = None,
    trigger_log: str | None = None,
) -> None:
    """Internal: run agents + coordinator for one user. Called via spawn (fire and forget)."""
    sys.path.insert(0, "/root")
    from shared import supabase_client as db
    from modal_app.coordinator import coordinate_for_user

    goals = db.get_active_goals(user_id=user_id)
    now = datetime.now(timezone.utc)
    active_goals = []
    for g in goals:
        if g.get("end_at"):
            end_at = datetime.fromisoformat(g["end_at"]).replace(tzinfo=timezone.utc)
            if end_at < now:
                db.deactivate_goal(g["id"])
                continue
        active_goals.append(g)

    if not active_goals:
        print(f"[_tick_for_user] No active goals for {user_id[:8]}")
        return

    if mode == "reactive_log":
        # For the matched goal, ensure an agent_state exists before the coordinator
        # reads it. New goals won't have one yet (agents haven't run).
        if source_goal_id:
            matched = [g for g in active_goals if g["id"] == source_goal_id]
            if matched:
                from shared import supabase_client as check_db
                existing = check_db.get_agent_states_for_user(user_id)
                has_state = any(s["goal_id"] == source_goal_id for s in existing)
                if not has_state:
                    run_agent_for_goal.remote(matched[0])

        # Coordinator responds using latest states, then remaining agents update.
        coordinate_for_user(
            user_id,
            llm_fn=_llm_call_coordinator,
            mode=mode,
            source_goal_id=source_goal_id,
            trigger_log=trigger_log,
        )
        list(run_agent_for_goal.map(active_goals))
    else:
        # For cron ticks, checkin, etc. — run agents first, then coordinate.
        list(run_agent_for_goal.map(active_goals))
        coordinate_for_user(
            user_id,
            llm_fn=_llm_call_coordinator,
            mode=mode,
            source_goal_id=source_goal_id,
            trigger_log=trigger_log,
        )


@app.local_entrypoint()
def main():
    """Manual trigger for testing: runs one tick immediately."""
    tick.remote()
    print("Tick completed.")
