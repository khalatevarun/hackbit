# LifeOS — Spec and Current State

## 0. Stack

**Frontend:** Next.js 15, React 19, Tailwind v4, shadcn/ui. No auth — single mock user for web app.

**Backend:** Python 3.12, uv for deps, Modal for scheduling + parallel execution, Supabase for DB, Supermemory for shared semantic memory. **Telegram:** Multi-user via `telegram_user_mapping` (chat_id → user_id); each bot chat gets isolated goals, logs, and agent state; coordinator looks up chat_id per user when sending.

**LLM:**
- **Agents (backend):** Groq API — `llama-3.1-8b-instant`, free tier (500K tokens/day). Fast, low cost.
- **Coordinator (backend):** Groq API — `llama-3.3-70b-versatile`, free tier (100K tokens/day). Better reasoning for conflict resolution + message generation.
- **Goal classification + log routing (frontend + telegram webhook):** Groq API — `llama-3.1-8b-instant`, called server-side.
- No GPU, no vLLM. Modal runs CPU-only functions; Groq handles all inference.

**Content suggestions:** Exa AI (`https://api.exa.ai/search`) — coordinator fetches relevant content when an agent's state warrants it. 10 content flavors; LLM picks the best one per situation.

**Delivery:** Telegram Bot API — coordinator sends messages to user; user replies go back as logs.

**Why Modal + Supermemory:**
- **Modal** = where and when agents run: cron schedules, parallel `.map()` over goals, web endpoints, secrets management.
- **Supermemory** = what agents remember: semantic search across observations, cross-goal context, time/tag-scoped queries.

---

## 1. Concept

One agent per goal. When a user writes "I want to sleep 8 hours a night", the system:
1. Classifies it via LLM into an agent template (sleep, fitness, money, social, short_lived, custom).
2. Creates a goal row in Supabase with the right config.
3. An agent runs on every tick for that goal, reads the user's logs, queries Supermemory for cross-goal context, reads peer agent states, and decides whether to `monitor` / `nudge` / `call` / `escalate`.

The coordinator runs after all per-goal agents finish. It reads agent states, detects patterns, generates messages via LLM (with Exa content), deduplicates, and dispatches Telegram messages.

**From the user's perspective:** They talk to named companions (Sleep, Fitness, Budget, Social, Focus) via Telegram — no agent/LLM language is exposed.

---

## 2. Three Operating Modes

### Mode 1: RESPONSIVE (user reaches out first)
The user logs something or sends a command. Bot responds to WHAT THEY SAID.

| Input | Response |
|---|---|
| Text log (e.g. "went for a 5K run") | **Always replies.** LLM classifies with confidence. If confident (>= 0.7): auto-routes. Agent responds: nudge/call/escalate = 1-2 sentence message + Exa links; monitor = brief ack ("Got it, you're on track"); dedup = short ack ("Logged under X"). If uncertain (< 0.7): asks user to confirm via inline buttons. If brand-new goal with no agent state: runs that single agent first, then responds. |
| `/status` | 5-line goal health check. One line per goal. Emoji + name + 4-tier status label. |
| `/confused` | hackbitz names ONE thing to focus on today + why. 3-4 sentences max. |
| `/plan` | Today's top 3 priorities given current state. Ordered list. |
| `/checkin` | Full fresh analysis. Acks immediately, runs agents in background (~60s), then sends hackbitz narrative. |
| `/addgoal <description>` | LLM parses free text → creates goal in DB → confirmation. |
| `/deletegoal` | Numbered list of active goals with emojis. |
| `/deletegoal <N>` | Deactivates goal by number. |
| `/reset` | Confirmation prompt → wipes all goals, logs, agent states, interventions, Supermemory. User starts fresh. |
| `/help` | What the bot can do. |

### Mode 2: PROACTIVE, PATTERN-TRIGGERED (bot reaches out first)
Not time-based. Pattern-based. Bot speaks when a threshold is crossed, not on a clock.

