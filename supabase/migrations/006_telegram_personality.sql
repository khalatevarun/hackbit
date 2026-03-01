-- User's chosen chat personality: roasting | playful | gentle (affects all bot message tone).
ALTER TABLE telegram_user_mapping
  ADD COLUMN IF NOT EXISTS personality text NOT NULL DEFAULT 'gentle';
