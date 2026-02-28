# LifeOS — Spec and Current State

## 0. Stack

**Frontend:** Next.js 15, React 19, Tailwind v4, shadcn/ui. No auth — single mock user.

**Backend:** Python 3.12, uv for deps, Modal for scheduling + parallel execution, Supabase for DB, Supermemory for shared semantic memory.

**LLM:**
- **Agents (backend):** Groq API — `llama-3.1-8b-instant`, free tier (500K tokens/day). Fast, low cost.
- **Coordinator (backend):** Groq API — `llama-3.3-70b-versatile`, free tier (100K tokens/day). Better reasoning for conflict resolution.
- **Goal classification + log routing (frontend + telegram webhook):** Groq API — `llama-3.1-8b-instant`, called server-side.
- No GPU, no vLLM. Modal runs CPU-only functions; Groq handles all inference.

**Content suggestions:** Exa AI (`https://api.exa.ai/search`) — returns relevant articles/videos when agents nudge/escalate.

**Delivery:** Telegram Bot API — coordinator sends assembled messages to user; user replies go back as logs.

**Why Modal + Supermemory:**
- **Modal** = where and when agents run: cron schedules, parallel `.map()` over goals, web endpoints, secrets management.
- **Supermemory** = what agents remember: semantic search across observations, cross-goal context, time/tag-scoped queries.

---

## 1. Concept

One accountability companion per goal. When a user writes "I want to sleep 8 hours a night", the system:
1. Classifies it via LLM into an agent template (sleep, fitness, money, social, short_lived, custom).
2. Spawns a goal row in Supabase with the right config.
3. An agent runs on every tick for that goal, reads the user's logs, queries Supermemory for cross-goal context, reads peer agent states, and decides whether to nudge/call/escalate/watch.

The coordinator runs after all per-goal agents finish, reads all agent states, deduplicates, and dispatches a single Telegram message.

**From the user's perspective:** They have "companions" — no agent/LLM language is exposed in the UI.

---

## 2. Architecture

```
User Input
  [Webapp]                          [Telegram Bot @hackbitz_bot]
  POST /api/logs (classify+save)    → telegram_webhook (classify+save)
       |                                      |
       | fire-and-forget                      | .spawn()
       ↓                                      ↓
  trigger_tick_for_user            _tick_for_user (Modal fn)
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
            |   |-- if nudge/escalate → calls Exa AI → content_suggestions[]
            |   |-- writes agent_states + agent_messages (with content_suggestions in context JSONB)
            |   +-- saves observations to Supermemory
            |
            +-- Coordinator (runs after all agents settle)
                |-- reads agent_states, filters agents requesting action
                |-- DEDUP: if any intervention sent to this user in last 6h → skip
                |-- if 1 agent: approve_single
                |-- if 2+ agents: Groq 70b resolves conflicts (health > deadline > fitness > money)
                |-- assembles Telegram message: one section per agent + unified coordinator line
                |-- sends via Telegram Bot API
                |-- marks intervention executed=true, delivered_at=now()
                |-- saves decision to Supermemory

[Telegram] ←──── coordinator sends message ──── [Supabase: interventions]
    |
    | user replies
    ↓
telegram_webhook → classify log → save to user_logs → spawn _tick_for_user

[Webapp] ←──── polls agent_messages + agent_states ──── [Supabase]
              renders companion messages with Exa link cards
```

---

## 3. Data Model (Supabase)

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
| updated_at | timestamptz | default now() |

### interventions
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| goal_id | uuid (nullable) | |
| triggered_by | text[] | agent/goal names that voted |
| intervention_type | text | `nudge`, `call`, `text`, `escalate` |
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
| from_agent | text | `{template}:{goal_id}` or "coordinator" |
| to_agent | text (nullable) | null = broadcast |
| message | text | |
| context | jsonb (nullable) | includes `content_suggestions: [{title, url, snippet, published_date}]` when Exa runs |
| created_at | timestamptz | default now() |

---

## 4. Agent Templates

