# LifeOS -- Spec and Current State

## 0. Stack

**Frontend:** Next.js 15, React 19, Tailwind v4, shadcn/ui. No auth -- single mock user for web app.

**Backend:** Python 3.12, uv for deps, Modal for scheduling + parallel execution, Supabase for DB, Supermemory for shared semantic memory. **Telegram:** Multi-user via `telegram_user_mapping` (chat_id -> user_id); each bot chat gets isolated goals, logs, and agent state; coordinator looks up chat_id per user when sending.

**LLM:**
- **Agents (backend):** Groq API -- `llama-3.1-8b-instant`, free tier (500K tokens/day). Fast, low cost.
- **Coordinator (backend):** Groq API -- `llama-3.3-70b-versatile`, free tier (100K tokens/day). Better reasoning for conflict resolution + message generation.
- **Goal classification + log routing (frontend + telegram webhook):** Groq API -- `llama-3.1-8b-instant`, called server-side.
- No GPU, no vLLM. Modal runs CPU-only functions; Groq handles all inference.

**Content suggestions:** Exa AI (`https://api.exa.ai/search`) -- coordinator fetches relevant content when an agent's state warrants it. 10 content flavors; topics are LLM-generated per goal (stored in `config.domain_topics`).

**Delivery:** Telegram Bot API -- coordinator sends messages to user; user replies go back as logs.

**Why Modal + Supermemory:**
- **Modal** = where and when agents run: cron schedules (30-min heartbeat + 5-min nudge tick), parallel `.map()` over goals, web endpoints, secrets management.
- **Supermemory** = what agents remember: semantic search across observations, cross-goal context, time/tag-scoped queries.

---

## 1. Concept

One agent per goal. All goals use a single `DynamicAgent` class -- no pre-built templates. When a user writes "I want to sleep 8 hours a night", the system:
1. Classifies it via LLM, extracting `agent_name`, `agent_template`, `config` (including `domain_topics`, optional `target_count`/`target_unit`), and detecting deadlines.
2. Creates a goal row in Supabase with `agent_name`, `personality`, `priority`, and `config`.
3. Asks the user (via Telegram inline buttons) whether they've tried this before (sets personality to warm/strict and priority to normal/high), then asks for nudge and log-check schedules.
4. An agent runs on every tick for that goal, building its system prompt dynamically from goal metadata.

The coordinator runs after all per-goal agents finish. It reads agent states, detects patterns, generates messages via LLM (with Exa content), deduplicates, and dispatches Telegram messages.

**From the user's perspective:** They talk to named agents (Leetcode, Sleep, CUDA, Thesis, etc.) via Telegram -- each name is LLM-generated during goal creation.

---

## 2. Operating Modes

### Mode 1: RESPONSIVE (user reaches out first)
The user logs something or sends a command. Bot responds to WHAT THEY SAID.

| Input | Response |
|---|---|
| Text log (e.g. "went for a 5K run") | Always replies. LLM classifies with confidence. If confident (>= 0.7): auto-routes. Agent responds: nudge/call/escalate = 1-2 sentence message + Exa links; monitor = brief ack ("Got it, you're on track"); dedup = short ack ("Logged under X"). If uncertain (< 0.7): asks user to confirm via inline buttons. |
| `/list` | All active goals with agent_name, goal name, status label, and priority tag. No LLM. |
| `/confused` | hackbitz names ONE thing to focus on today + why. 3-4 sentences max. |
| `/plan` | Today's top 3 priorities given current state. Ordered list. |
| `/checkin` | Full structured check-in. Acks immediately, runs agents in background (~60s), then sends hackbitz scorecard (going well / needs attention / streaks / top priority). |
| `/addgoal <description>` | LLM parses free text -> creates goal in DB -> multi-step flow: experience question (new/failed) -> nudge schedule -> logcheck schedule. Deadline goals skip experience question. |
| `/deletegoal` | Numbered list of active goals. |
| `/deletegoal <N>` | Deactivates goal by number. |
| `/reset` | Confirmation prompt -> wipes all data. |
| `/help` | What the bot can do. |

### Mode 2: PROACTIVE, PATTERN-TRIGGERED (bot reaches out first)
Pattern-based. Bot speaks when a threshold is crossed.

