"""
Wipe all data for a specific user across Supabase and Supermemory.

Usage:
    # Reset the default mock user (web app user)
    python reset_user.py

    # Reset a specific user by UUID
    python reset_user.py --user 12345678-1234-1234-1234-123456789012

    # Reset the user linked to a specific Telegram chat
    python reset_user.py --chat 987654321

    # Reset ALL users (everything in every table)
    python reset_user.py --all

    # Skip Supermemory wipe (only clear Supabase)
    python reset_user.py --skip-memory
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from shared import supabase_client as db

MOCK_USER_ID = "00000000-0000-0000-0000-000000000001"


def resolve_user_id(args: argparse.Namespace) -> str | None:
    """Return the user_id to reset, or None for --all mode."""
    if args.all:
        return None

    if args.chat:
        row = (
            db.get_client()
            .table("telegram_user_mapping")
            .select("user_id")
            .eq("telegram_chat_id", args.chat)
            .execute()
            .data
        )
        if not row:
            print(f"No user found for Telegram chat_id={args.chat}")
            sys.exit(1)
        uid = row[0]["user_id"]
        print(f"Resolved chat_id={args.chat} → user_id={uid}")
        return uid

    return args.user or MOCK_USER_ID


def wipe_supabase(user_id: str | None) -> None:
    """Delete all Supabase rows for a user, or all rows if user_id is None."""
    client = db.get_client()
    tables = [
        "agent_messages",
        "agent_states",
        "interventions",
        "user_logs",
        "goals",
        "telegram_user_mapping",
    ]

    label = f"user {user_id[:8]}..." if user_id else "ALL users"
    print(f"\nWiping Supabase data for {label}:")

    for table in tables:
        q = client.table(table).delete()
        if user_id:
            col = "telegram_chat_id" if table == "telegram_user_mapping" else "user_id"
            if table == "telegram_user_mapping":
                q = q.eq("user_id", user_id)
            else:
                q = q.eq("user_id", user_id)
        else:
            q = q.neq("id", "00000000-0000-0000-0000-000000000000")
        result = q.execute()
        count = len(result.data) if result.data else 0
        print(f"  {table}: {count} rows deleted")


def wipe_supermemory(user_id: str | None) -> None:
    """Delete all Supermemory data for a user's container tag."""
    api_key = os.environ.get("SUPERMEMORY_API_KEY")
    if not api_key:
        print("\n  SUPERMEMORY_API_KEY not set — skipping Supermemory wipe")
        return

    if user_id is None:
        # For --all mode, we need to find all user_ids that have data
        client = db.get_client()
        rows = client.table("telegram_user_mapping").select("user_id").execute().data
        user_ids = list({r["user_id"] for r in rows})
        user_ids.append(MOCK_USER_ID)
        user_ids = list(set(user_ids))
        print(f"\nWiping Supermemory for {len(user_ids)} user(s):")
        for uid in user_ids:
            _delete_container(api_key, uid)
    else:
        print(f"\nWiping Supermemory for user {user_id[:8]}...:")
        _delete_container(api_key, user_id)


def _delete_container(api_key: str, user_id: str) -> None:
    """Delete a user's container tag from Supermemory."""
    tag = f"user:{user_id}"
    try:
        resp = requests.delete(
            f"https://api.supermemory.ai/v3/container-tags/{tag}",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            docs = data.get("deletedDocumentsCount", 0)
            mems = data.get("deletedMemoriesCount", 0)
            print(f"  container '{tag}': {docs} documents, {mems} memories deleted")
        elif resp.status_code == 404:
            print(f"  container '{tag}': not found (already clean)")
        else:
            print(f"  container '{tag}': HTTP {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        print(f"  container '{tag}': error — {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wipe all data for a LifeOS user.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--user", type=str, help="User UUID to reset (default: mock user)")
    group.add_argument("--chat", type=str, help="Telegram chat_id — resolves to user_id")
    group.add_argument("--all", action="store_true", help="Reset ALL users")
    parser.add_argument("--skip-memory", action="store_true", help="Skip Supermemory wipe")
    args = parser.parse_args()

    user_id = resolve_user_id(args)

    if user_id:
        print(f"Resetting user: {user_id}")
    else:
        print("Resetting ALL users")
        confirm = input("Are you sure? This deletes everything. [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    if not args.skip_memory:
        wipe_supermemory(user_id)

    wipe_supabase(user_id)

    print("\nDone. User data has been wiped.")
    if user_id:
        print(f"Next time this user messages the bot, they'll get the welcome message and start fresh.")


if __name__ == "__main__":
    main()
