"""
LifeOS Modal App — Main entrypoint.

Everything runs on Modal: cron scheduling and parallel agent execution.
LLM inference is handled by Groq API (free tier, near-instant responses).

Each tick:
1. Loads all active goals from Supabase
2. For each goal, runs the appropriate agent template in parallel
3. Runs the coordinator for each user with pending actions
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

GROQ_MODEL = "llama-3.3-70b-versatile"


def _llm_call(messages: list[dict], temperature: float = 0.3) -> str:
    """Call Groq API for LLM inference. Runs inside a Modal CPU function."""
    import os
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=2048,
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
def run_coordinator(user_id: str) -> dict | None:
    """Run coordinator logic for a single user."""
    sys.path.insert(0, "/root")
    try:
        from modal_app.coordinator import coordinate_for_user
        return coordinate_for_user(user_id, llm_fn=_llm_call)
    except Exception as e:
        print(f"[coordinator:{user_id[:8]}] ERROR: {e}")
        traceback.print_exc()
        return {"decision": "error", "error": str(e)}


@app.function(
    image=agent_image,
    secrets=secrets,
    timeout=300,
    schedule=modal.Cron("*/15 * * * *"),
)
def tick():
    """Main cron tick: run all agents then coordinator."""
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

    results = list(run_agent_for_goal.map(active_goals))
    print(f"Processed {len(results)} goals: {results}")

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


@app.local_entrypoint()
def main():
    """Manual trigger for testing: runs one tick immediately."""
    tick.remote()
    print("Tick completed.")