| Trigger | Who speaks | What they say |
|---|---|---|
| Same agent in "concerned" state for 3+ consecutive ticks | That agent (by agent_name) | 2-3 sentences. Tone matches personality. Exa links. |
| 2+ agents "concerned" simultaneously | hackbitz (coordinator) | Simplification: "Focus on X. Y and Z can wait." Priority-aware. Exa links. |
| Agent flips from "concerned" -> "monitoring" (win!) | That agent | 1 warm sentence celebrating the win. |
| Scheduled nudge time (per-goal cron) | That agent | Motivational reminder. Tone matches personality. |
| Scheduled log-check time (per-goal cron) | That agent | "How did it go? Log your progress." Strict or warm tone. |
| Nightly summary time (derived from bedtime or default 10pm) | hackbitz | Coordinated scorecard: 1 line per goal, critical goals first, tomorrow's focus. |
| Agent suggests goal adjustment (adaptive difficulty) | That agent | "Want to adjust the goal to X?" with confirm/skip buttons. |

### Mode 3: SILENT (default, most common)
- Everything monitoring -> no message.
- Dedup active (already messaged in last 6h) -> no message.
- Cron runs silently, agents update states -> no Telegram.

---

## 3. Agent Personas & Telegram Format

No emojis in any messages. Every message header uses bold agent name.

| Source | Telegram header | Notes |
|---|---|---|
| Coordinator / multi-agent / commands | `*hackbitz*` | Cross-goal coordination |
| Any goal agent | `*{agent_name}*` | LLM-generated name: "Sleep", "Leetcode", "CUDA", "Thesis", etc. |

**Message format:**
```
*Leetcode*

I've looked at your logs and you've been hitting about 5 problems a day -- solid consistency. Want to push for 7 tomorrow?

Here's something worth reading:
[How to approach hard problems](url)
"Breaking down complex problems into smaller steps..."
```

**Voice rules (enforced in all LLM system prompts):**
- Speak directly to them like a helpful friend.
- Always first person. Never "the user". Never "companion" or "agent".
- Respond to what they said -- start from their words, not from the analysis.
- Do not include any emojis.
- Tone adapts to `personality`: strict = blunt, no sugarcoating; warm = encouraging, celebrates small wins.

---

## 4. Architecture

```
User Input
  [Webapp]                          [Telegram Bot @hackbitz_bot]
  POST /api/logs (classify+save)    -> telegram_webhook (classify+save)
       |                                      |
       | fire-and-forget                      | .spawn()
       v                                      v
  trigger_tick_for_user            _tick_for_user(mode, goal_id, log)
       |                                      |
       +--------------------------------------+
                          |
                   [Supabase DB: user_logs]
                          |
            Modal Agent Network
            (cron every 30 min + reactive on log save)
            (nudge cron every 5 min)
            |
            |-- Load active goals from DB
            |-- For each goal, run DynamicAgent in parallel (.map):
            |   |-- reads goal metadata (agent_name, personality, priority)
            |   |-- builds system prompt dynamically from goal config
            |   |-- reads own goal logs (last 7 days, capped at 10)
            |   |-- reads peer agent_states with priority info
            |   |-- queries Supermemory for cross-goal context
            |   |-- calls Groq 8b LLM -> AgentResult (including optional goal_adjustment)
            |   |-- writes agent_states (+ state_history, max 7 entries)
            |   +-- saves observations to Supermemory
            |
            +-- Coordinator (runs after all agents settle)
                |
                Modes:
                |-- reactive_log: respond on behalf of matching agent
                |-- pattern_check: detect patterns + goal adjustments + wins
                |-- win: standalone win celebration
                |-- checkin: structured life snapshot
                |
            +-- Scheduled Nudge Tick (every 5 min)
                |-- For each goal: check nudge_schedule / logcheck_schedule via croniter
                |-- Send nudge or logcheck reminders
                +-- Nightly summary at user's bedtime (or 10pm default)
```

---

## 5. Data Model (Supabase)

### goals
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| name | text | e.g. "Daily Leetcode Practice" |
| type | text | `habit`, `target`, `short_lived` |
| agent_template | text | `fitness`, `sleep`, `money`, `social`, `custom`, `short_lived` |
| agent_name | text | LLM-generated display name: "Leetcode", "Sleep", "CUDA", "Thesis". Default: "Goal". |
| personality | text | `warm` or `strict`. Controls agent tone. Default: "warm". |
| priority | text | `normal`, `high`, or `critical`. Affects coordinator tiebreaks. Default: "normal". |
| config | jsonb | See config fields below |
| active | boolean | default true |
| end_at | timestamptz | nullable; for deadline goals |
| created_at | timestamptz | default now() |

