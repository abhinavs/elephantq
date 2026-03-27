-- Scheduling infrastructure: recurring jobs and timeouts.

-- Recurring jobs (cron and interval schedules)
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
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  last_run TIMESTAMP WITH TIME ZONE,
  next_run TIMESTAMP WITH TIME ZONE,
  run_count INT NOT NULL DEFAULT 0,
  last_job_id UUID,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_elephantq_recurring_jobs_status
  ON elephantq_recurring_jobs (status);
CREATE INDEX IF NOT EXISTS idx_elephantq_recurring_jobs_next_run
  ON elephantq_recurring_jobs (next_run);

-- Per-job timeout configuration
CREATE TABLE IF NOT EXISTS elephantq_job_timeouts (
  job_id UUID PRIMARY KEY REFERENCES elephantq_jobs(id) ON DELETE CASCADE,
  timeout_seconds INTEGER NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Global configuration store (used by timeout processor and other features)
CREATE TABLE IF NOT EXISTS elephantq_config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