| Trigger | Who speaks | What they say |
|---|---|---|
| Same agent in "concerned" state for 3+ consecutive ticks | That agent only | 2-3 sentences. Direct but warm. Exa link (LLM-chosen flavor). |
| 2+ agents "concerned" simultaneously | hackbitz (coordinator) | Simplification: "Focus on X. Y and Z can wait." Exa link. |
| Agent flips from "concerned" → "monitoring" (win!) | That agent | 1 warm sentence celebrating the win. |

### Mode 3: SILENT (default, most common)
- Everything monitoring → no message.
- Dedup active (already messaged in last 6h) → no message.
- Cron runs silently, agents update states → no Telegram.

Silence is a feature. The bot staying quiet when things are fine is what makes it trusted when it does speak.

---

## 3. Agent Personas & Telegram Format

Every message in Telegram is headed by a bold label.

| Source | Telegram label | Emoji | Voice stance |
|---|---|---|---|
| Coordinator / multi-agent / commands | `⚡ *hackbitz*` | ⚡ | "I've looked at everything going on and" |
| Sleep agent | `🌙 *Sleep*` | 🌙 | "I've gone through your sleep updates and" |
| Fitness agent | `🏃 *Fitness*` | 🏃 | "I've looked at your fitness logs and" |
| Money agent | `💰 *Budget*` | 💰 | "I've been through your spending and" |
| Social agent | `🤝 *Social*` | 🤝 | "I've gone through your recent updates and" |
| Assignment / short-lived | `📚 *Focus*` | 📚 | "I've looked at where you are with your deadline and" |

**Message format:**
```
🌙 *Sleep*

I've gone through your sleep updates and three nights under 4 hours is something I want to help you fix. Let's get tonight right — even midnight works.

Here's a fun fact that might reframe this:
[Why 6 hours isn't enough — the science](url)
"Sleep debt compounds faster than most people realize..."
```

**Voice rules (enforced in all LLM system prompts):**
- Speak directly to them like a helpful friend. Use phrases like "I've gone through your updates", "Let me help you with this", "Here's what I think you should do", "I can see what's happening".
- Always first person. Never "the user". Never "companion" or "agent".
- Respond to what they said — start from their words, not from the analysis.

---

## 4. Architecture

```
User Input
  [Webapp]                          [Telegram Bot @hackbitz_bot]
  POST /api/logs (classify+save)    → telegram_webhook (classify+save)
       |                                      |
       | fire-and-forget                      | .spawn()
       ↓                                      ↓
  trigger_tick_for_user            _tick_for_user(mode, goal_id, log)
       |                                      |
       +──────────────────────────────────────+
                          |
                   [Supabase DB: user_logs]
                          |
            Modal Agent Network
            (cron every 30 min + reactive on log save)
            |
            |-- Load active goals from DB
            |-- For each goal, run agent template in parallel (.map):
            |   |-- reads own goal logs (last 7-14 days, capped at 10)
            |   |-- reads peer agent_states (get_peer_states())
            |   |-- queries Supermemory for cross-goal context (capped at 4 results)
            |   |-- calls Groq 8b LLM → { status, next_action, message_to_user }
            |   |-- writes agent_states (+ appends to state_history, max 7 entries)
            |   +-- saves observations to Supermemory
            |
            +-- Coordinator (runs after all agents settle)
                |
                Modes:
                |-- reactive_log: respond on behalf of matching agent to user's log
                |   |-- if monitor → silent
                |   |-- dedup: skip if intervention for this goal in last 6h
                |   |-- LLM (70b) generates 1-2 sentence agent-voice reply
                |   |-- if nudge/call/escalate → Exa (LLM picks flavor)
                |   +-- sends Telegram, logs intervention
                |
                |-- pattern_check: detect 3+ consecutive ticks in concerning state
                |   |-- check for wins (concerned→monitoring flip)
                |   |-- if 0 patterns + wins: send win messages, done
                |   |-- dedup: skip if any intervention in last 6h
                |   |-- if 2+ patterns: hackbitz simplification (70b) + Exa
                |   |-- if 1 pattern: single-agent message (70b) + Exa
                |   +-- sends Telegram, logs intervention
                |
                |-- win: standalone win celebration (bypasses dedup)
                |
                +-- checkin: full life snapshot (user-triggered via /checkin)
                    |-- reads fresh agent states (just run by _tick_for_user)
                    |-- hackbitz (70b): "what's good, what needs attention, one priority"
                    |-- Exa for top concern (LLM picks flavor)
                    +-- sends Telegram

[Telegram] ←──── coordinator sends message ──── [Supabase: interventions]
    |
    | user replies
    ↓
telegram_webhook → classify log (with confidence)
    |-- confident (>= 0.7): save with goal_id → spawn _tick_for_user
    |-- uncertain (< 0.7): save without goal_id → send inline buttons asking user to confirm
    |-- callback_query: user confirms → update log goal_id → spawn _tick_for_user
```

