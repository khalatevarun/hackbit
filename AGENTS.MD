# LifeOS — Revised Spec and Implementation Plan

## 0. Stack and Why Supermemory vs Modal

**Stack (locked in):**
- **Frontend:** Next.js, shadcn, Clerk for auth (as of now: no auth; add Clerk when needed).
- **Frontend scope:** Text input to create goals (short-lived vs long-term), text input for logging an activity. Nothing else for now.
- **Backend:** Python only; **uv** for all dependencies (no global pip). Use **Modal Python SDK** (official `modal` package) for scheduling, execution, **and LLM inference**. **Supabase** for DB; **Supermemory** for context sharing. **No external LLM API** (no OpenAI SDK) — all inference runs on Modal GPUs via vLLM.

**Modal vs Supermemory — do we need both?**
- **Modal** = *where* and *when* code runs: cron schedules, parallel execution (e.g. `run_agent_for_goal.remote.aio(goal_id)`), secrets, **GPU-powered LLM inference** via `modal.Cls` + vLLM. It does **not** store or search semantic memory.
- **Supermemory** = *what* agents remember: store observations and logs, **semantic search** ("why is user skipping workouts?"), time/tag-scoped queries, shared context across agents. Modal cannot do this without you building embeddings + vector search (e.g. pgvector) yourself.
- **Conclusion:** Use both. Modal runs the agent/coordinator jobs **and** hosts the LLM; Supermemory is the shared memory layer agents query. They are complementary.

**Modal feature choices (right-sized for this phase):**
- **Cron** (`modal.Cron`) for the main tick (e.g. every 15 min) and optionally per-template schedules.
- **Secrets** (`modal.Secret.from_name("lifeos-secrets")`) for Supabase + Supermemory keys at runtime.
- **GPU LLM** (`modal.Cls` with `gpu="A10G"`) running `Qwen/Qwen2.5-7B-Instruct` via vLLM. Uses `modal.Image.from_registry("vllm/vllm-openai:v0.7.3")` for a tested vLLM+transformers+CUDA stack. Model weights downloaded during image build. `min_containers=1` keeps GPU always warm; `scaledown_window=960` for backup.
- **Parallelism:** One function per goal via `run_agent_for_goal.map(goals)`; agents run on CPU containers, LLM calls dispatch to the GPU container via `.remote()`.
- **No** Modal Volumes for Phase 1; keep state in Supabase + Supermemory.

---

## 1. Concept Shift: From Fixed Agents to Dynamic Agents

**Original spec:** Four fixed agents (Gym Bro, Sleep Sheriff, Money Monitor, Social Connector) + Coordinator.

**Revised model:**

- **One accountability agent per goal/habit** — When a user creates "Gym 3x/week" or "Sleep by 11pm", an agent instance is spawned for that goal. The agent's behavior is driven by **agent templates** (fitness, sleep, money, social) plus goal-specific config (frequency, target, etc.).
- **Short-lived agents** — Goals with an end date (e.g., "Exam next week", "Project deadline March 15") get a temporary agent that runs until `end_date`, with configurable check-in cadence and optional success criteria.
- **Coordinator** — Still a single meta-orchestrator that runs on a schedule, but now reasons over **N** agent instances (one per active goal) instead of exactly four. It resolves conflicts (e.g., fitness agent wants to nudge, sleep agent says rest) and decides who intervenes and how.

So we keep the same **intelligence layer** (templates + shared context + coordinator), but the **number and identity** of agents are dynamic and driven by the goals table.

---

## 2. System Architecture

```
User Input (goal creation / activity log)
         |
    [Supabase DB]
         |
    Modal Agent Network (cron every 15 min)
    |-- Load active goals from DB
    |-- For each goal, run agent template in parallel:
    |   |-- Fitness template
    |   |-- Sleep template
    |   |-- Money template
    |   |-- Social template
    |   |-- Short-lived template
    |   +-- (writes agent_states back to DB)
    |
    +-- Coordinator (reads all agent_states per user)
        |-- Resolves conflicts via LLM
        |-- Decides interventions
        +-- Writes interventions + agent_messages
         |
    Supermemory (shared context layer)
    |-- User logs, agent observations, cross-agent comms
    |-- Semantic search for agent decision-making
```