**Config jsonb fields:**
- `domain_topics` (list[str]): LLM-generated search terms for Exa content (e.g. ["leetcode", "competitive programming"])
- `target_count` (number or null): measurable numeric target (e.g. 10 for "10 problems"). null for binary habits.
- `target_unit` (string or null): unit for target_count ("problems", "hours", "km"). null when target_count is null.
- `nudge_schedule` (string or null): cron expression for reminder nudges (e.g. "0 9 * * *")
- `logcheck_schedule` (string or null): cron expression for log-check reminders (e.g. "0 22 * * *")
- `frequency_per_week` (number or null): how often per week
- Plus any domain-specific fields (target_hours, weekly_budget, success_criteria, etc.)

### user_logs
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| goal_id | uuid (nullable) | FK to goals; auto-classified by LLM |
| content | text | free-text log entry |
| source | text | `manual_input`, `agent_checkin` |
| created_at | timestamptz | default now() |

### agent_states
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| goal_id | uuid | FK to goals (unique per user+goal) |
| state | jsonb | `{ last_checkin, pattern_detected, confidence, context_summary, next_action, next_action_time, goal_adjustment }` |
| state_history | jsonb | Array of last 7 `{ next_action, confidence, updated_at }` entries |
| updated_at | timestamptz | default now() |

### interventions
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| goal_id | uuid (nullable) | |
| triggered_by | text[] | agent names that triggered this |
| intervention_type | text | `nudge`, `call`, `escalate`, `pattern_multi`, `reactive_log`, `nightly_summary` |
| reason | text | |
| scheduled_for | timestamptz | |
| executed | boolean | default false |
| delivered_at | timestamptz | |
| outcome | text (nullable) | |
| created_at | timestamptz | default now() |

### agent_messages
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| goal_id | uuid (nullable) | |
| from_agent | text | `{agent_name}:{goal_id}` |
| to_agent | text (nullable) | null = broadcast |
| message | text | |
| context | jsonb (nullable) | |
| created_at | timestamptz | default now() |

### telegram_user_mapping
| Column | Type | Notes |
|--------|------|-------|
| telegram_chat_id | text (PK) | From Telegram `message.chat.id` |
| user_id | uuid | unique; used in goals, user_logs, agent_states, etc. |
| created_at | timestamptz | default now() |

---

## 6. Dynamic Agent Architecture

**File:** `backend/modal_app/agents/dynamic.py`

All goals use a single `DynamicAgent` class. No pre-built templates (fitness.py, sleep.py, etc. have been removed). The agent builds its system prompt at runtime from goal metadata:

1. **Identity:** "You are {agent_name}, an accountability partner tracking the goal: {goal_name}."
2. **Personality:** warm (encouraging, celebrates wins) or strict (blunt, calls out misses).
3. **Priority:** critical (deadline, highest urgency), high (user has failed before), normal (default).
4. **Deadline awareness:** days remaining if `end_at` is set.
5. **Quantifiable target:** If `target_count` is set, agent compares user output against target and can suggest adjustments. If null, tracks done/not-done consistency.
6. **Output format:** JSON with status, next_action, reasoning, confidence, message_to_user, and optional goal_adjustment.

### AgentResult fields
```python
status: str               # "monitoring" | "concerned" | "intervention_needed"
next_action: str          # "monitor" | "nudge" | "call" | "escalate"
reasoning: str
confidence: float         # 0.0-1.0
context_summary: str      # truncated to 500 chars
message_to_user: str|None # saved to agent_messages
goal_adjustment: dict|None # {"direction": "easier"|"harder", "suggestion": "...", "new_config": {...}} -- only for quantifiable goals
```

### get_peer_states() (BaseAgent method)
Reads all `agent_states` for the user (excluding own goal), formats with priority:
```
- Sleep (Sleep 7h/night): escalate, priority=normal (confidence 0.92). Context: ...
- Thesis (Finish thesis): monitor, priority=critical (confidence 0.4)
```
Agents self-regulate: a strict gym agent sees a critical thesis in escalate and eases off.

