-- Core jobs table and indexes.
-- This is the heart of ElephantQ — every other table relates back to this one.

CREATE TABLE IF NOT EXISTS elephantq_jobs (
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
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Partial index for the worker's queued-job fetch (status + priority)
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_status_priority
  ON elephantq_jobs (status, priority) WHERE status = 'queued';

-- Queue + status for queue-scoped queries
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_queue_status
  ON elephantq_jobs (queue, status);

-- Composite index covering the worker's hot fetch query:
-- WHERE queue = $1 AND status = 'queued' ORDER BY priority, scheduled_at
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_queue_status_priority
  ON elephantq_jobs (queue, status, priority, scheduled_at) WHERE status = 'queued';

-- Scheduled-at for timed job selection
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_scheduled_at
  ON elephantq_jobs (scheduled_at) WHERE scheduled_at IS NOT NULL;

-- Expiry for TTL cleanup
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_expires_at
  ON elephantq_jobs (expires_at) WHERE expires_at IS NOT NULL;

-- Unique job deduplication (only while queued, so completed jobs can be re-queued)
CREATE UNIQUE INDEX IF NOT EXISTS idx_elephantq_jobs_unique_queued
  ON elephantq_jobs (job_name, args_hash) WHERE status = 'queued' AND unique_job = TRUE;
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_args_hash
  ON elephantq_jobs (args_hash) WHERE unique_job = TRUE;

-- Dedup key (only one job per key while queued)
CREATE UNIQUE INDEX IF NOT EXISTS idx_elephantq_jobs_dedup_key
  ON elephantq_jobs (dedup_key) WHERE status = 'queued' AND dedup_key IS NOT NULL;
