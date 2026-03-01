-- Dynamic agent columns: LLM-generated name, personality, priority per goal.
ALTER TABLE goals ADD COLUMN IF NOT EXISTS agent_name text NOT NULL DEFAULT 'Goal';
ALTER TABLE goals ADD COLUMN IF NOT EXISTS personality text NOT NULL DEFAULT 'warm';
ALTER TABLE goals ADD COLUMN IF NOT EXISTS priority text NOT NULL DEFAULT 'normal';