---

## 5. Data Model (Supabase)

### goals
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| name | text | e.g. "Gym 3x/week" |
| type | text | `habit`, `target`, `short_lived` |
| agent_template | text | `fitness`, `sleep`, `money`, `social`, `custom`, `short_lived` |
| config | jsonb | e.g. `{ "frequency_per_week": 3 }` |
| active | boolean | default true |
| end_at | timestamptz | nullable; for short-lived goals |
| created_at | timestamptz | default now() |

### user_logs
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| goal_id | uuid (nullable) | FK to goals; auto-classified by LLM (webapp + telegram webhook) |
| content | text | free-text log entry |
| source | text | `manual_input`, `agent_checkin` |
| created_at | timestamptz | default now() |

### agent_states
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| goal_id | uuid | FK to goals (unique per user+goal) |
| state | jsonb | `{ last_checkin, pattern_detected, confidence, context_summary, next_action, next_action_time }` |
| state_history | jsonb | Array of last 7 `{ next_action, confidence, updated_at }` entries. Added by migration 003. |
| updated_at | timestamptz | default now() |

### interventions
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| goal_id | uuid (nullable) | |
| triggered_by | text[] | agent/goal names that triggered this |
| intervention_type | text | `nudge`, `call`, `escalate`, `pattern_multi`, `reactive_log` |
| reason | text | |
| scheduled_for | timestamptz | |
| executed | boolean | default false — set true after Telegram delivery |
| delivered_at | timestamptz | set when Telegram send succeeds (requires migration 002) |
| outcome | text (nullable) | |
| created_at | timestamptz | default now() |

### agent_messages
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| goal_id | uuid (nullable) | |
| from_agent | text | `{template}:{goal_id}` |
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

One row per Telegram chat. Webhook calls `get_or_create_user_by_telegram_chat(chat_id)` to resolve or create user_id; coordinator calls `get_telegram_chat_id(user_id)` when sending so each user gets messages in their own chat.

---

## 6. Agent Templates

Each template receives `(user_id, goal_id, config)` and:
1. Loads recent `user_logs` from Supabase (scoped to goal_id, last 7-14 days, capped at 10 entries).
2. Queries Supermemory for cross-goal semantic context (capped at 4-8 results).
3. Calls `get_peer_states(user_id, exclude_goal_id)` — reads all other agents' current `agent_states`.
4. Calls Groq `llama-3.1-8b-instant` with the combined prompt → returns `AgentResult`.
5. Writes `agent_states` (with `state_history` append) to Supabase + saves observations to Supermemory.

**Note:** Agents no longer call Exa directly. Exa is called exclusively by the coordinator after reading agent states.

Templates:
- **Fitness** — skip detection, backs off if sleep agent is escalating.
- **Sleep** — duration/consistency tracking, highest priority in coordinator.
- **Money** — spending spike detection, stress-spending correlation.
- **Social** — isolation detection, emotional state monitoring.
- **Short-lived** — deadline-aware progress tracking, auto-deactivates after `end_at`.