- **Modal:** Single cron tick (every 15 min) loads active goals from Supabase, dispatches each to the right template via `run_agent_for_goal.remote.aio(goal_id)` in parallel, then runs coordinator per user.
- **Supermemory:** Semantic context store. `containerTags: [user_id]` for user-wide context; metadata `goal_id` for goal-scoped queries. Python SDK: `client.memory.create(...)` and `client.search.memories(...)`.

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
| goal_id | uuid (nullable) | FK to goals |
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

## 4. Agent Templates (Parameterized by Goal)

Each template receives `(user_id, goal_id, config)` and:
1. Loads recent `user_logs` from Supabase (scoped to goal or user-wide).
2. Queries Supermemory for semantic context (cross-goal awareness).
3. Computes a state: `monitoring`, `concerned`, `intervention_needed`.
4. Writes `agent_states` and observations to Supermemory.

- **Fitness** — skip detection, cross-context (sleep, stress).
- **Sleep** — duration/consistency tracking, broadcasts to other agents when deprived.
- **Money** — spending spike detection, stress-spending correlation.
- **Social** — isolation detection, emotional state monitoring.
- **Short-lived** — deadline-aware progress tracking, auto-deactivates after `end_at`.

---

## 5. Supermemory Usage

- **Store:** `client.memory.create(content=..., metadata={...}, containerTags=[user_id])`. Metadata includes `goal_id`, `agent_template`, `timestamp`, `activity_type`.
- **Search:** `client.search.memories(q=..., container_tag=user_id, search_mode="hybrid", limit=10, filters={...})`. Filters on metadata for goal_id, time range, etc.
- **What gets stored:** user logs, agent observations, cross-agent messages, coordinator decisions, intervention outcomes.

---

## 6. Modal Implementation

- **Secrets:** `modal.Secret.from_name("lifeos-secrets")` for Supabase + Supermemory keys.
- **LLM:** `LLMService` class (`@app.cls(gpu="A10G")`) runs `Qwen/Qwen2.5-7B-Instruct` via vLLM. `@modal.enter()` loads the model once; `@modal.method()` handles inference. Model weights downloaded during image build for fast cold starts.
- **Cron:** Single tick every 15 min → load active goals → dispatch per-goal agents in parallel → run coordinator. All LLM calls from agents/coordinator route to the GPU service via `_llm_call` → `LLMService().generate.remote()`.
- **Per-goal function:** `run_agent_for_goal(goal_id)` — loads goal, injects `llm_fn`, runs template, writes state.
- **Coordinator:** `coordinator_for_user(user_id, llm_fn)` — reads all states, resolves conflicts via LLM on Modal GPU, writes interventions.

---

## 7. Short-Lived Agent Behavior

- Created with `type = short_lived`, `end_at` set.
- Included in same cron tick; skipped if `end_at < now()` (then marked `active = false`).
- Checks progress logs; nudges/escalates if deadline approaching with no progress.

---

## 8. Not Building in This Phase

- **Auth:** No Clerk; single-user or mock `user_id`.
- Voice calls, fancy UI, Twilio — only the intelligence layer. Intervention output is DB rows for a later phase.

---

## 9. Implementation Phases

**Phase 1 — Foundation:** Supabase tables, uv backend scaffold, Modal app bootstrap, Supermemory helpers.

**Phase 2 — Agent templates:** Fitness, sleep, money, social, short-lived templates. Wire cron dispatch.

**Phase 3 — Coordinator:** Conflict resolution via LLM, intervention logging.

**Phase 4 — Frontend + polish:** Next.js + shadcn minimal UI (create goal, log activity, view agent messages).

