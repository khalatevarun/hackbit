"""
Demo seed script for LifeOS hackathon.

Story: "The Burnout Spiral"
A developer is 7 days out from a hackathon deadline. Everything starts
fine. Then deadline pressure hits: sleep collapses first, then workouts
stop, then stress-spending spikes, then friends get ghosted.

5 agents monitor 5 domains. They ALL want to intervene at once.
The coordinator has to negotiate: sleep wins, everyone else backs off.

This creates visible, dramatic agent conflict — perfect for a demo.

Goals:
  1. Sleep 8h/night         (sleep agent)        — PRIMARY concern
  2. Gym 3x/week            (fitness agent)       — wants to push, sleep says no
  3. Spend < $300/week      (money agent)         — sees stress-spending spike
  4. Call friends 2x/week   (social agent)        — sees isolation pattern
  5. Submit hackathon       (short_lived agent)   — deadline pressure, root cause

Usage:
    cd backend
    python seed_demo.py           # add goals + logs
    python seed_demo.py --reset   # wipe existing data first, then seed
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from shared import supabase_client as db

MOCK_USER_ID = "00000000-0000-0000-0000-000000000001"


def reset(client):
    """Wipe all existing data for the demo user."""
    print("Resetting existing demo data...")
    client.table("agent_messages").delete().eq("user_id", MOCK_USER_ID).execute()
    client.table("agent_states").delete().eq("user_id", MOCK_USER_ID).execute()
    client.table("interventions").delete().eq("user_id", MOCK_USER_ID).execute()
    client.table("user_logs").delete().eq("user_id", MOCK_USER_ID).execute()
    client.table("goals").delete().eq("user_id", MOCK_USER_ID).execute()
    print("  Done.\n")


def seed(do_reset: bool = False):
    client = db.get_client()
    now = datetime.now(timezone.utc)

    if do_reset:
        reset(client)

    print("Seeding 'Burnout Spiral' demo scenario...\n")

    # ------------------------------------------------------------------
    # 1. Goals — five interconnected domains
    # ------------------------------------------------------------------
    print("Creating goals...")

    sleep_goal = db.create_goal(
        user_id=MOCK_USER_ID,
        name="Sleep 8h/night",
        goal_type="habit",
        agent_template="sleep",
        config={"target_hours": 8, "target_bedtime": "23:00"},
    )

    fitness_goal = db.create_goal(
        user_id=MOCK_USER_ID,
        name="Gym 3x/week",
        goal_type="habit",
        agent_template="fitness",
        config={"frequency_per_week": 3, "target": "strength training"},
    )

    money_goal = db.create_goal(
        user_id=MOCK_USER_ID,
        name="Keep weekly spend under $300",
        goal_type="habit",
        agent_template="money",
        config={"weekly_budget": 300, "watch_categories": ["food delivery", "impulse buys"]},
    )

    social_goal = db.create_goal(
        user_id=MOCK_USER_ID,
        name="Connect with friends 2x/week",
        goal_type="habit",
        agent_template="social",
        config={"min_social_per_week": 2},
    )

    hackathon_goal = db.create_goal(
        user_id=MOCK_USER_ID,
        name="Submit hackathon project",
        goal_type="short_lived",
        agent_template="short_lived",
        config={
            "end_date": (now + timedelta(days=2)).strftime("%Y-%m-%d"),
            "success_criteria": "Ship a working LifeOS demo with Supermemory + Modal integration",
        },
        end_at=(now + timedelta(days=2)).isoformat(),
    )

    sid  = sleep_goal["id"]
    fid  = fitness_goal["id"]
    mid  = money_goal["id"]
    soid = social_goal["id"]
    hid  = hackathon_goal["id"]

    print(f"  Sleep:      {sid}")
    print(f"  Fitness:    {fid}")
    print(f"  Money:      {mid}")
    print(f"  Social:     {soid}")
    print(f"  Hackathon:  {hid}\n")

    # ------------------------------------------------------------------
    # 2. Logs — 7-day burnout arc
    #
    # Day 7-6: Everything good. User is energised, social, on-budget.
    # Day 5:   Hackathon crunch begins. First sign of strain.
    # Day 4:   Sleep drops below 6h. Gym skipped. First food delivery.
    # Day 3:   4h sleep. Stress-spending. Cancelled on friends.
    # Day 2:   3h sleep. Body failing. Impulse buys. Ghosting everyone.
    # Day 1:   2.5h sleep. Complete collapse. Deadline in 2 days.
    # ------------------------------------------------------------------

    def at(days_back: int, hour: int = 20) -> str:
        return (now - timedelta(days=days_back)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        ).isoformat()

    logs = [
        # ── Day 7: baseline, everything green ────────────────────────
        (at(7, 7),  sid,  "Slept 8.5h. Bed by 10:30pm, woke up naturally. Feeling sharp."),
        (at(7, 18), fid,  "Crushed a 60-min strength session — bench, squat, deadlift. New PR on squat!"),
        (at(7, 19), mid,  "Cooked at home all week. Groceries: $58. Well under budget."),
        (at(7, 20), soid, "Dinner with Priya and Marcus. Laughed a lot. Needed that."),
        (at(7, 21), hid,  "Set up repo and architecture for hackathon project. Clean start. Excited."),

        # ── Day 6: still good ─────────────────────────────────────────
        (at(6, 7),  sid,  "8 hours. Bed by 11pm. Feeling rested."),
        (at(6, 12), fid,  "Rest day. Did a 20-min walk. Legs recovering well."),
        (at(6, 19), mid,  "Lunch out with a friend: $22. Nothing else."),
        (at(6, 20), soid, "Long phone call with Jake. Good to catch up."),
        (at(6, 21), hid,  "Frontend mostly done. 25% complete. Moving fast."),

        # ── Day 5: deadline pressure kicks in ─────────────────────────
        (at(5, 7),  sid,  "6.5h. Stayed up late reviewing API docs. Mind was busy."),
        (at(5, 17), fid,  "Skipped gym. Got absorbed in coding. Told myself I'd go tomorrow."),
        (at(5, 19), mid,  "Ordered DoorDash — too tired to cook. $34."),
        (at(5, 20), None, "Realised the hackathon deadline is tighter than I thought. Need to push."),
        (at(5, 21), hid,  "Backend API taking longer than expected. Supermemory integration is tricky. 40% done."),

        # ── Day 4: sliding fast ────────────────────────────────────────
        (at(4, 7),  sid,  "4.5h. Worked until 2am. Had coffee at 9pm — terrible idea. Feel foggy."),
        (at(4, 10), fid,  "Skipped gym again. Can't justify it with the deadline. Second miss this week."),
        (at(4, 13), mid,  "DoorDash twice today: $52. Also bought a mechanical keyboard I didn't need: $89."),
        (at(4, 18), soid, "Cancelled dinner with friends. Said I had to work. They were disappointed."),
        (at(4, 21), hid,  "Supermemory search is working! 60% done but burning out fast."),

        # ── Day 3: this is a crisis ────────────────────────────────────
        (at(3, 7),  sid,  "3.5h. Woke up at 4:30am with anxiety about the demo. Heart racing."),
        (at(3, 12), fid,  "No workout. Headache all day. Body feels like concrete."),
        (at(3, 14), mid,  "Coffee shop 3x: $24. DoorDash again: $47. Stress-bought noise cancelling headphones: $120."),
        (at(3, 17), soid, "Didn't reply to any messages today. Group chat asking if I'm okay. Ignored it."),
        (at(3, 21), hid,  "Got Modal deployment working. 75% done. Making stupid mistakes because I'm exhausted."),
        (at(3, 22), None, "Drank 5 coffees today. Hands are shaking. This is not sustainable."),

        # ── Day 2: hitting the wall ────────────────────────────────────
        (at(2, 7),  sid,  "3h. Kept jolting awake. Completely exhausted but can't stay asleep."),
        (at(2, 11), fid,  "Tried 10 pushups. Could barely do 5. Gave up. Body is completely depleted."),
        (at(2, 14), mid,  "Ordered food 3x: $78. Total spend this week already at $410 — way over $300 budget."),
        (at(2, 16), soid, "Friend texted asking if I'm okay. Said 'yes just busy' but I'm not okay."),
        (at(2, 20), hid,  "85% done. Deadline in 2 days. Making silly bugs. Need to sleep but can't stop."),
        (at(2, 22), None, "Feeling really anxious and low. Can't tell if the project is good or terrible anymore."),

        # ── Day 1: complete collapse ───────────────────────────────────
        (at(1, 7),  sid,  "2.5h sleep. Woke up at 5am, couldn't go back to sleep. Feel genuinely unwell."),
        (at(1, 10), fid,  "Zero workout capacity. Barely walked to the kitchen. This is day 4 of no gym."),
        (at(1, 12), mid,  "Red Bull x4: $16. More DoorDash: $55. I've stopped tracking — I know it's bad."),
        (at(1, 14), soid, "Cancelled video call with family. They sounded worried. I feel guilty."),
        (at(1, 16), hid,  "90% done. One big bug left. Deadline tomorrow. I need to push through tonight."),
        (at(1, 20), None, "Running on fumes. Head hurts. Eyes are dry. I know I need sleep but I'm scared to stop."),
    ]

    print(f"Inserting {len(logs)} log entries...")
    for logged_at, goal_id, content in logs:
        row = {
            "user_id": MOCK_USER_ID,
            "content": content,
            "source": "manual_input",
            "created_at": logged_at,
        }
        if goal_id:
            row["goal_id"] = goal_id
        client.table("user_logs").insert(row).execute()

    print("Done.\n")
    print("=" * 65)
    print("DEMO SCENARIO: 'The Burnout Spiral'")
    print("=" * 65)
    print()
    print("5 goals created:")
    print(f"  Sleep      → {sid[:8]}...")
    print(f"  Fitness    → {fid[:8]}...")
    print(f"  Money      → {mid[:8]}...")
    print(f"  Social     → {soid[:8]}...")
    print(f"  Hackathon  → {hid[:8]}...  (deadline: {(now + timedelta(days=2)).strftime('%b %d')})")
    print()
    print("DEMO SCRIPT:")
    print()
    print("  1. Show 5 active goals with their coloured badges.")
    print("  2. Click 'Run Agents' — watch the chat fill up.")
    print("  3. Point to Sleep agent: it flags 5 nights <4h and tells")
    print("     other agents to ease off.")
    print("  4. Point to Fitness agent: it saw the sleep context from")
    print("     Supermemory and softened its advice automatically.")
    print("  5. Point to Money agent: it connected stress → overspending.")
    print("  6. Point to Coordinator: it resolves the conflict —")
    print("     sleep > everything. Each agent gets specific instructions.")
    print("  7. Expand 'Agent Memory' — show Supermemory context that")
    print("     each agent retrieved (the cross-domain intelligence).")
    print("  8. Click 'Run Agents' again — second run shows agents")
    print("     adjusting based on memory from the first run.")
    print()
    print("KEY TALKING POINTS:")
    print("  • Modal: parallel agent execution on a cron, zero ops")
    print("  • Supermemory: agents share memory across domains —")
    print("    fitness agent knows about your sleep without being told")
    print("  • Coordinator pattern: LLM arbitrates conflicts between agents")
    print("=" * 65)


if __name__ == "__main__":
    do_reset = "--reset" in sys.argv
    seed(do_reset=do_reset)
