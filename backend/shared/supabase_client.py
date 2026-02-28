from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = create_client(url, key)
    return _client


# --------------- goals ---------------

def create_goal(
    user_id: str,
    name: str,
    goal_type: str,
    agent_template: str,
    config: dict | None = None,
    end_at: str | None = None,
) -> dict:
    row = {
        "user_id": user_id,
        "name": name,
        "type": goal_type,
        "agent_template": agent_template,
        "config": config or {},
        "active": True,
    }
    if end_at:
        row["end_at"] = end_at
    return get_client().table("goals").insert(row).execute().data[0]


def get_active_goals(user_id: str | None = None) -> list[dict]:
    q = get_client().table("goals").select("*").eq("active", True)
    if user_id:
        q = q.eq("user_id", user_id)
    return q.execute().data


def deactivate_goal(goal_id: str) -> None:
    get_client().table("goals").update({"active": False}).eq("id", goal_id).execute()


# --------------- user_logs ---------------

def create_log(
    user_id: str,
    content: str,
    goal_id: str | None = None,
    source: str = "manual_input",
) -> dict:
    row: dict[str, Any] = {
        "user_id": user_id,
        "content": content,
        "source": source,
    }
    if goal_id:
        row["goal_id"] = goal_id
    return get_client().table("user_logs").insert(row).execute().data[0]


def get_recent_logs(
    user_id: str,
    goal_id: str | None = None,
    days: int = 7,
    limit: int = 50,
) -> list[dict]:
    q = (
        get_client()
        .table("user_logs")
        .select("*")
        .eq("user_id", user_id)
        .gte("created_at", _days_ago(days))
        .order("created_at", desc=True)
        .limit(limit)
    )
    if goal_id:
        q = q.eq("goal_id", goal_id)
    return q.execute().data


# --------------- agent_states ---------------

def upsert_agent_state(user_id: str, goal_id: str, state: dict) -> dict:
    row = {
        "user_id": user_id,
        "goal_id": goal_id,
        "state": state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return (
        get_client()
        .table("agent_states")
        .upsert(row, on_conflict="user_id,goal_id")
        .execute()
        .data[0]
    )


def get_agent_states_for_user(user_id: str) -> list[dict]:
    return (
        get_client()
        .table("agent_states")
        .select("*, goals(name, agent_template, config)")
        .eq("user_id", user_id)
        .execute()
        .data
    )


# --------------- interventions ---------------

def create_intervention(
    user_id: str,
    intervention_type: str,
    reason: str,
    scheduled_for: str,
    triggered_by: list[str],
    goal_id: str | None = None,
) -> dict:
    row: dict[str, Any] = {
        "user_id": user_id,
        "intervention_type": intervention_type,
        "reason": reason,
        "scheduled_for": scheduled_for,
        "triggered_by": triggered_by,
    }
    if goal_id:
        row["goal_id"] = goal_id
    return get_client().table("interventions").insert(row).execute().data[0]


# --------------- agent_messages ---------------

def create_agent_message(
    user_id: str,
    from_agent: str,
    message: str,
    to_agent: str | None = None,
    goal_id: str | None = None,
    context: dict | None = None,
) -> dict:
    row: dict[str, Any] = {
        "user_id": user_id,
        "from_agent": from_agent,
        "message": message,
    }
    if to_agent:
        row["to_agent"] = to_agent
    if goal_id:
        row["goal_id"] = goal_id
    if context:
        row["context"] = context
    return get_client().table("agent_messages").insert(row).execute().data[0]


def get_agent_messages(
    user_id: str,
    limit: int = 50,
) -> list[dict]:
    return (
        get_client()
        .table("agent_messages")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )


# --------------- helpers ---------------

def _days_ago(days: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
