create extension if not exists "uuid-ossp";

create table goals (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null,
  name text not null,
  type text not null check (type in ('habit', 'target', 'short_lived')),
  agent_template text not null check (agent_template in ('fitness', 'sleep', 'money', 'social', 'custom', 'short_lived')),
  config jsonb not null default '{}',
  active boolean not null default true,
  end_at timestamptz,
  created_at timestamptz not null default now()
);

create index idx_goals_user_active on goals (user_id, active);

create table user_logs (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null,
  goal_id uuid references goals(id) on delete set null,
  content text not null,
  source text not null default 'manual_input' check (source in ('manual_input', 'agent_checkin', 'voice_note')),
  processed boolean not null default false,
  created_at timestamptz not null default now()
);

create index idx_user_logs_user on user_logs (user_id, created_at desc);
create index idx_user_logs_goal on user_logs (goal_id, created_at desc);

create table agent_states (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null,
  goal_id uuid not null references goals(id) on delete cascade,
  state jsonb not null default '{}',
  updated_at timestamptz not null default now(),
  unique (user_id, goal_id)
);

create index idx_agent_states_user on agent_states (user_id);

create table interventions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null,
  goal_id uuid references goals(id) on delete set null,
  triggered_by text[] not null default '{}',
  intervention_type text not null check (intervention_type in ('nudge', 'call', 'text', 'escalate')),
  reason text not null,
  scheduled_for timestamptz not null,
  executed boolean not null default false,
  outcome text,
  created_at timestamptz not null default now()
);

create index idx_interventions_user on interventions (user_id, created_at desc);

create table agent_messages (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null,
  goal_id uuid references goals(id) on delete set null,
  from_agent text not null,
  to_agent text,
  message text not null,
  context jsonb,
  created_at timestamptz not null default now()
);

create index idx_agent_messages_user on agent_messages (user_id, created_at desc);