### AgentResult fields
```python
status: str               # "monitoring" | "concerned" | "intervention_needed"
next_action: str          # "monitor" | "nudge" | "call" | "escalate"
reasoning: str
confidence: float         # 0.0–1.0
context_summary: str      # truncated to 500 chars; used by coordinator for Exa flavor selection
message_to_user: str|None # saved to agent_messages; not directly sent to Telegram
content_suggestions: list[dict]  # unused by coordinator (coordinator does its own Exa calls)
```

### get_peer_states() (BaseAgent method)
Reads all `agent_states` for the user (excluding own goal), formats as:
```
- Sleep companion (Sleep 8h): escalate (confidence 0.92) — "concerned". Context: ...
- Fitness companion (Gym 3x): monitor (confidence 0.4)
```
Injected into every agent's LLM prompt so agents self-regulate without a central coordinator pre-run.

---

## 7. Coordinator Logic

**File:** `backend/modal_app/coordinator.py`

### Key constants

```python
AGENT_PERSONAS   # label, emoji, header, voice starter per template
ACTION_TO_STATUS = {
    "monitor":  "✅ on track",
    "nudge":    "⚠️ watch this",
    "call":     "⚠️ needs attention",
    "escalate": "🔴 off track",
}
TEMPLATE_PRIORITY = ["sleep", "fitness", "money", "social", "short_lived", "custom"]
```

### coordinate_for_user(user_id, llm_fn, mode, source_goal_id, trigger_log)

| Mode | Trigger | Behavior |
|---|---|---|
| `reactive_log` | User sent a text log | Responds on behalf of matching agent. Silent if monitor. Exa on nudge/call/escalate. |
| `pattern_check` | Cron tick (default) | Detect 3+ tick patterns + wins. Dedup (6h global). hackbitz or single-agent message + Exa. |
| `win` | Agent flipped from pattern to monitor | Standalone win celebration (bypasses dedup). |
| `checkin` | User sent `/checkin` | Full life snapshot. hackbitz narrative + Exa for top concern. |

### Command handlers (synchronous, no spawn)

| Function | Command | Notes |
|---|---|---|
| `handle_status_command(user_id)` | `/status` | Reads last known agent states. Returns 4-tier labeled list. No LLM. |
| `handle_confused_command(user_id, llm_fn)` | `/confused` | hackbitz names ONE focus. LLM (70b). |
| `handle_plan_command(user_id, llm_fn)` | `/plan` | hackbitz top 3 priorities. LLM (70b). |
| `handle_addgoal_command(description, user_id, llm_fn)` | `/addgoal <desc>` | Calls `_parse_and_create_goal`. Empty desc → usage hint. |
| `handle_deletegoal_list_command(user_id)` | `/deletegoal` | Numbered list of active goals with emojis. No LLM. |
| `handle_deletegoal_number_command(user_id, number)` | `/deletegoal <N>` | Deactivates goal by sort position. Graceful out-of-range error. |

### _parse_and_create_goal(description, user_id, llm_fn)
LLM (70b) extracts `{ name, agent_template, type, config, end_at }` from free text → `db.create_goal(...)`.

Config fields extracted per template:
- sleep: `{ target_hours, target_bedtime }`
- fitness: `{ frequency_per_week, target }`
- money: `{ weekly_budget, watch_categories }`
- social: `{ min_social_per_week }`
- short_lived: `{ end_date, success_criteria }`

### Content flavor selection (no LLM call)
Flavors are picked deterministically per template via `TEMPLATE_FLAVOR_SETS` in `exa_client.py` — no extra LLM call. Each template has a curated set of 3 flavors (e.g. sleep: science, article, app; fitness: article, video, person). `search_content_multi(topic, template, trigger_log, count=3)` fetches one result per flavor and deduplicates URLs.

---

## 8. Exa AI Integration

**File:** `backend/shared/exa_client.py`

Uses REST API directly (`requests` library, no SDK):
```python
POST https://api.exa.ai/search
headers: { x-api-key: EXA_API_KEY }
body: { query, numResults: 1, type: "auto", contents: { highlights: { numSentences: 2 } } }
```

### 10 Content Flavors

