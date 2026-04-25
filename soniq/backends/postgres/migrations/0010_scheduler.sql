-- Scheduler feature: recurring jobs.
--
-- Applied by Scheduler.setup() (or `soniq setup --features=scheduler`).
-- A deployment that doesn't use the scheduler never creates this table.

CREATE TABLE IF NOT EXISTS soniq_recurring_jobs (
  id UUID PRIMARY KEY,
  job_name TEXT NOT NULL,
  schedule_type TEXT NOT NULL CHECK (schedule_type IN ('interval', 'cron')),
  schedule_value TEXT NOT NULL,
  priority INT NOT NULL DEFAULT 100,
  queue TEXT NOT NULL DEFAULT 'default',
  max_attempts INT NOT NULL DEFAULT 3,
  job_kwargs JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  last_run TIMESTAMP WITH TIME ZONE,
  next_run TIMESTAMP WITH TIME ZONE,
  run_count INT NOT NULL DEFAULT 0,
  last_job_id UUID,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_soniq_recurring_jobs_status
  ON soniq_recurring_jobs (status);
CREATE INDEX IF NOT EXISTS idx_soniq_recurring_jobs_next_run
  ON soniq_recurring_jobs (next_run);
