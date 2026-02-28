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
    from shared.telegram_client import parse_webhook_update, send_message
    from modal_app.coordinator import (
        HELP_TEXT,
        handle_status_command,
        handle_confused_command,
        handle_plan_command,
    )

    MOCK_USER_ID = "00000000-0000-0000-0000-000000000001"

    update = parse_webhook_update(body)
    if not update:
        return {"status": "ignored"}

    text = update["text"]
    chat_id = update["chat_id"]

    # --- Command routing ---
    if text == "/status":
        status_text = handle_status_command(MOCK_USER_ID)
        send_message(chat_id, status_text)
        return {"status": "ok", "command": "/status"}

    if text == "/confused":
        response_text = handle_confused_command(MOCK_USER_ID, _llm_call_coordinator)
        send_message(chat_id, response_text)
        return {"status": "ok", "command": "/confused"}

    if text == "/plan":
        response_text = handle_plan_command(MOCK_USER_ID, _llm_call_coordinator)
        send_message(chat_id, response_text)
        return {"status": "ok", "command": "/plan"}

    if text == "/help":
        send_message(chat_id, HELP_TEXT)
        return {"status": "ok", "command": "/help"}

    if text.startswith("/"):
        return {"status": "ignored", "reason": "unknown command"}

    # --- Text log: classify → save → spawn reactive analysis ---
    classified_goal_id = None
    try:
        goals = db.get_active_goals(user_id=MOCK_USER_ID)
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
                            "Return ONLY valid JSON: {\"goal_id\": \"<id or null>\"}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Active goals:\n{goal_list}\n\nUser message: \"{text}\"",
                    },
                ],
                temperature=0.1,
                max_tokens=64,
            )
            import json, re
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw)
            parsed = json.loads(raw)
            gid = parsed.get("goal_id")
            if gid and any(g["id"] == gid for g in goals):
                classified_goal_id = gid
    except Exception as e:
        print(f"[telegram_webhook] Classification error: {e}")

    db.create_log(
        user_id=MOCK_USER_ID,
        content=text,
        goal_id=classified_goal_id,
        source="manual_input",
    )
    print(f"[telegram_webhook] Saved log, goal_id={classified_goal_id}, spawning reactive tick")

    # Fire-and-forget: run agents then respond on behalf of the matching agent
    _tick_for_user.spawn(MOCK_USER_ID, "reactive_log", classified_goal_id, text)
    return {"status": "ok", "goal_id": classified_goal_id}


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

    # Run all agents (updates states + state_history)
    list(run_agent_for_goal.map(active_goals))

    # Coordinate based on mode
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