| Flavor | Query template | Intro sentence |
|---|---|---|
| `article` | `{topic} tips guide how to improve` | "Here's something worth reading:" |
| `science` | `surprising science research behind {topic}` | "Here's a fun fact that might reframe this:" |
| `video` | `{topic} youtube video tutorial` | "This video might be worth your time:" |
| `trending` | `{topic} trending news 2025` | "Here's what's trending around this:" |
| `person` | `{topic} experts creators to follow` | "Someone worth following on this:" |
| `podcast` | `best {topic} podcast episode` | "A podcast episode on exactly this:" |
| `app` | `best app for {topic} 2024` | "There's an app that might actually help:" |
| `community` | `{topic} community Reddit Discord forum` | "You're not alone — there's a community for this:" |
| `job` | `{topic} career jobs opportunities` | "Something that caught my eye on the opportunity side:" |
| `news` | `latest {topic} research news 2025` | "What's new in this space:" |

`search_content_multi()` returns a list of `{ title, url, snippet, flavor, flavor_label, intro }` (up to 3). `search_content_varied()` still available for single-result use.

### When Exa fires
- **Reactive log:** `nudge`, `call`, or `escalate` state (monitor = silent). Returns 2-3 links across different flavors.
- **Pattern check (single agent):** always. 2-3 links.
- **Pattern check (multi-agent hackbitz):** always. 2-3 links for the primary concern.
- **Checkin:** for top concern by `TEMPLATE_PRIORITY` order. 2-3 links.
- Each link has its own intro sentence from the flavor config.

### Domain topics (DOMAIN_TOPICS)
```python
"sleep":      ["sleep optimization", "sleep science", "circadian rhythm"]
"fitness":    ["running training", "5K prep", "endurance running"]
"money":      ["personal finance", "budgeting", "financial wellness"]
"social":     ["social wellbeing", "relationships", "loneliness prevention"]
"short_lived":["deep work", "productivity under pressure", "focus techniques"]
```

---

## 9. Telegram Integration

**File:** `backend/shared/telegram_client.py`

**Bot:** `@hackbitz_bot` (token in Modal secrets + `backend/.env`)

**send_message(chat_id, text):**
- POSTs to `https://api.telegram.org/bot{TOKEN}/sendMessage`
- Uses Markdown formatting
- Returns True/False

**parse_webhook_update(body):**
- Extracts `{chat_id, text}` from Telegram webhook payload
- Returns None for non-text or unsupported updates

**Webhook URL:** `https://khalatevarun--lifeos-agents-telegram-webhook.modal.run`
Registered via: `GET https://api.telegram.org/bot{TOKEN}/setWebhook?url=<webhook_url>`

### Command routing (in telegram_webhook)

```
/status        → handle_status_command (sync, no LLM)
/confused      → handle_confused_command (sync, LLM 70b)
/plan          → handle_plan_command (sync, LLM 70b)
/help          → HELP_TEXT constant
/checkin       → ack immediately + _tick_for_user.spawn(mode="checkin")
/deletegoal    → handle_deletegoal_list_command (sync, no LLM)
/deletegoal N  → handle_deletegoal_number_command (sync, no LLM)
/addgoal <desc>→ handle_addgoal_command (sync, LLM 70b for parsing)
text log       → classify to goal_id → save to user_logs → _tick_for_user.spawn(mode="reactive_log")
```

**`/checkin` is async:** Bot immediately sends `"⚡ *hackbitz*\n\nOn it — checking in on everything right now. Give me a minute."`, then spawns `_tick_for_user` in `checkin` mode. The full summary arrives ~60s later.

---

## 10. Modal Implementation

**Secrets:** `modal.Secret.from_name("lifeos-secrets")` — stores:
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPERMEMORY_API_KEY`, `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `EXA_API_KEY`

**Image packages:** `supabase`, `supermemory`, `python-dotenv`, `fastapi[standard]`, `groq`, `exa-py`, `requests`

**Functions:**

