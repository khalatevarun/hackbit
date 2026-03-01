"""
LifeOS Modal App -- Main entrypoint.

Everything runs on Modal: cron scheduling and parallel agent execution.
LLM inference is handled by Groq API (free tier, near-instant responses).
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
        "croniter",
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
# LLM call -- Groq API
# ---------------------------------------------------------------------------

GROQ_AGENT_MODEL = "llama-3.1-8b-instant"
GROQ_COORDINATOR_MODEL = "llama-3.3-70b-versatile"


def _extract_numeric_value(text: str) -> float | None:
    """Extract the first meaningful number from a log entry.

    "did 12 problems" → 12.0, "ran 5.5km" → 5.5, "slept well" → None
    Skips pure timestamps (e.g. '8pm', '7am') and date-like patterns.
    """
    import re
    # Skip time patterns like 8pm, 7am, 10:30
    cleaned = re.sub(r'\b\d{1,2}(?:am|pm)\b', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b\d{1,2}:\d{2}\b', '', cleaned)
    m = re.search(r'\b(\d+(?:\.\d+)?)\b', cleaned)
    if m:
        v = float(m.group(1))
        # Ignore single-digit years like "did it for 1 day" where 1 is trivial
        # but keep it — the agent can decide if it's meaningful
        return v
    return None


def _llm_call(messages: list[dict], temperature: float = 0.5) -> str:
    """LLM call for agents -- uses fast 8b model for JSON assessments."""
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
    """LLM call for coordinator -- uses 70b model for better reasoning."""
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
    """Run the DynamicAgent for a single goal."""
    sys.path.insert(0, "/root")

    goal_id = goal["id"]
    user_id = goal["user_id"]
    config = goal.get("config", {})

    goal_meta = {
        "agent_name": goal.get("agent_name", "Goal"),
        "personality": goal.get("personality", "warm"),
        "priority": goal.get("priority", "normal"),
        "name": goal.get("name", ""),
        "end_at": goal.get("end_at"),
    }

    try:
        from modal_app.agents.dynamic import DynamicAgent
        agent = DynamicAgent(llm_fn=_llm_call)

        print(f"[{goal_meta['agent_name']}:{goal_id[:8]}] Starting analysis ...")
        result = agent.analyze(user_id, goal_id, config, goal_meta)
        print(f"[{goal_meta['agent_name']}:{goal_id[:8]}] Done -- status={result.status}, action={result.next_action}")

        from shared import supabase_client as db
        db.upsert_agent_state(user_id, goal_id, result.to_state())

        if result.message_to_user:
            db.create_agent_message(
                user_id=user_id,
                from_agent=f"{goal_meta['agent_name']}:{goal_id}",
                message=result.message_to_user,
                goal_id=goal_id,
            )

        return {
            "goal_id": goal_id,
            "status": result.status,
            "next_action": result.next_action,
        }
    except Exception as e:
        print(f"[{goal_meta['agent_name']}:{goal_id[:8]}] ERROR: {e}")
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

    results = list(run_agent_for_goal.map(active_goals))
    print(f"Processed {len(results)} goals: {results}")

    user_ids = list({g["user_id"] for g in active_goals})
    coord_results = list(run_coordinator.map(user_ids))
    print(f"Coordinator results: {coord_results}")


@app.function(
    image=agent_image,
    secrets=secrets,
    timeout=300,
    schedule=modal.Cron("*/5 * * * *"),
)
def scheduled_nudge_tick():
    """Every 5 minutes: detect skipped goals and send per-agent check-in messages."""
    sys.path.insert(0, "/root")
    from shared import supabase_client as db
    from shared import telegram_client as tg
    from shared.supabase_client import compute_goal_stats
    from modal_app.coordinator import generate_skip_message, handle_nightly_summary

    now = datetime.now(timezone.utc)
    goals = db.get_active_goals()
    if not goals:
        return

    # Group goals by user
    by_user: dict[str, list[dict]] = {}
    for g in goals:
        by_user.setdefault(g["user_id"], []).append(g)

    for user_id, user_goals in by_user.items():
        chat_id = db.get_telegram_chat_id(user_id)
        if not chat_id:
            continue

        # Skip detection only fires in the evening window (18:00–23:59 UTC)
        # This covers most timezones for an end-of-day check-in
        if 18 <= now.hour <= 23:
            for goal in user_goals:
                config = goal.get("config") or {}
                goal_type = goal.get("type", "habit")

                # Dedup: one skip message per goal per day
                recent = db.get_recent_interventions(user_id, goal_id=goal["id"], hours=20)
                if any(i.get("intervention_type") == "skip_nudge" for i in recent):
                    continue

                try:
                    stats = compute_goal_stats(user_id, goal["id"], config)
                    today_str = str(now.date())
                    last_logged = stats.get("last_logged_at")
                    last_logged_date = last_logged[:10] if last_logged else None
                    freq = config.get("frequency_per_week")

                    is_skip = False
                    if goal_type == "short_lived":
                        # Deadline goal: no log in 48h = skip
                        if last_logged:
                            from datetime import datetime as _dt
                            last_dt = _dt.fromisoformat(last_logged.replace("Z", "+00:00"))
                            if last_dt.tzinfo is None:
                                last_dt = last_dt.replace(tzinfo=timezone.utc)
                            is_skip = (now - last_dt).total_seconds() > 48 * 3600
                        else:
                            is_skip = True
                    elif freq:
                        # Frequency-based habit (e.g. gym 4x/week): behind on weekly count?
                        week_logged = stats.get("this_week_logged", 0)
                        days_remaining = 6 - now.weekday()  # days left in week after today
                        needed = int(freq) - week_logged
                        is_skip = needed > days_remaining + 1  # +1 buffer
                    else:
                        # Daily habit or count goal: no log today = skip
                        is_skip = last_logged_date != today_str

                    if not is_skip:
                        continue

                    msg = generate_skip_message(goal, stats, _llm_call_coordinator)
                    tg.send_message(chat_id, msg)
                    db.create_intervention(
                        user_id=user_id,
                        intervention_type="skip_nudge",
                        reason=f"No log detected for {goal['name']}",
                        scheduled_for=now.isoformat(),
                        triggered_by=[goal.get("agent_name", "Goal")],
                        goal_id=goal["id"],
                    )
                except Exception as e:
                    print(f"[nudge_tick] Skip check error for goal {goal['id'][:8]}: {e}")

        # Nightly summary check: derive time from sleep goal's target_bedtime or default 22:00
        summary_hour = 22
        for g in user_goals:
            cfg = g.get("config") or {}
            bedtime = cfg.get("target_bedtime")
            if bedtime:
                try:
                    summary_hour = int(bedtime.split(":")[0])
                except (ValueError, IndexError):
                    pass
                break

        if now.hour == summary_hour and now.minute < 5:
            recent = db.get_recent_interventions(user_id, hours=6)
            nightly_already = any(
                i.get("intervention_type") == "nightly_summary" for i in recent
            )
            if not nightly_already:
                try:
                    handle_nightly_summary(user_id, _llm_call_coordinator)
                except Exception as e:
                    print(f"[nudge_tick] Nightly summary error for user {user_id[:8]}: {e}")


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


VALID_DEMO_ACTIONS = {"nightly_summary", "proactive_nudges", "checkin"}


def _run_demo_action_for_user(user_id: str, action: str, db, tg):
    """Run one demo action for a single user. Returns (ok: bool, result: dict)."""
    from modal_app.coordinator import (
        handle_nightly_summary,
        generate_nudge_message,
        generate_logcheck_message,
    )

    chat_id = db.get_telegram_chat_id(user_id)
    if not chat_id:
        return False, {"reason": "no Telegram chat"}

    if action == "nightly_summary":
        result = handle_nightly_summary(user_id, _llm_call_coordinator)
        if result.get("decision") == "no_action":
            return False, {"reason": result.get("reason", "No action")}
        return True, {"message": "Nightly summary sent"}

    if action == "proactive_nudges":
        goals = db.get_active_goals(user_id=user_id)
        now = datetime.now(timezone.utc)
        active_goals = []
        for g in goals:
            if g.get("end_at"):
                end_at = datetime.fromisoformat(g["end_at"]).replace(tzinfo=timezone.utc)
                if end_at < now:
                    continue
            active_goals.append(g)
        nudge_count = 0
        logcheck_count = 0
        for goal in active_goals:
            config = goal.get("config") or {}
            if config.get("nudge_schedule"):
                try:
                    msg = generate_nudge_message(goal, user_id, _llm_call_coordinator)
                    if tg.send_message(chat_id, msg):
                        nudge_count += 1
                except Exception as e:
                    print(f"[trigger_demo] nudge error goal {goal['id'][:8]}: {e}")
            if config.get("logcheck_schedule"):
                try:
                    today_logs = db.get_recent_logs(user_id, goal_id=goal["id"], days=1)
                    if not today_logs:
                        msg = generate_logcheck_message(goal)
                        if tg.send_message(chat_id, msg):
                            logcheck_count += 1
                except Exception as e:
                    print(f"[trigger_demo] logcheck error goal {goal['id'][:8]}: {e}")
        return True, {"nudge_count": nudge_count, "logcheck_count": logcheck_count}

    if action == "checkin":
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
            return False, {"reason": "No active goals"}
        list(run_agent_for_goal.map(active_goals))
        run_coordinator.remote(user_id, "checkin")
        return True, {"message": "Check-in sent"}

    return False, {"reason": "Unknown action"}


@app.function(image=agent_image, secrets=secrets, timeout=300)
@modal.fastapi_endpoint(method="POST", docs=True)
def trigger_demo_action(body: dict):
    """Demo: trigger nightly summary, proactive nudges, or check-in. Send to one user or all (send_to_all=True)."""
    sys.path.insert(0, "/root")
    from shared import supabase_client as db
    from shared import telegram_client as tg
    from modal_app.coordinator import (
        handle_nightly_summary,
        generate_nudge_message,
        generate_logcheck_message,
    )

    action = body.get("action")
    if not action or action not in VALID_DEMO_ACTIONS:
        return {
            "status": "error",
            "message": f"action must be one of: {', '.join(sorted(VALID_DEMO_ACTIONS))}",
        }

    send_to_all = body.get("send_to_all", False)
    if send_to_all:
        user_ids = db.get_all_telegram_user_ids()
        if not user_ids:
            return {"status": "ok", "users_processed": 0, "message": "No users with Telegram linked"}
        ok_count = 0
        total_nudge = 0
        total_logcheck = 0
        for uid in user_ids:
            try:
                ok, result = _run_demo_action_for_user(uid, action, db, tg)
                if ok:
                    ok_count += 1
                    total_nudge += result.get("nudge_count", 0)
                    total_logcheck += result.get("logcheck_count", 0)
            except Exception as e:
                print(f"[trigger_demo] error for user {uid[:8]}: {e}")
        return {
            "status": "ok",
            "users_processed": ok_count,
            "users_total": len(user_ids),
            "nudge_count": total_nudge,
            "logcheck_count": total_logcheck,
            "message": f"Sent to {ok_count}/{len(user_ids)} users",
        }

    user_id = body.get("user_id")
    if not user_id:
        return {"status": "error", "message": "user_id required (or set send_to_all: true)"}
    try:
        ok, result = _run_demo_action_for_user(user_id, action, db, tg)
    except Exception as e:
        return {"status": "error", "message": str(e)}
    if not ok:
        return {"status": "skipped", "message": result.get("reason", "No action")}
    return {"status": "ok", **result}


@app.function(image=agent_image, secrets=secrets, timeout=60)
@modal.fastapi_endpoint(method="POST", docs=True)
def telegram_webhook(body: dict):
    """Receive Telegram webhook updates."""
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
        handle_list_command,
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

        # classify:confirm:<short_log_id>:<short_goal_id>
        if data.startswith("cls:c:"):
            parts = data.split(":", 3)
            if len(parts) == 4:
                short_log, short_goal = parts[2], parts[3]
                # Resolve short UUIDs by prefix match
                recent_logs = db.get_recent_logs(user_id, days=1, limit=20)
                log_id = next((l["id"] for l in recent_logs if l["id"].startswith(short_log)), None)
                active_goals = db.get_active_goals(user_id=user_id)
                goal_id = next((g["id"] for g in active_goals if g["id"].startswith(short_goal)), None)
                if log_id and goal_id:
                    db.update_log_goal(log_id, goal_id)
                    goal_info = next((g for g in active_goals if g["id"] == goal_id), None)
                    goal_name = goal_info["name"] if goal_info else "that goal"
                    send_message(chat_id, f"⚡ *hackbitz*\n\nGot it — logged under _{goal_name}_. ✅")
                    _tick_for_user.spawn(user_id, "reactive_log", goal_id)
                else:
                    send_message(chat_id, "⚡ *hackbitz*\n\nGot it, noted. ✅")
            return {"status": "ok", "callback": "confirm"}

        # classify:skip:<log_id>
        if data.startswith("cls:s:"):
            send_message(chat_id, "⚡ *hackbitz*\n\nSaved without linking to a goal. 📌")
            return {"status": "ok", "callback": "skip"}

        # classify:new:<log_id>
        if data.startswith("cls:n:"):
            send_message(
                chat_id,
                "⚡ *hackbitz*\n\nSend me `/addgoal <description>` to create a new goal for this. 🌱",
            )
            return {"status": "ok", "callback": "new"}

        # reset:confirm / reset:cancel
        if data == "reset:confirm":
            _wipe_user_data(user_id)
            send_message(
                chat_id,
                "⚡ *hackbitz*\n\nDone — everything has been wiped. You're starting fresh. 🌱\n\n"
                "Use /addgoal to set up your first goal.",
            )
            return {"status": "ok", "callback": "reset_confirm"}

        if data == "reset:cancel":
            send_message(chat_id, "⚡ *hackbitz*\n\nCancelled. Your data is safe. ✅")
            return {"status": "ok", "callback": "reset_cancel"}

        # addgoal:exp:<goal_id>:<new|failed> -- experience questionnaire
        if data.startswith("addgoal:exp:"):
            parts = data.split(":")
            if len(parts) == 4:
                goal_id = parts[2]
                experience = parts[3]
                goals = db.get_active_goals(user_id=user_id)
                goal = next((g for g in goals if g["id"] == goal_id), None)
                agent_name = goal.get("agent_name", "Goal") if goal else "Goal"
                if experience == "failed":
                    db.update_goal_meta(goal_id, {"personality": "strict", "priority": "high"})
                    send_message(
                        chat_id,
                        f"⚡ *hackbitz*\n\nUnderstood — *{agent_name}* will be direct with you. No going easy. 💪\n\n"
                        "Just log updates anytime — I'll check in automatically if I notice a gap.",
                    )
                else:
                    db.update_goal_meta(goal_id, {"personality": "warm", "priority": "normal"})
                    send_message(
                        chat_id,
                        f"⚡ *hackbitz*\n\nGot it — *{agent_name}* has your back. 🌟\n\n"
                        "Just log updates anytime — I'll check in automatically if I notice a gap.",
                    )
            return {"status": "ok", "callback": "addgoal_exp"}

        # adjust:yes:<goal_id> / adjust:no:<goal_id>
        if data.startswith("adjust:yes:"):
            goal_id = data.split(":", 2)[2]
            agent_states = db.get_agent_states_for_user(user_id)
            matched = next((s for s in agent_states if s["goal_id"] == goal_id), None)
            if matched:
                state = matched.get("state", {})
                adjustment = state.get("goal_adjustment", {})
                new_config = adjustment.get("new_config")
                if new_config:
                    goals = db.get_active_goals(user_id=user_id)
                    goal = next((g for g in goals if g["id"] == goal_id), None)
                    if goal:
                        config = goal.get("config") or {}
                        config.update(new_config)
                        db.update_goal_config(goal_id, config)
                        agent_name = goal.get("agent_name", "Goal")
                        send_message(chat_id, f"*{agent_name}*\n\nDone — goal adjusted. Let's see how this goes. 📐✨")
                        return {"status": "ok", "callback": "adjust_yes"}
            send_message(chat_id, "⚡ *hackbitz*\n\nAdjusted. ✅")
            return {"status": "ok", "callback": "adjust_yes"}

        if data.startswith("adjust:no:"):
            send_message(chat_id, "⚡ *hackbitz*\n\nGot it — keeping the goal as is. 👍")
            return {"status": "ok", "callback": "adjust_no"}

        # personality:roasting | personality:playful | personality:gentle
        if data.startswith("personality:"):
            personality = data.split(":", 1)[1]
            if personality in ("roasting", "playful", "gentle"):
                db.update_user_personality(user_id, personality)
                labels = {"roasting": "Roasting 😤", "playful": "Playful 😄", "gentle": "Gentle 💙"}
                send_message(chat_id, f"⚡ *hackbitz*\n\nDone. I'll talk to you in {labels[personality]} mode from now on. ✨")
            return {"status": "ok", "callback": "personality"}

        return {"status": "ignored", "reason": "unknown callback"}

    text = update.get("text", "")
    if not text:
        return {"status": "ignored"}
    if is_new:
        send_message(
            chat_id,
            "⚡ *hackbitz*\n\nHi, I'm hackbitz. Use /addgoal to add a goal, /help for commands. 👋",
        )

    # --- Command routing ---
    if text == "/personality":
        current = db.get_user_personality(user_id)
        labels = {"roasting": "Roasting 😤", "playful": "Playful 😄", "gentle": "Gentle 💙"}
        send_message_with_buttons(
            chat_id,
            "⚡ *hackbitz*\n\nPick how I should talk to you:\n\n"
            "• **Roasting** — sarcastic tough love, no sugarcoating\n"
            "• **Playful** — fun, light, jokes and warmth\n"
            "• **Gentle** — warm, kind, no pressure\n\n"
            f"(Current: {labels.get(current, current)})",
            [
                [
                    {"text": "Roasting 😤", "callback_data": "personality:roasting"},
                    {"text": "Playful 😄", "callback_data": "personality:playful"},
                    {"text": "Gentle 💙", "callback_data": "personality:gentle"},
                ],
            ],
        )
        return {"status": "ok", "command": "/personality"}

    if text == "/list":
        response_text = handle_list_command(user_id)
        send_message(chat_id, response_text)
        return {"status": "ok", "command": "/list"}

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
        send_message(chat_id, "⚡ *hackbitz*\n\nOn it — checking in on everything right now. Give me a minute. ⏳")
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
            response_text = "⚡ *hackbitz*\n\nUse `/deletegoal` to see your goals, then `/deletegoal <number>` to remove one. 📋"
        send_message(chat_id, response_text)
        return {"status": "ok", "command": "/deletegoal"}

    if text.startswith("/addgoal"):
        description = text[len("/addgoal"):].strip()
        goal, error_text = handle_addgoal_command(description, user_id, _llm_call_coordinator)
        if error_text:
            send_message(chat_id, error_text)
            return {"status": "ok", "command": "/addgoal"}

        agent_name = goal.get("agent_name", "Goal")
        goal_name = goal.get("name", description[:50])
        goal_id = goal["id"]
        has_deadline = goal.get("priority") == "critical"

        confirm_msg = (
            f"⚡ *hackbitz*\n\nGot it — I've added \"{goal_name}\". 🌱\n"
            f"Everything related to this will be tracked by *{agent_name}*."
        )

        if has_deadline:
            # Deadline goals: confirm immediately, cron handles check-ins
            send_message(
                chat_id,
                confirm_msg + "\n\nI'll check in automatically if you go quiet. Deadline is on the clock. ⏳",
            )
        else:
            # Non-deadline goals: ask experience question first
            send_message_with_buttons(
                chat_id,
                confirm_msg + "\nHave you tried following this goal before?",
                [
                    [{"text": "New to this -- first time", "callback_data": f"addgoal:exp:{goal_id}:new"}],
                    [{"text": "Tried before, need to get serious", "callback_data": f"addgoal:exp:{goal_id}:failed"}],
                ],
            )
        return {"status": "ok", "command": "/addgoal"}

    if text == "/reset":
        send_message_with_buttons(
            chat_id,
            "⚡ *hackbitz*\n\nThis will delete all your goals, logs, and history. Are you sure? ⚠️",
            [[
                {"text": "Yes, wipe everything", "callback_data": "reset:confirm"},
                {"text": "Cancel", "callback_data": "reset:cancel"},
            ]],
        )
        return {"status": "ok", "command": "/reset"}

    if text.startswith("/"):
        return {"status": "ignored", "reason": "unknown command"}

    # --- Text log: multi-goal split -> save per-goal logs -> spawn reactive analysis ---
    import json, re
    goals = db.get_active_goals(user_id=user_id)
    splits = []  # list of {goal_id, segment, confidence}

    if goals:
        goal_list = "\n".join(
            f"- id: {g['id']} | name: \"{g['name']}\" | agent: {g.get('agent_name', 'Goal')}"
            for g in goals
        )
        try:
            groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
            resp = groq_client.chat.completions.create(
                model=GROQ_AGENT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Analyze the user's message and identify which parts relate to which active goals. "
                            "A single message may contain updates about multiple goals — extract each separately. "
                            "Return ONLY valid JSON: "
                            '{"splits": [{"goal_id": "<goal id>", "segment": "<the relevant part of the message>", "confidence": <0.0-1.0>}]}\n\n'
                            "Rules:\n"
                            "- Extract one split per goal that is genuinely referenced.\n"
                            "- segment is the specific portion of the message relevant to that goal.\n"
                            "- confidence >= 0.7 means you're sure this part is about that goal.\n"
                            "- If only one goal is mentioned, return one split.\n"
                            "- If nothing matches any goal, return splits: [].\n"
                            "- Never force a match. Only include goals clearly referenced."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Active goals:\n{goal_list}\n\nUser message: \"{text}\"",
                    },
                ],
                temperature=0.1,
                max_tokens=256,
            )
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw)
            parsed = json.loads(raw)
            goal_ids_set = {g["id"] for g in goals}
            for sp in parsed.get("splits", []):
                gid = sp.get("goal_id")
                if gid and gid in goal_ids_set:
                    splits.append({
                        "goal_id": gid,
                        "segment": sp.get("segment", text),
                        "confidence": float(sp.get("confidence", 0.0)),
                    })
        except Exception as e:
            print(f"[telegram_webhook] Multi-split classification error: {e}")

    high_conf = [s for s in splits if s["confidence"] >= 0.7]

    # --- Multi-goal path: 2+ confident matches ---
    if len(high_conf) >= 2:
        goal_map = {g["id"]: g for g in goals}
        agent_names = []
        trigger_logs_map = {}
        for sp in high_conf:
            gid = sp["goal_id"]
            segment = sp["segment"]
            extracted_value = _extract_numeric_value(segment)
            db.create_log(user_id=user_id, content=segment, goal_id=gid, source="manual_input", value=extracted_value)
            goal_info = goal_map.get(gid, {})
            agent_names.append(goal_info.get("agent_name", goal_info.get("name", "Goal")))
            trigger_logs_map[gid] = segment

        agents_str = ", ".join(agent_names)
        send_message(chat_id, f"⚡ *hackbitz*\n\nGot it — split across {len(high_conf)} goals: _{agents_str}_. Agents checking in... ⚡")
        source_goal_ids = [sp["goal_id"] for sp in high_conf]
        _tick_for_user.spawn(user_id, "multi_reactive_log", None, None, source_goal_ids, trigger_logs_map)
        return {"status": "ok", "goal_ids": source_goal_ids, "multi": True}

    # --- Single-goal path (existing behavior) ---
    classified_goal_id = None
    confidence = 0.0
    if high_conf:
        classified_goal_id = high_conf[0]["goal_id"]
        confidence = high_conf[0]["confidence"]
    elif splits:
        best = max(splits, key=lambda s: s["confidence"])
        classified_goal_id = best["goal_id"]
        confidence = best["confidence"]

    if confidence >= 0.7 or not goals:
        db.create_log(
            user_id=user_id,
            content=text,
            goal_id=classified_goal_id,
            source="manual_input",
            value=_extract_numeric_value(text),
        )
        print(f"[telegram_webhook] Saved log (confident), goal_id={classified_goal_id}")
        _tick_for_user.spawn(user_id, "reactive_log", classified_goal_id, text)
        return {"status": "ok", "goal_id": classified_goal_id}

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
        agent_name = goal_info.get("agent_name", "Goal") if goal_info else "Goal"
        # Shorten UUIDs to first 8 chars to stay within Telegram's 64-byte callback_data limit
        short_log = log_id[:8]
        short_goal = classified_goal_id[:8]
        buttons = [
            [{"text": f"Yes, log under {agent_name} -- {goal_name}", "callback_data": f"cls:c:{short_log}:{short_goal}"}],
            [
                {"text": "Create new goal", "callback_data": f"cls:n:{log_id}"},
                {"text": "Just save it", "callback_data": f"cls:s:{log_id}"},
            ],
        ]
        send_message_with_buttons(
            chat_id,
            f"⚡ *hackbitz*\n\nThis sounds like it could be part of _{goal_name}_. Should I log it there? 🤔",
            buttons,
        )
    else:
        buttons = [
            [{"text": "Create new goal", "callback_data": f"cls:n:{log_id}"}],
            [{"text": "Just save it", "callback_data": f"cls:s:{log_id}"}],
        ]
        send_message_with_buttons(
            chat_id,
            "⚡ *hackbitz*\n\nI'm not sure which goal this belongs to. Want to create a new goal for it, or just save it as a general note? 📝",
            buttons,
        )
    return {"status": "ok", "goal_id": None, "pending_confirmation": True}


@app.function(image=agent_image, secrets=secrets, timeout=300)
def _tick_for_user(
    user_id: str,
    mode: str = "pattern_check",
    source_goal_id: str | None = None,
    trigger_log: str | None = None,
    source_goal_ids: list[str] | None = None,
    trigger_logs_map: dict | None = None,
) -> None:
    """Internal: run agents + coordinator for one user. Called via spawn."""
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
        if source_goal_id:
            matched = [g for g in active_goals if g["id"] == source_goal_id]
            if matched:
                from shared import supabase_client as check_db
                existing = check_db.get_agent_states_for_user(user_id)
                has_state = any(s["goal_id"] == source_goal_id for s in existing)
                if not has_state:
                    run_agent_for_goal.remote(matched[0])

        coordinate_for_user(
            user_id,
            llm_fn=_llm_call_coordinator,
            mode=mode,
            source_goal_id=source_goal_id,
            trigger_log=trigger_log,
        )
        list(run_agent_for_goal.map(active_goals))
    elif mode == "multi_reactive_log" and source_goal_ids:
        # Bootstrap agent state for any goal that doesn't have one yet
        existing = db.get_agent_states_for_user(user_id)
        existing_gids = {s["goal_id"] for s in existing}
        to_bootstrap = [g for g in active_goals if g["id"] in source_goal_ids and g["id"] not in existing_gids]
        if to_bootstrap:
            list(run_agent_for_goal.map(to_bootstrap))
        # Each goal's agent responds independently with its own persona
        for gid in source_goal_ids:
            segment = (trigger_logs_map or {}).get(gid)
            coordinate_for_user(
                user_id,
                llm_fn=_llm_call_coordinator,
                mode="reactive_log",
                source_goal_id=gid,
                trigger_log=segment,
            )
        list(run_agent_for_goal.map(active_goals))
    else:
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
