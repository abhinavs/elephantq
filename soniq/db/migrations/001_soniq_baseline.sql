-- Baseline schema for soniq. Single consolidated migration; no pre-existing
-- migrations carry over.

-- ---------------------------------------------------------------------------
-- Core jobs
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS soniq_jobs (
  id UUID PRIMARY KEY,
  job_name TEXT NOT NULL,
  args JSONB NOT NULL,
  args_hash TEXT,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'processing', 'done', 'failed', 'dead_letter', 'cancelled')),
  attempts INT DEFAULT 0,
  max_attempts INT DEFAULT 3,
  queue TEXT DEFAULT 'default',
  priority INT DEFAULT 100,
  unique_job BOOLEAN DEFAULT FALSE,
  dedup_key TEXT,
  scheduled_at TIMESTAMP WITH TIME ZONE,
  expires_at TIMESTAMP WITH TIME ZONE,
  last_error TEXT,
  result JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_soniq_jobs_status_priority
  ON soniq_jobs (status, priority) WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS idx_soniq_jobs_queue_status
  ON soniq_jobs (queue, status);

-- Covers the worker's hot fetch:
-- WHERE queue = $1 AND status = 'queued' ORDER BY priority, scheduled_at
CREATE INDEX IF NOT EXISTS idx_soniq_jobs_queue_status_priority
  ON soniq_jobs (queue, status, priority, scheduled_at) WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS idx_soniq_jobs_scheduled_at
  ON soniq_jobs (scheduled_at) WHERE scheduled_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_soniq_jobs_expires_at
  ON soniq_jobs (expires_at) WHERE expires_at IS NOT NULL;

-- Uniqueness while queued; completed jobs can be re-queued.
CREATE UNIQUE INDEX IF NOT EXISTS idx_soniq_jobs_unique_queued
  ON soniq_jobs (job_name, args_hash) WHERE status = 'queued' AND unique_job = TRUE;
CREATE INDEX IF NOT EXISTS idx_soniq_jobs_args_hash
  ON soniq_jobs (args_hash) WHERE unique_job = TRUE;

-- Dedup key: at most one queued job per key.
CREATE UNIQUE INDEX IF NOT EXISTS idx_soniq_jobs_dedup_key
  ON soniq_jobs (dedup_key) WHERE status = 'queued' AND dedup_key IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Workers
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS soniq_workers (
  id UUID PRIMARY KEY,
  hostname TEXT NOT NULL,
  pid INTEGER NOT NULL,
  queues TEXT[] DEFAULT '{}',
  concurrency INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'stopping', 'stopped')),
  last_heartbeat TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  version TEXT,
  metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_soniq_workers_last_heartbeat
  ON soniq_workers (last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_soniq_workers_status
  ON soniq_workers (status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_soniq_workers_host_pid
  ON soniq_workers (hostname, pid);

ALTER TABLE soniq_jobs
  ADD COLUMN IF NOT EXISTS worker_id UUID;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'soniq_jobs_worker_id_fkey'
  ) THEN
    ALTER TABLE soniq_jobs
      ADD CONSTRAINT soniq_jobs_worker_id_fkey
      FOREIGN KEY (worker_id) REFERENCES soniq_workers(id) ON DELETE SET NULL;
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_soniq_jobs_worker_id
  ON soniq_jobs (worker_id) WHERE worker_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Scheduling (recurring jobs, per-job timeouts, config)
-- ---------------------------------------------------------------------------

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

CREATE TABLE IF NOT EXISTS soniq_job_timeouts (
  job_id UUID PRIMARY KEY REFERENCES soniq_jobs(id) ON DELETE CASCADE,
  timeout_seconds INTEGER NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS soniq_config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Optional features: dead-letter queue, webhooks, structured logging
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS soniq_dead_letter_jobs (
  id UUID PRIMARY KEY,
  job_name TEXT NOT NULL,
  args JSONB NOT NULL,
  queue TEXT NOT NULL,
  priority INTEGER NOT NULL,
  max_attempts INTEGER NOT NULL,
  attempts INTEGER NOT NULL,
  last_error TEXT,
  dead_letter_reason TEXT NOT NULL,
  original_created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  moved_to_dead_letter_at TIMESTAMP WITH TIME ZONE NOT NULL,
  resurrection_count INTEGER DEFAULT 0,
  last_resurrection_at TIMESTAMP WITH TIME ZONE,
  tags JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_soniq_dead_letter_jobs_job_name
  ON soniq_dead_letter_jobs (job_name);
CREATE INDEX IF NOT EXISTS idx_soniq_dead_letter_jobs_queue
  ON soniq_dead_letter_jobs (queue);
CREATE INDEX IF NOT EXISTS idx_soniq_dead_letter_jobs_reason
  ON soniq_dead_letter_jobs (dead_letter_reason);
CREATE INDEX IF NOT EXISTS idx_soniq_dead_letter_jobs_moved_at
  ON soniq_dead_letter_jobs (moved_to_dead_letter_at);

CREATE TABLE IF NOT EXISTS soniq_webhook_endpoints (
  id TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  secret TEXT,
  events JSONB,
  active BOOLEAN DEFAULT true,
  max_retries INTEGER DEFAULT 3,
  timeout_seconds INTEGER DEFAULT 30,
  headers JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS soniq_webhook_deliveries (
  id TEXT PRIMARY KEY,
  endpoint_id TEXT NOT NULL REFERENCES soniq_webhook_endpoints(id) ON DELETE CASCADE,
  event TEXT NOT NULL,
  payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER DEFAULT 0,
  max_attempts INTEGER DEFAULT 3,
  next_retry_at TIMESTAMP WITH TIME ZONE,
  last_error TEXT,
  response_status INTEGER,
  response_body TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  delivered_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_soniq_webhook_deliveries_status
  ON soniq_webhook_deliveries (status);
CREATE INDEX IF NOT EXISTS idx_soniq_webhook_deliveries_next_retry
  ON soniq_webhook_deliveries (next_retry_at);
CREATE INDEX IF NOT EXISTS idx_soniq_webhook_deliveries_endpoint
  ON soniq_webhook_deliveries (endpoint_id);

CREATE TABLE IF NOT EXISTS soniq_logs (
  id SERIAL PRIMARY KEY,
  timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
  level TEXT NOT NULL,
  message TEXT NOT NULL,
  logger_name TEXT NOT NULL,
  module TEXT,
  function TEXT,
  line_number INTEGER,
  request_id TEXT,
  job_id TEXT,
  job_name TEXT,
  queue TEXT,
  extra_data JSONB,
  exception_data JSONB,
  performance_data JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_soniq_logs_timestamp
  ON soniq_logs (timestamp);
CREATE INDEX IF NOT EXISTS idx_soniq_logs_job_id
  ON soniq_logs (job_id);
CREATE INDEX IF NOT EXISTS idx_soniq_logs_level
  ON soniq_logs (level);
CREATE INDEX IF NOT EXISTS idx_soniq_logs_request_id
  ON soniq_logs (request_id);