---

## 10. Current State (as of 2026-02-28, evening)

### What's done

- **Supabase:** All 5 tables created and working (`goals`, `user_logs`, `agent_states`, `interventions`, `agent_messages`). Schema in `supabase/migrations/001_initial_schema.sql`.
- **Backend (Modal):**
  - App name: `lifeos-agents`. Deployed to Modal (`modal deploy modal_app/app.py`).
  - OpenAI SDK fully removed. LLM runs on Modal GPU via vLLM (`Qwen/Qwen2.5-7B-Instruct` on A10G).
  - LLM image uses **vLLM's official Docker image** (`vllm/vllm-openai:v0.7.3`) via `modal.Image.from_registry()` to avoid vLLM/transformers version conflicts. Model weights downloaded during image build.
  - `LLMService` class (`@app.cls(gpu="A10G", min_containers=1, scaledown_window=960)`) with `@modal.enter()` for model loading and `@modal.method()` for inference. `min_containers=1` keeps one GPU always warm (no cold starts). `scaledown_window=960` ensures it survives between 15-min cron ticks.
  - LLM injected into agents and coordinator via `_llm_call` wrapper using dependency injection.
  - All 5 agent templates (fitness, sleep, money, social, short_lived) implemented and using `self.llm_assess()`.
  - Coordinator implemented with LLM-based conflict resolution for multi-agent scenarios.
  - Cron tick every 15 min (`modal.Cron("*/15 * * * *")`).
  - Web endpoint `trigger_tick` (`@modal.fastapi_endpoint`) for manual triggering from frontend.
  - Trigger URL: `https://khalatevarun--lifeos-agents-trigger-tick.modal.run`
  - Modal secret: `lifeos-secrets` (stores `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPERMEMORY_API_KEY`).
  - Error handling: `run_agent_for_goal` and `run_coordinator` both wrapped in try/except with full traceback logging to Modal stdout. Errors return `{"status": "error", "error": str(e)}` instead of crashing the `.map()`.
  - All timeouts increased: `run_agent_for_goal`=600s, `run_coordinator`=600s, `tick`=900s, `trigger_tick`=900s, `LLMService`=600s.
- **Frontend:**
  - Next.js 15 + React 19 + Tailwind v4 + shadcn initialized and running.
  - Goal creation form, activity log input, agent chat display all working.
  - API routes: `/api/goals`, `/api/logs`, `/api/agent-messages`, `/api/trigger-tick`.
  - "Run Agents" button in header triggers the Modal web endpoint.
  - `.env.local` configured with Supabase URL/key and `MODAL_TRIGGER_URL`.
  - Mock user ID: `00000000-0000-0000-0000-000000000001`.
- **Local dev setup:**
  - Backend venv at `backend/.venv` (created with `uv venv`, has `modal` + `supabase` installed).
  - Modal CLI authenticated via `modal setup` (token in `~/.modal.toml`).
- **Supermemory:**
  - Client (`shared/supermemory_client.py`) stores agent observations and coordinator decisions; provides semantic search for cross-agent context.
  - Currently empty — will populate once agents complete a successful run.
  - Dashboard at `app.supermemory.com` shows search requests from agents but no stored memories yet.

### Issues resolved

1. **`@modal.web_endpoint` renamed to `@modal.fastapi_endpoint`** — Modal deprecated the old name.
2. **`container_idle_timeout` renamed to `scaledown_window`** — Modal deprecation.
3. **`fastapi[standard]` added to `agent_image`** — required for web endpoints.
4. **`FunctionTimeoutError` (300s)** — `run_agent_for_goal` timed out because the LLM GPU cold start (~2.5 min) + agent logic exceeded the 300s limit. Fixed by increasing all timeouts and adding `min_containers=1`.
5. **vLLM/transformers tokenizer crash (`all_special_tokens_extended` AttributeError)** — latest `transformers` removed an attribute that vLLM's tokenizer caching relied on. Affected both Qwen and Mistral models when using `debian_slim` + `pip install vllm`. Fixed by switching to `modal.Image.from_registry("vllm/vllm-openai:v0.7.3")` which bundles compatible vLLM + transformers + CUDA together.