Each template receives `(user_id, goal_id, config)` and:
1. Loads recent `user_logs` from Supabase (scoped to goal_id, last 7-14 days, capped at 10 entries, 120 chars each).
2. Queries Supermemory for cross-goal semantic context (capped at 4 results, 120 chars each).
3. Calls `get_peer_states(user_id, exclude_goal_id)` — reads all other agents' current `agent_states` and formats as text for the LLM prompt.
4. Calls Groq `llama-3.1-8b-instant` with the combined prompt.
5. If `next_action in (nudge, call, escalate)` → calls Exa AI for 3 relevant content suggestions.
6. Returns `AgentResult` with `content_suggestions` list.
7. Writes `agent_states` to Supabase + observations to Supermemory.

Templates:
- **Fitness** — skip detection, backs off if sleep companion is escalating.
- **Sleep** — duration/consistency, highest priority in coordinator.
- **Money** — spending spike detection, stress-spending correlation.
- **Social** — isolation detection, emotional state monitoring.
- **Short-lived** — deadline-aware progress tracking, auto-deactivates after `end_at`.

### AgentResult fields
```python
status: str               # "monitoring" | "concerned" | "intervention_needed"
next_action: str          # "monitor" | "nudge" | "call" | "escalate"
reasoning: str
confidence: float         # 0.0–1.0
context_summary: str      # truncated to 500 chars
message_to_user: str|None # displayed in webapp + sent via Telegram
content_suggestions: list[dict]  # [{title, url, snippet, published_date}] from Exa
```

### get_peer_states() (BaseAgent method)
Reads all `agent_states` for the user (excluding own goal), formats as:
```
- Sleep companion (Sleep 8h): escalate (confidence 0.92) — "concerned". Context: ...
- Fitness companion (Gym 3x): monitor (confidence 0.4)
```
Injected into every agent's LLM prompt so agents self-regulate without a central coordinator pre-run.

---

## 5. Coordinator Logic

```python
def coordinate_for_user(user_id, llm_fn):
    agent_states = db.get_agent_states_for_user(user_id)
    action_requests = [s for s in agent_states if next_action in (nudge, call, escalate)]

    if not action_requests:
        return no_action

    # DEDUP: skip if ANY intervention was sent to this user in the last 6h
    recent = db.get_recent_interventions(user_id, hours=6)
    if recent:
        return no_action  # prevents cron spam

    if len(action_requests) == 1:
        approve_single → _log_decision()

    else:
        # LLM (70b) resolves conflicts: health > deadline > fitness > money
        decision = llm(COORDINATOR_SYSTEM_PROMPT, states_summary + memory_context)
        _log_decision()

def _log_decision(user_id, decision, action_requests):
    db.create_agent_message(coordinator message)
    intervention = db.create_intervention(...)

    # Build Telegram message: one section per requesting agent
    # Collect Exa links from agent_messages.context.content_suggestions
    telegram_client.send_message(chat_id, assembled_text, links=all_links)
    db.mark_intervention_executed(intervention.id)  # sets executed=true, delivered_at=now()

    mem.add_memory(coordinator decision)
```

**Delivery decision table:**

| Agents requesting | Action | Channel |
|---|---|---|
| 0 | — | nothing |
| 1 agent, any action | nudge/call/escalate | Telegram message + top Exa link per agent |
| 2+ agents | coordinate | Telegram with all agent sections + unified message |
| Same user intervened < 6h ago | any | skip (dedup) |

---

## 6. Exa AI Integration

**File:** `backend/shared/exa_client.py`

Uses REST API directly (`requests` library, no SDK dependency):
```python
POST https://api.exa.ai/search
headers: { x-api-key: EXA_API_KEY }
body: { query, numResults, type: "auto", contents: { highlights: { numSentences: 2 } } }
```

Returns `[{title, url, snippet, published_date}]`. Returns `[]` silently if `EXA_API_KEY` missing or any error.

**Agent-specific queries:**
- Fitness: `"10 minute home workout when you haven't exercised in a week"`
- Sleep: `"how sleep deprivation affects productivity and health science"`
- Money: `"how to stop stress spending practical tips mindful money habits"`
- Social: `"how to reconnect with friends when feeling isolated and overwhelmed"`
- Short-lived: `"how to focus and make progress on a project with N days remaining productivity tips"`

---

## 7. Telegram Integration