---

## 7. Coordinator Logic

**File:** `backend/modal_app/coordinator.py`

### Priority engine

Replaces hardcoded `TEMPLATE_PRIORITY`. All tiebreaks use goal priority + severity:

```python
PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2}
SEVERITY_ORDER = {"escalate": 0, "call": 1, "nudge": 2, "monitor": 3}
```

`_sort_by_priority()` sorts agent states by priority first, then severity. Critical deadline goals always win over normal habits.

### Key constants

```python
ACTION_TO_LABEL = {
    "monitor": "on track",
    "nudge": "watch this",
    "call": "needs attention",
    "escalate": "off track",
}
```

### coordinate_for_user(user_id, llm_fn, mode, source_goal_id, trigger_log)

| Mode | Trigger | Behavior |
|---|---|---|
| `reactive_log` | User sent a text log | Responds on behalf of matching agent. Brief ack if monitor. Exa on nudge/call/escalate. |
| `pattern_check` | Cron tick (default) | Detect 3+ tick patterns + wins + goal adjustments. Priority-aware tiebreaking. |
| `win` | Agent flipped from pattern to monitor | Standalone win celebration (bypasses dedup). |
| `checkin` | User sent `/checkin` | Structured life snapshot with scorecard. |

### Command handlers

| Function | Command | Notes |
|---|---|---|
| `handle_list_command(user_id)` | `/list` | Active goals with agent_name, status, priority. No LLM. |
| `handle_confused_command(user_id, llm_fn)` | `/confused` | hackbitz names ONE focus. LLM (70b). |
| `handle_plan_command(user_id, llm_fn)` | `/plan` | hackbitz top 3 priorities. LLM (70b). |
| `handle_addgoal_command(desc, user_id, llm_fn)` | `/addgoal <desc>` | Returns (goal, error_text). Caller handles multi-step flow. |
| `handle_deletegoal_list_command(user_id)` | `/deletegoal` | Numbered list. No LLM. |
| `handle_deletegoal_number_command(user_id, number)` | `/deletegoal <N>` | Deactivates goal by position. |
| `handle_nightly_summary(user_id, llm_fn)` | (scheduled) | Coordinated evening wrap-up. |
| `generate_nudge_message(goal, user_id, llm_fn)` | (scheduled) | Per-goal nudge. |
| `generate_logcheck_message(goal)` | (scheduled) | Per-goal log check (no LLM). |

### _parse_and_create_goal(description, user_id, llm_fn)
LLM (70b) extracts: `{ name, agent_name, agent_template, type, has_deadline, config, end_at }`.

Config includes `domain_topics`, `target_count`, `target_unit`, and domain-specific fields. If `has_deadline` is true, goal gets `personality=strict`, `priority=critical` automatically.

### Multi-step /addgoal flow (handled in app.py callbacks)

1. LLM creates goal with agent_name.
2. **Deadline goals:** skip to nudge schedule question.
3. **Non-deadline goals:** ask experience ("New to this" / "Tried before, need to get serious").
   - New -> personality=warm, priority=normal
   - Failed -> personality=strict, priority=high
4. Ask nudge schedule (9am / 7pm / Custom).
5. Ask logcheck schedule (10pm / 8pm / Custom).
6. Confirmation with agent_name and personality tone.

### Adaptive goal difficulty
- Only for goals with `target_count` in config.
- Agent returns `goal_adjustment` in its result when pattern suggests adjustment.
- Coordinator sends inline buttons: "Yes, adjust" / "Keep as is".
- On confirm: updates `goals.config` with `new_config`.

---

## 8. Exa AI Integration

**File:** `backend/shared/exa_client.py`

Uses REST API directly (`requests` library, no SDK).

### 10 Content Flavors (no emojis)

| Flavor | Query template | Intro sentence |
|---|---|---|
| `article` | `{topic} tips guide how to improve` | "Here's something worth reading:" |
| `science` | `surprising science research behind {topic}` | "Here's a fun fact that might reframe this:" |
| `video` | `{topic} youtube video tutorial` | "This video might be worth your time:" |
| `trending` | `{topic} trending news 2025` | "Here's what's trending around this:" |
| `person` | `{topic} experts creators to follow` | "Someone worth following on this:" |
| `podcast` | `best {topic} podcast episode` | "A podcast episode on exactly this:" |
| `app` | `best app for {topic} 2024` | "There's an app that might actually help:" |
| `community` | `{topic} community Reddit Discord forum` | "You're not alone -- there's a community for this:" |
| `job` | `{topic} career jobs opportunities` | "Something that caught my eye on the opportunity side:" |
| `news` | `latest {topic} research news 2025` | "What's new in this space:" |

