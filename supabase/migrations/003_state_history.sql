-- Add state_history JSONB column to agent_states for pattern detection.
-- Each agent run appends {next_action, confidence, updated_at} (last 7 kept).
ALTER TABLE agent_states
  ADD COLUMN IF NOT EXISTS state_history jsonb NOT NULL DEFAULT '[]'::jsonb;
