# LifeOS — Spec and Current State

## 0. Stack

**Frontend:** Next.js 15, React 19, Tailwind v4, shadcn/ui. No auth — single mock user.

**Backend:** Python 3.12, uv for deps, Modal for scheduling + parallel execution, Supabase for DB, Supermemory for shared semantic memory.

**LLM:**
- **Agents/coordinator (backend):** Groq API — `llama-3.3-70b-versatile`, free tier.
- **Goal classification + log routing (frontend):** Groq API — `llama-3.1-8b-instant`, free tier, called server-side from Next.js API routes.
- No GPU, no vLLM. Modal runs CPU-only functions; Groq handles all inference.

**Why Modal + Supermemory:**
- **Modal** = where and when agents run: cron schedules, parallel `.map()` over goals, web endpoint for manual trigger, secrets management.
- **Supermemory** = what agents remember: semantic search across observations, cross-goal context, time/tag-scoped queries. Agents cannot do cross-goal reasoning without it.

---

## 1. Concept

One accountability companion per goal. When a user writes "I want to sleep 8 hours a night", the system:
1. Classifies it via LLM into an agent template (sleep, fitness, money, social, short_lived, custom).
2. Spawns a goal row in Supabase with the right config.
3. An agent runs on every cron tick for that goal, reads the user's logs, queries Supermemory for cross-goal context, and decides whether to nudge/call/escalate/watch.

The coordinator runs after all per-goal agents finish, reads all agent states, and resolves conflicts (e.g., fitness agent wants to push, sleep agent says rest).

**From the user's perspective:** They have "companions" — no agent/LLM language is exposed in the UI.

---

## 2. Architecture

```
User Input (goal description / activity update)
         |
    [Next.js API routes]
    |-- POST /api/goals   → Groq classifies description → template + config → Supabase
    |-- POST /api/logs    → Groq routes log to nearest active goal → Supabase
         |
    [Supabase DB]
         |
    Modal Agent Network (cron every 15 min + manual trigger)
    |-- Load active goals from DB
    |-- For each goal, run agent template in parallel (.map):
    |   |-- Fitness template
    |   |-- Sleep template
    |   |-- Money template
    |   |-- Social template
    |   |-- Short-lived template
    |   +-- writes agent_states + observations to Supermemory
    |
    +-- Coordinator (reads all agent_states per user)
        |-- Resolves conflicts via Groq LLM
        |-- Writes interventions + agent_messages
         |
    Supermemory (shared context layer)
    |-- User logs, agent observations, cross-agent context
    |-- Semantic search for agent decision-making
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
| goal_id | uuid (nullable) | FK to goals; auto-classified by LLM |
| content | text | free-text log entry |
| source | text | `manual_input`, `agent_checkin` |
| created_at | timestamptz | default now() |
| processed | boolean | default false |

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
| executed | boolean | default false |
| outcome | text (nullable) | |
| created_at | timestamptz | default now() |

### agent_messages
| Column | Type | Notes |
|--------|------|-------|
| id | uuid (PK) | |
| user_id | uuid | |
| goal_id | uuid (nullable) | |
| from_agent | text | goal name or "coordinator" |
| to_agent | text (nullable) | null = broadcast |
| message | text | |
| context | jsonb (nullable) | |
| created_at | timestamptz | default now() |

---

## 4. Agent Templates

Each template receives `(user_id, goal_id, config)` and:
1. Loads recent `user_logs` from Supabase (scoped to goal + user-wide).
2. Queries Supermemory for semantic cross-goal context.
3. Calls Groq LLM to analyze and decide: `{ pattern_detected, confidence, context_summary, next_action }`.
4. Writes `agent_states` to Supabase and observations to Supermemory.

Templates:
- **Fitness** — skip detection, cross-context with sleep/stress signals.
- **Sleep** — duration/consistency, broadcasts deprivation context to other agents.
- **Money** — spending spike detection, stress-spending correlation.
- **Social** — isolation detection, emotional state monitoring.
- **Short-lived** — deadline-aware progress tracking, auto-deactivates after `end_at`.

---

## 5. Supermemory Usage

**SDK version:** 3.27.0. Critical: use `search.memories()` not `search.execute()` (deprecated in v3+).

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

**What gets stored:** user logs (when agent processes them), agent observations, cross-agent context summaries, coordinator decisions.

---

## 6. Modal Implementation

**Secrets:** `modal.Secret.from_name("lifeos-secrets")` — stores `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPERMEMORY_API_KEY`, `GROQ_API_KEY`.

**Image:** `modal.Image.debian_slim(python_version="3.12").pip_install("supabase", "supermemory", "python-dotenv", "fastapi[standard]", "groq")`

**No GPU.** All inference via Groq HTTP API. Cold starts are fast (~1s).

**LLM call (in app.py):**
```python
GROQ_MODEL = "llama-3.3-70b-versatile"