`search_content_multi(topics, trigger_log, count)` accepts `topics: list[str]` from `goal.config.domain_topics`. Picks random flavors. Returns up to `count` results with deduped URLs. Fallback if no domain_topics: uses goal name.

No hardcoded `DOMAIN_TOPICS` or `TEMPLATE_FLAVOR_SETS` -- everything is dynamic per goal.

---

## 9. Telegram Integration

**File:** `backend/shared/telegram_client.py`

**Bot:** `@hackbitz_bot` (token in Modal secrets + `backend/.env`)

### Functions
- `send_message(chat_id, text)` -- Markdown formatting
- `send_message_with_buttons(chat_id, text, buttons)` -- inline keyboard
- `answer_callback_query(callback_query_id, text)` -- ack button press
- `parse_webhook_update(body)` -- extracts message or callback data

### Command routing (in telegram_webhook)

```
/list          -> handle_list_command (sync, no LLM)
/confused      -> handle_confused_command (sync, LLM 70b)
/plan          -> handle_plan_command (sync, LLM 70b)
/help          -> HELP_TEXT constant
/checkin       -> ack immediately + _tick_for_user.spawn(mode="checkin")
/deletegoal    -> handle_deletegoal_list_command (sync, no LLM)
/deletegoal N  -> handle_deletegoal_number_command (sync, no LLM)
/addgoal <desc>-> handle_addgoal_command + multi-step inline buttons
/reset         -> confirmation inline buttons
text log       -> classify to goal_id -> save to user_logs -> spawn _tick_for_user
```

### Callback query routing

```
cls:c:<log_id>:<goal_id>           -> confirm log classification
cls:s:<log_id>                     -> skip classification
cls:n:<log_id>                     -> prompt for /addgoal
addgoal:exp:<goal_id>:<new|failed> -> set personality/priority
addgoal:nudge:<goal_id>:<time>     -> set nudge_schedule
addgoal:logcheck:<goal_id>:<time>  -> set logcheck_schedule
adjust:yes:<goal_id>               -> apply goal adjustment
adjust:no:<goal_id>                -> skip goal adjustment
reset:confirm                      -> wipe all data
reset:cancel                       -> cancel wipe
```

---

## 10. Modal Implementation

**Secrets:** `modal.Secret.from_name("lifeos-secrets")` -- stores:
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPERMEMORY_API_KEY`, `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `EXA_API_KEY`

**Image packages:** `supabase`, `supermemory`, `python-dotenv`, `fastapi[standard]`, `groq`, `exa-py`, `requests`, `croniter`

**Functions:**

| Function | Type | Timeout | Notes |
|---|---|---|---|
| `run_agent_for_goal(goal)` | Modal fn | 120s | Runs DynamicAgent, passes goal_meta |
| `run_coordinator(user_id, mode, ...)` | Modal fn | 120s | Uses 70b model |
| `tick()` | Cron (*/30) | 300s | Heartbeat: agents + pattern_check |
| `scheduled_nudge_tick()` | Cron (*/5) | 300s | Per-goal nudge/logcheck + nightly summary |
| `trigger_tick()` | POST endpoint | 300s | Manual trigger for all users |
| `trigger_tick_for_user(body)` | POST endpoint | 300s | Per-user reactive trigger |
| `telegram_webhook(body)` | POST endpoint | 60s | Commands, text logs, callbacks |
| `_tick_for_user(user_id, mode, ...)` | Modal fn | 300s | Internal: agents + coordinator |

### scheduled_nudge_tick() -- every 5 minutes
1. Loads all active goals, groups by user.
2. For each goal with `nudge_schedule` or `logcheck_schedule` in config:
   - Uses `croniter` to check if the cron should have fired in the last 5 minutes.
   - Nudge: sends personality-styled motivational message via LLM.
   - Log-check: checks if user logged today; if not, sends reminder.
