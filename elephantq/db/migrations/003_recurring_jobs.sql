-- Migration 003: Recurring jobs persistence

CREATE TABLE IF NOT EXISTS elephantq_recurring_jobs (
  id UUID PRIMARY KEY,
  job_name TEXT NOT NULL,
  schedule_type TEXT NOT NULL CHECK (schedule_type IN ('interval', 'cron')),
  schedule_value TEXT NOT NULL,
  priority INT NOT NULL DEFAULT 100,
  queue TEXT NOT NULL DEFAULT 'default',
  max_attempts INT NOT NULL DEFAULT 3,
  job_kwargs JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
  created_at TIMESTAMP DEFAULT NOW(),
  last_run TIMESTAMP,
  next_run TIMESTAMP,
  run_count INT NOT NULL DEFAULT 0,
  last_job_id UUID,
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_elephantq_recurring_jobs_status
ON elephantq_recurring_jobs (status);

CREATE INDEX IF NOT EXISTS idx_elephantq_recurring_jobs_next_run
ON elephantq_recurring_jobs (next_run);