### Current blocker (needs verification after redeploy)

The vLLM Docker image fix (`vllm/vllm-openai:v0.7.3`) has been applied but needs a fresh deploy to verify. Once the LLM loads successfully, the full agent pipeline should work. The error handling in `run_agent_for_goal` will now surface any remaining issues (Supermemory, JSON parsing, etc.) in Modal logs instead of silently failing.

**If the LLM still fails after deploying**, check Modal dashboard logs at `https://modal.com/apps/khalatevarun/main/deployed/lifeos-agents`. Remaining risks:
- Supermemory API key in `lifeos-secrets` may not match `backend/.env` — verify in Modal dashboard under Secrets.
- LLM may return non-JSON output that `_extract_json()` can't parse — logs will now show the raw output and traceback.

### How to resume development

```bash
# Terminal 1 — Frontend
cd lifeos/frontend
npm run dev
# Open http://localhost:3000

# Terminal 2 — Backend (deploy after changes)
cd lifeos/backend
source .venv/bin/activate
modal deploy modal_app/app.py

# To test a single tick manually:
modal run modal_app/app.py
```

### Budget note

$280 Modal credits available, expiring in ~2 days. With `min_containers=1` on A10G ($1.10/hr), the GPU costs ~$26/day ($52 total). Remaining ~$228 covers all CPU agent runs and experimentation. When done testing, remove `min_containers=1` or run `modal app stop lifeos-agents` to stop burning GPU credits.

---

## 11. Repo Layout

```
lifeos/
├── AGENTS.MD                          # This file
├── backend/
│   ├── .env                           # Local env vars (SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPERMEMORY_API_KEY)
│   ├── .venv/                         # Python venv (uv venv, has modal + supabase)
│   ├── modal_app/
│   │   ├── __init__.py
│   │   ├── app.py                     # Modal app: LLMService, cron, run_agent_for_goal, coordinator, trigger_tick web endpoint
│   │   ├── coordinator.py             # Coordinator logic (accepts llm_fn)
│   │   └── agents/
│   │       ├── __init__.py
│   │       ├── base.py                # BaseAgent with llm_fn injection, _extract_json helper
│   │       ├── fitness.py
│   │       ├── sleep.py
│   │       ├── money.py
│   │       ├── social.py
│   │       └── short_lived.py
│   └── shared/
│       ├── __init__.py
│       ├── supabase_client.py         # Supabase helpers
│       └── supermemory_client.py      # Supermemory helpers
├── supabase/
│   └── migrations/
│       └── 001_initial_schema.sql     # All tables
└── frontend/
    ├── package.json                   # Next.js 15 + React 19 + shadcn
    ├── tsconfig.json
    ├── next.config.ts
    ├── postcss.config.mjs
    ├── components.json                # shadcn config
    ├── .env.local                     # NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, MODAL_TRIGGER_URL
    ├── lib/
    │   ├── utils.ts                   # cn() helper
    │   └── supabase.ts                # Supabase client + MOCK_USER_ID
    ├── app/
    │   ├── globals.css                # Tailwind v4 + shadcn CSS variables
    │   ├── layout.tsx
    │   ├── page.tsx                   # 3-column layout + "Run Agents" button
    │   └── api/
    │       ├── goals/route.ts
    │       ├── logs/route.ts
    │       ├── agent-messages/route.ts
    │       └── trigger-tick/route.ts  # Proxies to Modal web endpoint
    └── components/
        ├── goal-form.tsx
        ├── activity-log.tsx
        ├── agent-chat.tsx
        └── ui/                        # shadcn components (badge, button, card, input, label, select, tabs, textarea)
```