| Function | Type | Timeout | Notes |
|---|---|---|---|
| `run_agent_for_goal(goal)` | Modal fn | 120s | Runs one agent, uses `_llm_call` (8b) |
| `run_coordinator(user_id, mode, ...)` | Modal fn | 120s | Uses `_llm_call_coordinator` (70b) |
| `tick()` | Cron (*/30) | 300s | Loads all active goals, maps agents + coordinator (pattern_check) |
| `trigger_tick()` | POST endpoint | 300s | Manual trigger for all users |
| `trigger_tick_for_user(body)` | POST endpoint | 300s | Per-user reactive trigger (called after webapp log save) |
| `telegram_webhook(body)` | POST endpoint | 60s | Receives bot messages, routes commands or classifies + saves + spawns |
| `_tick_for_user(user_id, mode, source_goal_id, trigger_log)` | Modal fn | 300s | Internal: agents + coordinator for one user. Called via `.spawn()` |

**`_tick_for_user` modes:**
- `"reactive_log"` — user just sent a text log; agents run, coordinator responds on behalf of matching agent.
- `"pattern_check"` — cron default; detect 3+ tick patterns.
- `"checkin"` — user sent `/checkin`; agents run fresh, coordinator sends full life snapshot.

**Endpoints:**
```
trigger_tick:          https://khalatevarun--lifeos-agents-trigger-tick.modal.run
trigger_tick_for_user: https://khalatevarun--lifeos-agents-trigger-tick-for-user.modal.run
telegram_webhook:      https://khalatevarun--lifeos-agents-telegram-webhook.modal.run
```

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
# resp.results[i] has: .id, .memory, .chunk, .similarity, .metadata
```

**What gets stored:** agent observations (when status != monitoring), coordinator decisions. Cross-goal context is retrieved via semantic search before each agent LLM call.

---

## 12. Frontend — LLM-Powered UX

### Goal creation
User types free-form: *"I want to sleep 8 hours a night"*

`POST /api/goals` calls Groq (`llama-3.1-8b-instant`) to classify into `{ agent_template, goal_type, name, config }`.

Goals can also be created via Telegram with `/addgoal <description>` — same LLM parsing logic, runs in `coordinator.py`.

### Log auto-routing
User types free-form: *"Skipped the gym again, feeling exhausted"*

`POST /api/logs` classifies to nearest active goal via Groq, saves with `goal_id`, then fires non-blocking `fetch` to `MODAL_TRIGGER_URL_FOR_USER` (reactive tick).

### Companion chat (`agent-chat.tsx`)
- Messages labeled by template: Fitness / Sleep / Money / Social / Deadline / All companions
- When `context.content_suggestions` is present, renders clickable link cards below message

---

## 13. Current State (as of 2026-02-28)

### Working
- All 5 Supabase tables live and seeded with demo data.
- Modal app deployed: cron (30 min) + manual trigger + reactive trigger + telegram webhook.
- Two-model Groq setup: 8b for agents (500K/day), 70b for coordinator (100K/day).
- All 5 agent templates with peer-state awareness (`get_peer_states()`).
- Coordinator: 4 modes (`reactive_log`, `pattern_check`, `win`, `checkin`).
- Pattern detection: 3+ consecutive ticks in concerning state → Telegram message.
- Win detection: agent flips from concerned → monitoring → celebration message.
- Exa: 10 content flavors, 2-3 links per message across different flavors (deterministic per template, no LLM call). Each link has its own intro sentence.
- 4-tier `/status` labels: ✅ on track / ⚠️ watch this / ⚠️ needs attention / 🔴 off track.
- Goal management via Telegram: `/addgoal`, `/deletegoal`, `/deletegoal <N>`.
- `/checkin` command: async full life snapshot with Exa for top concern.
- Coordinator dedup: one proactive Telegram message per user per 6h.
- Telegram delivery: coordinator sends assembled message; user replies saved as logs.
- Telegram webhook classifies messages with confidence score; auto-routes if >= 0.7, asks user to confirm via inline buttons if < 0.7.
- Frontend log route returns suggestion for uncertain classifications; UI shows confirmation prompt.
- Reactive tick: log save (webapp or Telegram) → coordinator responds immediately using latest states, then agents update in background (~3-5s response time instead of ~30s).
- `state_history` column: last 7 agent state snapshots per goal (migration 003).
- Voice stance: all LLM prompts use helper framing ("Let me help you with this") not observer framing ("I've noticed").
- **Multi-user Telegram:** `telegram_user_mapping` links each chat_id to a user_id. Webhook uses `get_or_create_user_by_telegram_chat(chat_id)`; coordinator uses `get_telegram_chat_id(user_id)` to send to the correct chat. New Telegram users get a welcome message on first message.

### Pending
- Run `supabase/migrations/002_delivery.sql` manually in Supabase SQL editor to add `delivered_at` column. Until then, `mark_intervention_executed` falls back to setting only `executed=true`.
- Run `supabase/migrations/003_state_history.sql` to add `state_history` column to `agent_states`. Until then, pattern detection won't fire.
- Run `supabase/migrations/004_telegram_user_mapping.sql` to add the Telegram chat → user mapping table (required for multi-user bot).
- Web app: no auth — single hardcoded mock user `00000000-0000-0000-0000-000000000001`. Telegram: each chat gets its own user_id via onboarding.

### Issues resolved (full history)
1. **GPU/vLLM removed** — Switched from A10G + vLLM to Groq free tier.
2. **Supermemory SDK v3.27.0 breaking change** — Fixed search API call.
3. **Groq 429 rate limit** — Switched agents to `llama-3.1-8b-instant`; reduced cron to 30 min; capped prompt tokens.
4. **Dedup broken** — Interventions saved without `goal_id`; dedup was checking `WHERE goal_id = uuid` → never matched. Fixed: dedup now checks by `user_id` only.
5. **Exa returning 0 results** — `exa-py` SDK `highlights` param format mismatch. Fixed: rewrote client to use REST API via `requests`.
6. **Telegram logs invisible to agents** — Bot messages saved without `goal_id`; no reactive tick. Fixed: webhook now classifies + spawns `_tick_for_user`.
7. **`mark_intervention_executed` failing** — `delivered_at` column missing (migration 002 not run). Fixed: fallback to `executed=true` only until migration runs.
8. **`/status` all showing "needs attention"** — `ACTION_TO_STATUS` map had only 2 distinct labels. Fixed: 4-tier map with ✅/⚠️/🔴.
9. **Exa never showing for nudge** — Reactive path only triggered Exa for `escalate`. Fixed: fires for `nudge`, `call`, and `escalate`.
10. **All Telegram users sharing same data** — Webhook and coordinator used single MOCK_USER_ID and TELEGRAM_CHAT_ID. Fixed: `telegram_user_mapping` table, `get_or_create_user_by_telegram_chat` / `get_telegram_chat_id` in supabase_client; webhook resolves user per chat and sends welcome for new users; coordinator `_send_telegram(user_id, text)` looks up chat_id per user.
11. **Unclassified logs silently dropped** — When LLM couldn't match a log to a goal, it was saved without goal_id and no feedback given. Fixed: classification prompt now returns confidence; uncertain matches (< 0.7) prompt user to confirm via Telegram inline buttons or web UI. Callback queries update the log's goal_id and trigger reactive analysis.
12. **High latency on reactive messages** — After a user logged something, all agents ran for all goals before the coordinator could respond (~30s). Fixed: for `reactive_log` mode, coordinator responds first using latest DB states, then agents update in the background. Also removed `_pick_exa_flavor` LLM call (was an extra 70b call just to pick a word); flavors are now deterministic per template via `TEMPLATE_FLAVOR_SETS`.
13. **Exa only sending 1 link** — Coordinator sent a single Exa result per message. Fixed: `search_content_multi()` fetches 2-3 results across different flavors per template (e.g. fitness: article + video + person). `_build_telegram_message` renders each link with its own intro sentence and snippet.
14. **No reply after logging to a new or on-track goal** — Three silent-exit paths in `_handle_reactive_log`: (a) brand-new goal with no `agent_states` row → coordinator found no matching state → silent. (b) agent state was "monitor" → silent. (c) dedup within 6h → silent. Fixed: (a) `_tick_for_user` now checks if the matched goal has an agent_state; if not, runs that single agent synchronously first. (b) "monitor" now sends a brief ack ("Got it, you're on track"). (c) dedup now sends "Logged under X" instead of silence. Users always get a reply.

---

## 14. How to Run

```bash
# Frontend
cd lifeos/frontend
npm run dev
# → http://localhost:3000

