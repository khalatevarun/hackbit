-- Add delivery tracking to interventions
alter table interventions
  add column if not exists delivered_at timestamptz;