def _llm_call(messages: list[dict], temperature: float = 0.3) -> str:
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model=GROQ_MODEL, messages=messages, temperature=temperature, max_tokens=2048,
    )
    return response.choices[0].message.content
```

**Cron:** `modal.Cron("*/15 * * * *")` — loads active goals, dispatches per-goal agents via `.map()`, runs coordinator per user.

**Timeouts:** `run_agent_for_goal`=120s, `run_coordinator`=300s, `tick`=300s, `trigger_tick`=300s.

**Trigger URL:** `https://khalatevarun--lifeos-agents-trigger-tick.modal.run`

---

## 7. Frontend — LLM-Powered UX

### Goal creation
User types free-form: *"I want to sleep 8 hours a night"*

`POST /api/goals` calls Groq (`llama-3.1-8b-instant`) to classify:
```json
{ "agent_template": "sleep", "goal_type": "habit", "name": "Sleep 8 hours a night", "config": { "target_hours": 8 } }
```
Falls back to `custom` template on any LLM failure.

### Log auto-routing
User types free-form: *"Skipped the gym again, feeling exhausted"*

`POST /api/logs` fetches active goals, calls Groq to classify which goal the log belongs to, validates the returned ID, saves with `goal_id`. No goal selector in the UI.

### Groq client (frontend)
`frontend/lib/groq.ts` — `fetch` to `https://api.groq.com/openai/v1/chat/completions` with `GROQ_API_KEY` from `process.env` (server-side only). `parseGroqJSON<T>()` strips markdown fences and parses JSON.

---

## 8. Companion UX (What Users See)

The UI uses "companions" language throughout. No agent/LLM terminology is exposed.

- **Header:** "A set of companions that keep you accountable — across every part of your life."
- **Goals:** Shown with template emoji (🏋️ fitness, 😴 sleep, 💰 money, 🤝 social, 🎯 deadline, ✨ custom).
- **"Your companions" panel:** Messages from agents, labeled Fitness / Sleep / Money / Social / Deadline / All companions.
- **"Why they said that" panel:** Expandable rows per companion showing the Supermemory context they retrieved, confidence as "X% sure", action as "nudging you / watching / checking in / urgent".
- **"Check in now" button:** Manually triggers Modal cron tick.

---

## 9. Demo Scenario — "Burnout Spiral"

Run `python seed_demo.py --reset` from `backend/` to wipe and re-seed.

**5 goals:**
1. Sleep 8h/night (sleep agent)
2. Gym 3x/week (fitness agent)
3. Spend < $300/week (money agent)
4. Connect with friends 2x/week (social agent)
5. Submit hackathon project by deadline (short_lived, end_at = today + 2 days)

**38 logs across 7 days** telling the burnout story:
- Days 6–7: healthy baselines
- Day 5: deadline pressure starts → first sleep slip
- Day 4: sliding — missed gym, stress food order
- Day 3: crisis — 4h sleep, no social contact
- Day 2: wall — skipped workouts, isolation, anxiety
- Day 1: collapse — 3h sleep, everything falling apart, deadline panic

**Demo flow for judges:**
1. Run seed → show 5 goals on dashboard
2. Click "Check in now" → watch all companions respond in real time
3. Expand "Why they said that" → show Supermemory context coordinator used
4. Coordinator message should reference cross-goal pattern (sleep collapse → missed workouts → stress spending → isolation)

---

## 10. Current State (as of 2026-02-28)