**File:** `backend/shared/telegram_client.py`

**Bot:** `@hackbitz_bot` (token in Modal secrets + `backend/.env`)

**send_message(chat_id, text, links=[]):**
- POSTs to `https://api.telegram.org/bot{TOKEN}/sendMessage`
- Uses Markdown formatting, appends link list at bottom (up to 3 links)
- Returns True/False

**parse_webhook_update(body):**
- Extracts `{chat_id, text}` from Telegram webhook payload
- Returns None for non-text or bot commands

**Webhook URL:** `https://khalatevarun--lifeos-agents-telegram-webhook.modal.run`
Registered via: `GET https://api.telegram.org/bot{TOKEN}/setWebhook?url=<webhook_url>`

**Webhook flow:**
1. User sends message to `@hackbitz_bot`
2. Telegram POSTs to `telegram_webhook` Modal endpoint
3. Bot command (e.g. `/start`) → ignored
4. Text message → classify to goal_id via Groq → save to `user_logs` → spawn `_tick_for_user`
5. Agents run, coordinator assembles response, sends back via Telegram

---

## 8. Supermemory Usage

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

## 9. Modal Implementation

**Secrets:** `modal.Secret.from_name("lifeos-secrets")` — stores:
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPERMEMORY_API_KEY`, `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `EXA_API_KEY`

**Image packages:** `supabase`, `supermemory`, `python-dotenv`, `fastapi[standard]`, `groq`, `exa-py`, `requests`

**Functions:**

| Function | Type | Timeout | Notes |
|---|---|---|---|
| `run_agent_for_goal(goal)` | Modal fn | 120s | Runs one agent, uses `_llm_call` (8b) |
| `run_coordinator(user_id)` | Modal fn | 120s | Uses `_llm_call_coordinator` (70b) |
| `tick()` | Cron (*/30) | 300s | Loads all active goals, maps agents + coordinator |
| `trigger_tick()` | POST endpoint | 300s | Manual trigger for all users |
| `trigger_tick_for_user(body)` | POST endpoint | 300s | Per-user reactive trigger (called after webapp log save) |
| `telegram_webhook(body)` | POST endpoint | 60s | Receives bot messages, classifies, saves log, spawns `_tick_for_user` |
| `_tick_for_user(user_id)` | Modal fn | 300s | Internal: agents + coordinator for one user. Called via `.spawn()` for fire-and-forget |

**Endpoints:**
```
trigger_tick:          https://khalatevarun--lifeos-agents-trigger-tick.modal.run
trigger_tick_for_user: https://khalatevarun--lifeos-agents-trigger-tick-for-user.modal.run
telegram_webhook:      https://khalatevarun--lifeos-agents-telegram-webhook.modal.run
```

---

## 10. Frontend — LLM-Powered UX

### Goal creation
User types free-form: *"I want to sleep 8 hours a night"*

`POST /api/goals` calls Groq (`llama-3.1-8b-instant`) to classify into `{ agent_template, goal_type, name, config }`.

### Log auto-routing
User types free-form: *"Skipped the gym again, feeling exhausted"*

`POST /api/logs` classifies to nearest active goal via Groq, saves with `goal_id`, then fires non-blocking `fetch` to `MODAL_TRIGGER_URL_FOR_USER` (reactive tick).

### Companion chat (`agent-chat.tsx`)
- Messages labeled by template: Fitness / Sleep / Money / Social / Deadline / All companions
- When `context.content_suggestions` is present, renders clickable link cards below message (title + snippet)

---

## 11. Companion UX (What Users See)

- **"Your companions" panel:** Agent messages with Exa content link cards when present.
- **"Why they said that" panel:** Supermemory context per companion, confidence %, next action label.
- **"Check in now" button:** Triggers `trigger_tick` for all users.
- **Telegram:** Receives assembled multi-companion message. Can reply to bot to log updates.

---

## 12. Current State (as of 2026-02-28)