3. Nightly summary: checks if it's the user's summary hour (from sleep goal's `target_bedtime` or default 22:00). If so, runs `handle_nightly_summary`.

---

## 11. Supermemory Usage

**SDK version:** 3.27.0.

**Store:**
```python
client.add(content=..., metadata={...}, container_tags=[user_id])
```

**Search:**
```python
resp = client.search.memories(
    q=query,
    container_tag=f"user:{user_id}",
    limit=limit,
    threshold=threshold,
)
```

**What gets stored:** agent observations (when status != monitoring), coordinator decisions. Cross-goal context is retrieved via semantic search before each agent LLM call.

---

## 12. Frontend -- LLM-Powered UX

### Goal creation
User types free-form: *"I want to sleep 8 hours a night"*

`POST /api/goals` calls Groq (`llama-3.1-8b-instant`) to classify. Goals can also be created via Telegram with `/addgoal <description>` -- multi-step flow with personality and schedule questions.

### Log auto-routing
`POST /api/logs` classifies to nearest active goal via Groq, saves with `goal_id`, then fires reactive tick.

### Companion chat (`agent-chat.tsx`)
- Messages labeled by agent_name
- Content suggestions render as clickable link cards

---

## 13. Current State (as of 2026-02-28)

### Working
- All Supabase tables live (goals with agent_name/personality/priority columns).
- Modal app deployed: 30-min heartbeat cron + 5-min nudge cron + reactive trigger + telegram webhook.
- Two-model Groq setup: 8b for agents (500K/day), 70b for coordinator (100K/day).
- **Fully dynamic agent architecture:** single DynamicAgent replaces all 5 template agents. System prompt built at runtime from goal metadata.
- **Per-goal personality:** warm (encouraging) or strict (no-nonsense). Set during multi-step /addgoal flow.
- **Dynamic priority engine:** critical > high > normal. Deadline goals auto-set to critical. Priority used in all coordinator tiebreaks.
- **LLM-generated agent names:** each goal gets a unique persona name (Leetcode, CUDA, Sleep, Thesis, etc.).
- Coordinator: 4 modes (reactive_log, pattern_check, win, checkin).
- Pattern detection: 3+ consecutive ticks in concerning state -> Telegram message.
- Win detection: agent flips from concerned -> monitoring -> celebration message.
- **Adaptive goal difficulty:** agents can suggest adjusting target_count up/down. Only for quantifiable goals. Inline buttons for confirm/skip.
- Exa: 10 content flavors (no emojis), dynamic topics from `config.domain_topics`. 2-3 links per message.
- `/list` command: goals with agent_name, status labels, priority tags.
- `/checkin` command: structured output (going well / needs attention / streaks / hackbitz says).
- **Multi-step /addgoal:** LLM creates goal -> experience question -> nudge schedule -> logcheck schedule. Deadline goals skip experience question.
- **Scheduled nudge/logcheck:** per-goal cron schedules checked every 5 minutes via croniter.
- **Nightly summary:** coordinated evening wrap-up from hackbitz, priority-aware, cross-agent coordination.
- **No emojis:** all bot messages are plain text with bold headers. No emojis anywhere.
- Coordinator dedup: one proactive Telegram message per user per 6h.
- Telegram webhook classifies messages with confidence; asks to confirm if < 0.7.
- Reactive tick: coordinator responds first (~3-5s), agents update in background.
- state_history: last 7 agent state snapshots per goal.
- Multi-user Telegram: telegram_user_mapping links each chat_id to a user_id.

### Pending
- Run `supabase/migrations/002_delivery.sql` manually to add `delivered_at` column.
- Run `supabase/migrations/003_state_history.sql` to add `state_history` column.
- Run `supabase/migrations/004_telegram_user_mapping.sql` for multi-user bot.
- Run `supabase/migrations/005_dynamic_agents.sql` to add `agent_name`, `personality`, `priority` columns.
- Web app: no auth -- single hardcoded mock user. Telegram: each chat gets its own user_id.

---

## 14. How to Run

```bash
# Frontend
cd lifeos/frontend
npm run dev
# -> http://localhost:3000

# Backend -- redeploy after changes
cd lifeos/backend
source .venv/bin/activate
modal deploy modal_app/app.py

# Seed demo data
cd lifeos/backend
python seed_demo.py --reset

# Reset user data (Supabase + Supermemory)
cd lifeos/backend
python reset_user.py                     # reset mock user
python reset_user.py --chat 123456789    # reset by Telegram chat_id
python reset_user.py --user <uuid>       # reset by user_id
python reset_user.py --all               # reset ALL users
python reset_user.py --skip-memory       # skip Supermemory wipe
# Users can also send /reset in Telegram to wipe their own data.

# Manual tick (CLI)
modal run modal_app/app.py

# Update Modal secrets (after adding new keys to .env)
modal secret create lifeos-secrets KEY=val ... --force
```

**Required env:**

`backend/.env`:
```
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
SUPERMEMORY_API_KEY=...
GROQ_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
EXA_API_KEY=...
```

`frontend/.env.local`:
```
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
MODAL_TRIGGER_URL=https://khalatevarun--lifeos-agents-trigger-tick.modal.run
MODAL_TRIGGER_URL_FOR_USER=https://khalatevarun--lifeos-agents-trigger-tick-for-user.modal.run
GROQ_API_KEY=...
```

Modal secret (`lifeos-secrets`): all keys above except `NEXT_PUBLIC_*`.

---

## 15. Repo Layout

```
lifeos/
+-- AGENTS.MD                          # This file
+-- backend/
|   +-- .env                           # Local env (gitignored)
|   +-- .venv/                         # Python venv
|   +-- seed_demo.py                   # Seeds demo data (--reset to wipe first)
|   +-- reset_user.py                  # Wipe user data; --user/--chat/--all
|   +-- modal_app/
|   |   +-- __init__.py
|   |   +-- app.py                     # Modal app: LLM fns, cron (30min + 5min), endpoints,
|   |   |                              # telegram_webhook with command + callback routing,
|   |   |                              # scheduled_nudge_tick, _tick_for_user
|   |   +-- coordinator.py             # Priority engine, coordinate_for_user (4 modes),
|   |   |                              # handle_list/confused/plan/addgoal/deletegoal commands,
|   |   |                              # handle_nightly_summary, generate_nudge/logcheck messages,
|   |   |                              # _parse_and_create_goal, _check_patterns, _build_telegram_message
|   |   +-- agents/
|   |       +-- __init__.py
|   |       +-- base.py                # BaseAgent: get_peer_states() with priority, AgentResult with goal_adjustment
|   |       +-- dynamic.py             # DynamicAgent: single agent class, builds prompt from goal metadata
|   +-- shared/
|       +-- __init__.py
|       +-- supabase_client.py         # goals (with agent_name/personality/priority), logs, states, interventions,
|       |                              # update_goal_meta, update_goal_config, telegram_user_mapping
|       +-- supermemory_client.py      # Supermemory helpers (SDK v3.27 compatible)
|       +-- exa_client.py             # Exa REST API: 10 flavors (no emojis), search_content_multi(topics)
|       +-- telegram_client.py         # send_message, send_message_with_buttons, answer_callback_query,
|                                      # parse_webhook_update
+-- supabase/
|   +-- migrations/
|       +-- 001_initial_schema.sql     # All 5 tables
|       +-- 002_delivery.sql           # ALTER TABLE interventions ADD delivered_at
|       +-- 003_state_history.sql      # ALTER TABLE agent_states ADD state_history
|       +-- 004_telegram_user_mapping.sql  # telegram_user_mapping table
|       +-- 005_dynamic_agents.sql     # ALTER TABLE goals ADD agent_name, personality, priority
+-- frontend/
    +-- .env.local
    +-- lib/
    |   +-- supabase.ts                # Supabase client + MOCK_USER_ID
    |   +-- groq.ts                    # Groq fetch wrapper + parseGroqJSON
    +-- app/
    |   +-- page.tsx                   # 3-column layout
    |   +-- api/
    |       +-- goals/route.ts         # POST: Groq classifies description
    |       +-- logs/route.ts          # POST: Groq routes log + fires reactive tick
    |       +-- agent-messages/route.ts
    |       +-- agent-states/route.ts
    |       +-- trigger-tick/route.ts  # POST: proxies to Modal trigger_tick
    +-- components/
        +-- agent-chat.tsx             # Agent messages + Exa link cards
        +-- agent-memory.tsx           # Supermemory context
        +-- activity-log.tsx
        +-- goal-form.tsx
        +-- ui/
```
