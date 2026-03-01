"""
Demo seed script for LifeOS.

Story: "The ML Assignment That Ate My Life"
A CS junior is juggling five life goals — sleep, running, budget, staying social,
and finishing an ML assignment due Friday. The first week is solid. Then the
assignment drops and everything slowly falls apart in the most relatable way possible.

5 agents monitor 5 domains:
  1. Sleep 7h/night          (sleep agent)       — bedtime creeping later every night
  2. Run 4x/week             (fitness agent)     — training for a 5K in 3 weeks
  3. Budget $150/week        (money agent)       — watches food delivery + coffee
  4. Stay social 3x/week     (social agent)      — family calls, roommate hangouts
  5. Submit ML assignment    (short_lived agent) — due in 3 days, barely started

Usage:
    cd backend
    python seed_demo.py           # add goals + logs
    python seed_demo.py --reset   # wipe everything first, then seed
"""
from __future__ import annotations

import os
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

    print("Seeding 'The ML Assignment That Ate My Life' scenario...\n")

    # ------------------------------------------------------------------
    # 1. Goals
    # ------------------------------------------------------------------
    print("Creating goals...")

    sleep_goal = db.create_goal(
        user_id=MOCK_USER_ID,
        name="Sleep 7h/night",
        goal_type="habit",
        agent_template="sleep",
        config={"target_hours": 7, "target_bedtime": "23:30"},
    )

    fitness_goal = db.create_goal(
        user_id=MOCK_USER_ID,
        name="Run 4x/week (training for 5K)",
        goal_type="habit",
        agent_template="fitness",
        config={"frequency_per_week": 4, "target": "running"},
    )

    money_goal = db.create_goal(
        user_id=MOCK_USER_ID,
        name="Stay under $150/week",
        goal_type="habit",
        agent_template="money",
        config={"weekly_budget": 150, "watch_categories": ["food delivery", "coffee", "snacks"]},
    )

    social_goal = db.create_goal(
        user_id=MOCK_USER_ID,
        name="Stay connected — family + friends 3x/week",
        goal_type="habit",
        agent_template="social",
        config={"min_social_per_week": 3},
    )

    assignment_goal = db.create_goal(
        user_id=MOCK_USER_ID,
        name="Submit ML assignment (due Friday)",
        goal_type="short_lived",
        agent_template="short_lived",
        config={
            "end_date": (now + timedelta(days=3)).strftime("%Y-%m-%d"),
            "success_criteria": (
                "Implement a multi-class classifier on the CIFAR-10 dataset, "
                "write a 4-page report, and submit to Gradescope by Friday 11:59pm"
            ),
        },
        end_at=(now + timedelta(days=3)).isoformat(),
    )

    sid  = sleep_goal["id"]
    fid  = fitness_goal["id"]
    mid  = money_goal["id"]
    soid = social_goal["id"]
    aid  = assignment_goal["id"]

    print(f"  Sleep:       {sid}")
    print(f"  Fitness:     {fid}")
    print(f"  Money:       {mid}")
    print(f"  Social:      {soid}")
    print(f"  Assignment:  {aid}\n")

    # ------------------------------------------------------------------
    # 2. Logs — 10-day student arc
    #
    # Days 10-8: Solid week. Runs, decent sleep, under budget, social.
    # Days 7-5:  Assignment released. Things slip a little but manageable.
    # Days 4-3:  Assignment panic. Sleep drops, runs stop, food delivery spikes.
    # Days 2-1:  Full crunch. 4h sleep, zero exercise, way over budget, ghosting everyone.
    # ------------------------------------------------------------------

    def at(days_back: int, hour: int = 20, minute: int = 0) -> str:
        return (now - timedelta(days=days_back)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        ).isoformat()

    logs = [
        # ── Day 10: strong start ──────────────────────────────────────
        (at(10, 7),  sid,  "Woke up without an alarm at 7am. 7.5h. Starting the week right."),
        (at(10, 8),  fid,  "5K morning run. 28:14. Legs felt light, really happy with the pace."),
        (at(10, 13), mid,  "Made pasta at home. Rice + dal for dinner. Spent basically nothing today."),
        (at(10, 19), soid, "Called mom and dad for like 45 mins. Dad is learning to use Reels, absolute chaos."),
        (at(10, 21), aid,  "Did the week's lecture readings on SVMs and backprop. Feeling prepared."),

        # ── Day 9: still on track ─────────────────────────────────────
        (at(9, 7),   sid,  "7h exactly. Bed by 11:30, up at 6:30. Not bad."),
        (at(9, 17),  fid,  "Ran 4K with Rohan from the dorm. He's way faster than me but good push."),
        (at(9, 12),  mid,  "Grabbed coffee from the campus cafe: $3.50. Cooked everything else."),
        (at(9, 20),  soid, "Study group with Anika and Dev. Mostly actual studying with some venting about Prof Chen."),
        (at(9, 22),  aid,  "Reviewed last year's assignment solutions. The CIFAR dataset is huge, need to plan carefully."),

        # ── Day 8: rest + social day ──────────────────────────────────
        (at(8, 9),   sid,  "8h on a Saturday, deserved it. Felt amazing."),
        (at(8, 11),  fid,  "Rest day. Did a 20-min stretch. Shins a bit sore from yesterday."),
        (at(8, 13),  mid,  "Groceries: $42. Stocked up for the week. Good."),
        (at(8, 16),  soid, "Went to the farmers market with roommates Priya and Sam. Bought a mango. Life is okay."),
        (at(8, 20),  soid, "Movie night in the dorm common room. Three of us watched Interstellar for the fourth time."),

        # ── Day 7: assignment drops Monday morning ────────────────────
        (at(7, 8),   sid,  "7h. Woke up and immediately saw the assignment email. Due Friday. Okay. Okay."),
        (at(7, 10),  fid,  "Ran 3K but cut it short to get started on the assignment. Legs felt heavy anyway."),
        (at(7, 14),  mid,  "Coffee at the library: $4.75. Worth it, got a solid 3h block in."),
        (at(7, 19),  soid, "Quick lunch with Anika. Complained about the assignment. She has a stats exam. We're both cooked."),
        (at(7, 22),  aid,  "Set up the repo, downloaded CIFAR-10, got training loop running. ~15% done. This is doable."),

        # ── Day 6: optimistic but starting to slip ────────────────────
        (at(6, 7),   sid,  "6.5h. Stayed up till 1am debugging. Not a disaster but felt it this morning."),
        (at(6, 10),  fid,  "Skipped the run. Told myself I'd go in the evening. (I didn't go in the evening.)"),
        (at(6, 13),  mid,  "Ordered Chipotle because I didn't meal prep. $13.50. Whatever, one time."),
        (at(6, 16),  aid,  "Data augmentation is NOT working the way I expected. Spent 4h on one bug. 25% done."),
        (at(6, 21),  soid, "Replied to the group chat at least. Told them I'm buried in the assignment. They understand."),

        # ── Day 5: the grind is real ──────────────────────────────────
        (at(5, 7),   sid,  "5.5h. Went to bed at 2am, couldn't sleep, brain still running through model architectures."),
        (at(5, 12),  fid,  "No run. Honestly forgot it was a run day until right now writing this."),
        (at(5, 13),  mid,  "DoorDash $18. Also bought two Red Bulls from the vending machine ($5). This is how it starts."),
        (at(5, 15),  None, "The TA's office hours were useless. He basically just read the assignment PDF back at me."),
        (at(5, 19),  aid,  "Finally got 71% validation accuracy with ResNet-style architecture. 50% done. Report not started."),
        (at(5, 23),  sid,  "It's 11pm and I'm still at the library. Heading back now. This is fine."),

        # ── Day 4: sliding ────────────────────────────────────────────
        (at(4, 8),   sid,  "5h. Eyes hurt. Had a dream about gradient descent which is genuinely embarrassing."),
        (at(4, 9),   fid,  "Third skipped run in a row. I keep telling myself it's temporary. Starting to feel it though — stiff and sluggish."),
        (at(4, 12),  mid,  "DoorDash for lunch AND dinner: $32. Also four coffees at the library cafe: $18. Weekly total already at $120."),
        (at(4, 15),  soid, "Mom called. I let it go to voicemail. Feel terrible about it. Will call her tomorrow. (I probably won't.)"),
        (at(4, 20),  aid,  "Model at 79% accuracy. Trying to push past 80 for a better grade. Spent 5h on hyperparameter tweaks. 65% done."),
        (at(4, 23),  None, "Ate dinner at 11pm. Two granola bars and a Red Bull. This is my life now."),

        # ── Day 3: crisis mode ────────────────────────────────────────
        (at(3, 7),   sid,  "4h. Woke up at 5am with a specific anxiety about the softmax layer. Actually got up and fixed it."),
        (at(3, 9),   fid,  "Noticed I haven't moved properly in four days. Walked to class and back, that's it. Calves are weirdly tight."),
        (at(3, 11),  mid,  "Dunkin twice: $11. DoorDash again for dinner: $22. I don't even remember deciding to order. Just did it."),
        (at(3, 14),  soid, "Dev texted asking if I'm coming to lunch. Said I was stuck in lab. He brought me a sandwich. Good guy."),
        (at(3, 17),  aid,  "80.3% accuracy! But I still need to write the full 4-page report. Due in two days. Not okay. 70% done, 0% of report done."),
        (at(3, 22),  None, "Stress level: extremely elevated. Opened Twitter to 'take a break' and lost 40 minutes. Classic."),

        # ── Day 2: wall ───────────────────────────────────────────────
        (at(2, 7),   sid,  "3.5h. Went to bed at 3am, alarm at 6:30. Head is pounding. This is bad."),
        (at(2, 10),  fid,  "Zero exercise. Week 2 with basically no runs. I can feel my fitness slipping. The 5K is in 3 weeks and I'm falling apart."),
        (at(2, 12),  mid,  "Weekly budget: $148 already and it's only Wednesday. Red Bull 4-pack: $12. More DoorDash: $24."),
        (at(2, 14),  soid, "Priya knocked on my door to check on me. I was in my chair, unwashed, staring at a loss curve. She looked concerned."),
        (at(2, 16),  aid,  "Report: 1.5 pages done out of 4. Model is solid. But the writing is so slow when I'm this tired. 80% done. Due tomorrow."),
        (at(2, 21),  None, "I genuinely cannot tell if I'm being productive or just sitting at my desk looking at code. It all blurs together."),
        (at(2, 23),  sid,  "It's midnight. I need to write 2.5 more pages. I'm going to be up all night. This is my fault and I know it."),

        # ── Day 1: crunch day ─────────────────────────────────────────
        (at(1, 5),   sid,  "2h sleep. Pulled an all-nighter. Submitted the assignment at 4:47am with 74 minutes to spare."),
        (at(1, 7),   fid,  "Haven't run in 6 days. Body feels like a used paper bag. Walked to get breakfast and felt winded."),
        (at(1, 9),   mid,  "Total spend this week: $187. $37 over budget. That's what happens when every meal is DoorDash or vending machine."),
        (at(1, 11),  soid, "Called mom back finally. She immediately said I sounded awful. I started crying a little on the phone. She was nice about it."),
        (at(1, 12),  aid,  "Assignment submitted. Final accuracy: 80.3%. Report was rough but complete. Now I need to sleep for 12 hours."),
        (at(1, 14),  None, "Slept from noon to 6pm. Woke up feeling like a different person. I really need to not let it get that bad again."),
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

    # Optional: link one Telegram chat to the demo user so that chat sees seeded data
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if telegram_chat_id:
        client.table("telegram_user_mapping").upsert(
            {"telegram_chat_id": telegram_chat_id, "user_id": MOCK_USER_ID},
            on_conflict="telegram_chat_id",
        ).execute()
        print(f"Linked TELEGRAM_CHAT_ID to demo user {MOCK_USER_ID[:8]}... (that chat will see seeded goals)\n")

    print("=" * 65)
    print("DEMO SCENARIO: 'The ML Assignment That Ate My Life'")
    print("=" * 65)
    print()
    print("5 goals created:")
    print(f"  Sleep       → {sid[:8]}...")
    print(f"  Fitness     → {fid[:8]}...")
    print(f"  Money       → {mid[:8]}...")
    print(f"  Social      → {soid[:8]}...")
    print(f"  Assignment  → {aid[:8]}...  (due: {(now + timedelta(days=3)).strftime('%A %b %d')})")
    print()
    print(f"  {len(logs)} log entries across 10 days")
    print()
    print("WHAT TO EXPECT FROM AGENTS:")
    print()
    print("  Sleep:      Flags 6 consecutive nights under 6h. Asks")
    print("              fitness + social to ease off. Highest priority.")
    print()
    print("  Fitness:    Sees 6 skipped runs. But reads sleep state →")
    print("              backs off the push, suggests a walk instead.")
    print()
    print("  Money:      Spots the DoorDash spiral + Red Bull pattern.")
    print("              Connects it to stress from the assignment.")
    print()
    print("  Social:     Notices mom's missed call + isolation pattern.")
    print("              Flags that user replied to texts but avoids calls.")
    print()
    print("  Assignment: Due in 3 days, 80%+ done. Nudges on the report.")
    print("              Coordinates with sleep — won't push if sleep is critical.")
    print()
    print("  Coordinator: Sleep wins. One message, not five.")
    print("               Surfaces Exa links on healthy crunch habits.")
    print()
    print("DEMO SCRIPT:")
    print("  1. Show 5 active goals.")
    print("  2. Click 'Check in now' — companions respond.")
    print("  3. Show Exa link cards under sleep/fitness messages.")
    print("  4. Send a message to @hackbitz_bot: 'finally slept 7h last night'")
    print("  5. Watch the bot reply — agents update their assessment.")
    print("  6. Expand 'Why they said that' to show cross-agent awareness.")
    print("=" * 65)


if __name__ == "__main__":
    do_reset = "--reset" in sys.argv
    seed(do_reset=do_reset)