# Backend — redeploy after changes
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
python reset_user.py --all               # reset ALL users (asks for confirmation)
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
├── AGENTS.MD                          # This file — update after every architecture change
├── backend/
│   ├── .env                           # Local env (gitignored)
│   ├── .venv/                         # Python venv
│   ├── seed_demo.py                   # Seeds 5-goal Burnout Spiral demo (--reset to wipe first)
│   ├── reset_user.py                  # Wipe all data for a user (Supabase + Supermemory); --user/--chat/--all
│   ├── modal_app/
│   │   ├── __init__.py
│   │   ├── app.py                     # Modal app: two LLM fns, cron, all endpoints, _tick_for_user
│   │   │                              # Telegram command routing: /status /confused /plan /help
│   │   │                              # /checkin /addgoal /deletegoal /deletegoal N
│   │   ├── coordinator.py             # All coordinator logic:
│   │   │                              #   AGENT_PERSONAS, ACTION_TO_STATUS, HELP_TEXT
│   │   │                              #   coordinate_for_user (4 modes)
│   │   │                              #   _handle_reactive_log, _handle_pattern_check, _handle_win, _handle_checkin
│   │   │                              #   _pick_exa_flavor (LLM-driven)
│   │   │                              #   handle_status/confused/plan/addgoal/deletegoal commands
│   │   │                              #   _parse_and_create_goal, _check_patterns
│   │   │                              #   _build_telegram_message; _send_telegram(user_id, text) looks up chat_id
│   │   └── agents/
│   │       ├── __init__.py
│   │       ├── base.py                # BaseAgent: get_peer_states(), AgentResult
│   │       ├── fitness.py
│   │       ├── sleep.py
│   │       ├── money.py
│   │       ├── social.py
│   │       └── short_lived.py
│   └── shared/
│       ├── __init__.py
│       ├── supabase_client.py         # Supabase: goals, logs, agent_states, interventions, messages;
│       │                              #   get_or_create_user_by_telegram_chat, get_telegram_chat_id
│       ├── supermemory_client.py      # Supermemory helpers (SDK v3.27 compatible)
│       ├── exa_client.py              # Exa REST API: 10 flavors with intro sentences, search_content_varied
│       └── telegram_client.py         # send_message, send_message_with_buttons, answer_callback_query,
│                                      #   parse_webhook_update (messages + callback queries)
├── supabase/
│   └── migrations/
│       ├── 001_initial_schema.sql     # All 5 tables
│       ├── 002_delivery.sql           # ALTER TABLE interventions ADD COLUMN delivered_at (run manually)
│       ├── 003_state_history.sql      # ALTER TABLE agent_states ADD COLUMN state_history (run manually)
│       └── 004_telegram_user_mapping.sql  # telegram_user_mapping (chat_id → user_id) for multi-user bot
└── frontend/
    ├── .env.local
    ├── lib/
    │   ├── supabase.ts                # Supabase client + MOCK_USER_ID
    │   └── groq.ts                    # Groq fetch wrapper + parseGroqJSON
    ├── app/
    │   ├── page.tsx                   # 3-column layout
    │   └── api/
    │       ├── goals/route.ts         # POST: Groq classifies description
    │       ├── logs/route.ts          # POST: Groq routes log + fires reactive tick
    │       ├── agent-messages/route.ts
    │       ├── agent-states/route.ts
    │       └── trigger-tick/route.ts  # POST: proxies to Modal trigger_tick
    └── components/
        ├── agent-chat.tsx             # Companion messages + Exa link cards
        ├── agent-memory.tsx           # Supermemory context per companion
        ├── activity-log.tsx
        ├── goal-form.tsx
        └── ui/
```
