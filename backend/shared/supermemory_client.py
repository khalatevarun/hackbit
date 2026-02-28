from __future__ import annotations

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from supermemory import Supermemory

load_dotenv()

_client: Supermemory | None = None


def get_client() -> Supermemory:
    global _client
    if _client is None:
        _client = Supermemory(api_key=os.environ["SUPERMEMORY_API_KEY"])
    return _client


def add_memory(
    content: str,
    user_id: str,
    metadata: dict | None = None,
    goal_id: str | None = None,
) -> str:
    """Store a memory in Supermemory, scoped to user (and optionally goal)."""
    tags = [f"user:{user_id}"]
    if goal_id:
        tags.append(f"goal:{goal_id}")

    meta = {
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(metadata or {}),
    }
    if goal_id:
        meta["goal_id"] = goal_id

    resp = get_client().add(
        content=content,
        container_tags=tags,
        metadata=meta,
    )
    return resp.id


def search_memories(
    query: str,
    user_id: str,
    goal_id: str | None = None,
    limit: int = 10,
    threshold: float = 0.5,
) -> list[dict]:
    """Semantic search across user's memories. Optionally scope to a goal."""
    container_tag = f"user:{user_id}"

    resp = get_client().search.memories(
        q=query,
        container_tag=container_tag,
        limit=limit,
        threshold=threshold,
    )

    results = []
    for item in resp.results:
        results.append({
            "id": item.id,
            "content": item.memory or item.chunk or "",
            "score": item.similarity,
            "metadata": item.metadata,
        })
    return results


def add_agent_observation(
    user_id: str,
    goal_id: str,
    agent_template: str,
    observation: str,
    observation_type: str = "pattern_detected",
    confidence: float = 0.5,
) -> str:
    """Store an agent's observation about a user's goal."""
    return add_memory(
        content=observation,
        user_id=user_id,
        goal_id=goal_id,
        metadata={
            "agent_template": agent_template,
            "observation_type": observation_type,
            "confidence": str(confidence),
        },
    )


def add_intervention_outcome(
    user_id: str,
    goal_id: str | None,
    agent: str,
    intervention_type: str,
    outcome: str,
    insights: list[str] | None = None,
) -> str:
    """Store the outcome of an intervention for future context."""
    return add_memory(
        content=outcome,
        user_id=user_id,
        goal_id=goal_id,
        metadata={
            "agent_template": agent,
            "intervention_type": intervention_type,
            "insights": ",".join(insights) if insights else "",
        },
    )
