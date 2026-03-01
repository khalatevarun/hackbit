-- Map Telegram chat_id to internal user_id for multi-user bot support.
-- One row per Telegram chat; each chat gets a dedicated UUID used in goals, user_logs, etc.

create table telegram_user_mapping (
  telegram_chat_id text primary key,
  user_id uuid not null unique default uuid_generate_v4(),
  created_at timestamptz not null default now()
);

create unique index idx_telegram_user_mapping_user_id on telegram_user_mapping (user_id);