### Working
- All 5 Supabase tables live and seeded with demo data.
- Modal app deployed, cron (30 min) + manual trigger + reactive trigger working.
- Two-model Groq setup: 8b for agents (500K/day), 70b for coordinator (100K/day).
- All 5 agent templates with peer-state awareness (`get_peer_states()`).
- Exa AI content suggestions on nudge/escalate — rendered as link cards in webapp.
- Coordinator dedup: one Telegram message per user per 6h.
- Telegram delivery: coordinator sends assembled message; user replies saved as logs.
- Telegram webhook classifies messages to goal_id before saving.
- Reactive tick: log save (webapp or Telegram) → agents run within ~30s.
- Frontend renders Exa link cards in companion chat.

### Pending
- Run `supabase/migrations/002_delivery.sql` manually in Supabase SQL editor to add `delivered_at` column (`ALTER TABLE interventions ADD COLUMN IF NOT EXISTS delivered_at timestamptz`). Until then, `mark_intervention_executed` falls back to setting only `executed=true`.
- No auth — single hardcoded mock user `00000000-0000-0000-0000-000000000001`.

### Issues resolved (full history)
1. **GPU/vLLM removed** — Switched from A10G + vLLM to Groq free tier.
2. **Supermemory SDK v3.27.0 breaking change** — Fixed search API call.
3. **Groq 429 rate limit** — Switched agents to `llama-3.1-8b-instant`; reduced cron to 30 min; capped prompt tokens.
4. **Dedup broken** — Interventions saved without `goal_id`; dedup was checking `WHERE goal_id = uuid` → never matched. Fixed: dedup now checks by `user_id` only.
5. **Exa returning 0 results** — `exa-py` SDK `highlights` param format mismatch. Fixed: rewrote client to use REST API via `requests`.
6. **Telegram logs invisible to agents** — Bot messages saved without `goal_id`; no reactive tick. Fixed: webhook now classifies + spawns `_tick_for_user`.
7. **`mark_intervention_executed` failing** — `delivered_at` column missing (migration 002 not run). Fixed: fallback to `executed=true` only until migration runs.

---

## 13. How to Run

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

## 14. Repo Layout

```
lifeos/
├── AGENTS.MD                          # This file — update after every architecture change
├── backend/
│   ├── .env                           # Local env (gitignored)
│   ├── .venv/                         # Python venv
│   ├── seed_demo.py                   # Seeds 5-goal Burnout Spiral demo (--reset to wipe first)
│   ├── modal_app/
│   │   ├── __init__.py
│   │   ├── app.py                     # Modal app: two LLM fns, cron, all endpoints, _tick_for_user
│   │   ├── coordinator.py             # Coordinator: dedup, conflict resolution, Telegram dispatch
│   │   └── agents/
│   │       ├── __init__.py
│   │       ├── base.py                # BaseAgent: get_peer_states(), AgentResult (with content_suggestions)
│   │       ├── fitness.py             # + Exa search on nudge
│   │       ├── sleep.py               # + Exa search on nudge
│   │       ├── money.py               # + Exa search on nudge
│   │       ├── social.py              # + Exa search on nudge
│   │       └── short_lived.py         # + Exa search on nudge
│   └── shared/
│       ├── __init__.py
│       ├── supabase_client.py         # Supabase helpers + get_recent_interventions + mark_intervention_executed
│       ├── supermemory_client.py      # Supermemory helpers (SDK v3.27 compatible)
│       ├── exa_client.py              # Exa REST API wrapper (no SDK, uses requests)
│       └── telegram_client.py         # Telegram send_message + parse_webhook_update
├── supabase/
│   └── migrations/
│       ├── 001_initial_schema.sql     # All 5 tables
│       └── 002_delivery.sql           # ALTER TABLE interventions ADD COLUMN delivered_at (run manually)
└── frontend/
    ├── .env.local                     # Supabase keys + MODAL_TRIGGER_URL + MODAL_TRIGGER_URL_FOR_USER + GROQ_API_KEY
    ├── lib/
    │   ├── supabase.ts                # Supabase client + MOCK_USER_ID
    │   └── groq.ts                    # Groq fetch wrapper + parseGroqJSON
    ├── app/
    │   ├── page.tsx                   # 3-column layout
    │   └── api/
    │       ├── goals/route.ts         # POST: Groq classifies description
    │       ├── logs/route.ts          # POST: Groq routes log + fires reactive tick (fire-and-forget)
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
