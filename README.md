# Hackbitz

**One companion per goal. They talk to each other so you don't have to.**

Most habit trackers just count streaks. Hackbitz gives each of your goals its own AI companion that actually reads your logs, notices patterns across your life, and reaches out through Telegram when something needs attention. Skip the gym three days in a row while your sleep is great? Your fitness companion knows, and it also knows your sleep companion isn't worried — so it nudges you gently instead of panicking.

---

## What it does

You tell Hackbitz what you're working on in plain English:

> "Go to the gym 4 times a week"
> "Sleep 8 hours, be in bed by 11pm"
> "Keep weekly spending under $150"

Each goal gets its own companion (fitness, sleep, money, social, or deadline-based). You share updates whenever — through the web app or by texting a Telegram bot. The system figures out which goal your message belongs to and routes it automatically.

Every 15 minutes (and reactively when you log something), all companions run in parallel:

- Read your recent logs
- Check what the other companions are thinking
- Search semantic memory for cross-goal context
- Decide: **watch**, **nudge**, **call out**, or **escalate**

Then a coordinator steps in. If multiple companions are concerned, it picks the ONE thing that matters most (sleep > deadlines > fitness > money) and sends you a single Telegram message — not five. If nothing's wrong, it stays quiet.

When a companion does reach out, it also pulls in a relevant article, podcast, or tool from Exa AI — so you get something actionable, not just "hey, do better."

---

## How it works

```
You (web app / Telegram)
  │
  ├─ "Skipped gym again, feeling lazy"
  │     │
  │     ├─ LLM classifies → fitness goal
  │     ├─ Saved to Supabase (user_logs)
  │     └─ Triggers agent tick
  │
  ▼
Modal Agent Network (parallel)
  │
  ├─ Fitness agent: "3 skips this week, 0/4 target" → nudge
  ├─ Sleep agent: "8h avg, consistent bedtime" → monitor (all good)
  ├─ Money agent: "$92 spent, under $150" → monitor
  └─ Social agent: "cancelled plans 3x this month" → concerned
  │
  ▼
Coordinator
  │
  ├─ 2 agents want to intervene (fitness + social)
  ├─ LLM resolves: "Focus on fitness. Social can wait."
  ├─ Pulls Exa article: "10-min home workout for zero motivation days"
  └─ Sends ONE Telegram message with everything
```

The companions also talk to each other through shared state. If your sleep companion is escalating, your fitness companion backs off — because pushing someone to work out when they're sleep-deprived doesn't help.

---

## Telegram bot

Text `@hackbitz_bot` on Telegram. It's the main way companions reach you.

**Commands:**

- `/status` — quick health check across all goals (no LLM, instant)
- `/confused` — "just tell me the ONE thing I should do right now"
- `/plan` — today's top 3 priorities based on current state
- `/help` — what the bot can do

Or just text it anything: _"slept terribly"_, _"spent $40 on lunch"_, _"went for a run today"_ — it classifies, saves, and triggers the right companion.

---

## Tech stack

| Layer    | What                                                              | Why                                                          |
| -------- | ----------------------------------------------------------------- | ------------------------------------------------------------ |
| Frontend | Next.js 15, React 19, Tailwind v4, shadcn/ui                      | fast to build, looks clean                                   |
| Database | Supabase (Postgres)                                               | real-time, good free tier, instant API                       |
| Backend  | Modal (Python)                                                    | cron scheduling, parallel `.map()` over goals, zero infra    |
| LLM      | Groq API (llama-3.1-8b for agents, llama-3.3-70b for coordinator) | free tier, ~200ms latency, no GPU needed                     |
| Memory   | Supermemory                                                       | semantic search across observations, cross-goal context      |
| Content  | Exa AI                                                            | finds relevant articles/podcasts/tools when companions nudge |
| Delivery | Telegram Bot API                                                  | instant, personal, no app to install                         |

No GPU. No vLLM. Modal runs CPU-only functions; Groq handles all inference. The whole thing runs on free tiers.

---

## Project structure