### Working
- All 5 Supabase tables live and seeded with demo data.
- Modal app deployed, cron + manual trigger working.
- Groq LLM integration working in both backend (agent analysis) and frontend (classification).
- All 5 agent templates analyzing logs and writing `agent_states` + Supermemory observations.
- Coordinator running after agents, writing to `agent_messages`.
- Supermemory storing agent observations and returning semantic context to coordinator.
- Frontend: 3-column layout, goal creation (NL), log sharing (NL), companion messages, companion memory panel.
- `agent-memory.tsx` component shows Supermemory context per companion ("Why they said that").
- Auto-classify logs to nearest goal — no dropdown needed.
- Natural language goal creation — no template picker needed.

### Issues resolved
1. **GPU/vLLM removed** — Switched from A10G + vLLM to Groq free tier. Saves ~$26/day.
2. **Supermemory SDK v3.27.0 breaking change** — `search.execute(container_tags=[...])` removed. Fixed by switching to `search.memories(container_tag=..., threshold=...)`. Result fields changed: `.document_id` → `.id`, `.content` → `.memory or .chunk`, `.score` → `.similarity`.
3. **Modal secret already exists** — Use `modal secret create lifeos-secrets --force` to update keys.
4. **Dead `since` variable** in `supabase_client.py::get_recent_logs` — removed.

### Known limitations (not blocking for hackathon)
- `interventions.executed` is always `false` — intervention dispatch is logged but not acted on (no Twilio/email).
- No auth — single hardcoded mock user `00000000-0000-0000-0000-000000000001`.
- 15-min cron means live demo requires "Check in now" button.

---

## 11. How to Run

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
```

**Required env:**

`backend/.env`:
```
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
SUPERMEMORY_API_KEY=...
GROQ_API_KEY=...
```

`frontend/.env.local`:
```
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
MODAL_TRIGGER_URL=https://khalatevarun--lifeos-agents-trigger-tick.modal.run
GROQ_API_KEY=...
```

Modal secret (`lifeos-secrets`): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPERMEMORY_API_KEY`, `GROQ_API_KEY`.

---

## 12. Repo Layout

```
lifeos/
├── AGENTS.md                          # This file
├── backend/
│   ├── .env                           # Local env (SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPERMEMORY_API_KEY, GROQ_API_KEY)
│   ├── .venv/                         # Python venv (uv venv)
│   ├── seed_demo.py                   # Seeds 5-goal Burnout Spiral demo (--reset to wipe first)
│   ├── modal_app/
│   │   ├── __init__.py
│   │   ├── app.py                     # Modal app: _llm_call (Groq), cron tick, run_agent_for_goal, trigger_tick
│   │   ├── coordinator.py             # Coordinator: conflict resolution via Groq
│   │   └── agents/
│   │       ├── __init__.py
│   │       ├── base.py                # BaseAgent: llm_fn injection, _extract_json, Supermemory helpers
│   │       ├── fitness.py
│   │       ├── sleep.py
│   │       ├── money.py
│   │       ├── social.py
│   │       └── short_lived.py
│   └── shared/
│       ├── __init__.py
│       ├── supabase_client.py         # Supabase helpers
│       └── supermemory_client.py      # Supermemory helpers (SDK v3.27 compatible)
├── supabase/
│   └── migrations/
│       └── 001_initial_schema.sql     # All 5 tables
└── frontend/
    ├── package.json                   # Next.js 15 + React 19 + shadcn
    ├── .env.local                     # Supabase keys + MODAL_TRIGGER_URL + GROQ_API_KEY
    ├── lib/
    │   ├── utils.ts                   # cn() helper
    │   ├── supabase.ts                # Supabase client + MOCK_USER_ID
    │   └── groq.ts                    # Groq fetch wrapper + parseGroqJSON
    ├── app/
    │   ├── globals.css
    │   ├── layout.tsx
    │   ├── page.tsx                   # 3-column layout, companion-first copy
    │   └── api/
    │       ├── goals/route.ts         # POST: Groq classifies description → template + config
    │       ├── logs/route.ts          # POST: Groq routes log to nearest active goal
    │       ├── agent-messages/route.ts
    │       ├── agent-states/route.ts  # GET: agent_states joined with goals
    │       └── trigger-tick/route.ts  # POST: proxies to Modal web endpoint
    └── components/
        ├── goal-form.tsx              # Free-text input + optional deadline
        ├── activity-log.tsx           # Free-text textarea, no goal selector
        ├── agent-chat.tsx             # "Your companions" with companion labels
        ├── agent-memory.tsx           # "Why they said that" — Supermemory context per companion
        └── ui/                        # shadcn components
```
