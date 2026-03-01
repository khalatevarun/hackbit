-- Add structured tracking columns to user_logs.
-- value: extracted numeric value from the log ("did 12 problems" → 12.0)
-- logged_date: the calendar date this log represents (for streak/frequency computation)
ALTER TABLE user_logs ADD COLUMN IF NOT EXISTS value numeric;
ALTER TABLE user_logs ADD COLUMN IF NOT EXISTS logged_date date NOT NULL DEFAULT CURRENT_DATE;

CREATE INDEX IF NOT EXISTS idx_user_logs_goal_date ON user_logs (goal_id, logged_date DESC);