```
├── frontend/                    # Next.js web app
│   ├── app/
│   │   ├── api/goals/          # CRUD + LLM classification
│   │   ├── api/logs/           # Activity logs + auto-routing
│   │   ├── api/agent-messages/ # Companion messages
│   │   ├── api/agent-states/   # Agent internal states
│   │   └── api/trigger-tick/   # Manual agent trigger
│   ├── components/             # GoalForm, ActivityLog, AgentChat, AgentMemory
│   └── lib/                    # Supabase client, Groq client
│
├── backend/
│   ├── modal_app/
│   │   ├── app.py              # Modal entrypoint: cron, parallel agents, coordinator
│   │   ├── coordinator.py      # Cross-agent conflict resolution, Telegram delivery
│   │   └── agents/             # fitness, sleep, money, social, short_lived
│   │       └── base.py         # BaseAgent: logs, memory, peer states, LLM assess
│   └── shared/
│       ├── supabase_client.py  # DB operations
│       ├── supermemory_client.py
│       ├── exa_client.py       # Content suggestions with rotating "flavors"
│       └── telegram_client.py
│
├── supabase/migrations/        # SQL schema
└── docs/openapi.yaml           # API documentation (Swagger/OpenAPI 3.0)
```

---

## Setup

### 1. Get your keys

You need accounts on: [Supabase](https://supabase.com), [Groq](https://console.groq.com), [Modal](https://modal.com), [Supermemory](https://supermemory.com)

Exa AI and Telegram are optional — the system works without them, just no content suggestions or Telegram delivery.

### 2. Create the database

In your Supabase SQL editor, run the contents of `supabase/migrations/001_initial_schema.sql`. Then disable RLS for Phase 1:

```sql
ALTER TABLE goals DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_logs DISABLE ROW LEVEL SECURITY;
ALTER TABLE agent_states DISABLE ROW LEVEL SECURITY;
ALTER TABLE interventions DISABLE ROW LEVEL SECURITY;
ALTER TABLE agent_messages DISABLE ROW LEVEL SECURITY;
```

### 3. Backend

```bash
pip install modal
modal token new

# Create the secret with your keys
modal secret create lifeos-secrets \
  GROQ_API_KEY=your_key \
  SUPABASE_URL=https://your-project.supabase.co \
  SUPABASE_SERVICE_KEY=your_service_key \
  SUPERMEMORY_API_KEY=your_key

# Deploy
modal deploy backend/modal_app/app.py
```

### 4. Frontend

Create `frontend/.env.local`:

```
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
GROQ_API_KEY=your_key
MODAL_TRIGGER_URL=https://your-workspace--lifeos-agents-trigger-tick.modal.run
```

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000** — add a goal, share an update, hit "Check in now."

---

## What makes this different

- **Companions, not dashboards.** You don't check a dashboard. They come to you.
- **They coordinate.** Multiple agents concerned? You get ONE message, not five notifications.
- **Silence is a feature.** If everything's fine, you hear nothing. That's intentional.
- **Cross-domain awareness.** Your fitness companion knows your sleep companion is worried. Agents read each other's states.
- **Content, not just reminders.** When a companion nudges you, it includes a relevant article, podcast, or tool — something you can actually act on.
- **Dedup built in.** No spam. Max one intervention per 6 hours per user. Win celebrations bypass this (because good news should always get through).

---

## API docs

Full OpenAPI 3.0 spec at `docs/openapi.yaml`. Paste it into [editor.swagger.io](https://editor.swagger.io) or import to [SwaggerHub](https://app.swaggerhub.com).

| Method | Endpoint              | What it does                                         |
| ------ | --------------------- | ---------------------------------------------------- |
| GET    | `/api/goals`          | List all goals                                       |
| POST   | `/api/goals`          | Create goal (LLM auto-classifies from plain English) |
| GET    | `/api/logs`           | Recent activity logs                                 |
| POST   | `/api/logs`           | Log an update (auto-matched to goal)                 |
| GET    | `/api/agent-messages` | Companion messages                                   |
| GET    | `/api/agent-states`   | What each companion is currently thinking            |
| POST   | `/api/trigger-tick`   | Manually run all agents + coordinator                |

---

Built at a hackathon. The idea: what if your goals had friends that actually talked to each other?
