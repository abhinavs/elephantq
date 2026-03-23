-- ElephantQ initial schema
-- Creates all tables and indexes for the job queue system.

-- Core jobs table
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
  scheduled_at TIMESTAMP,
  expires_at TIMESTAMP,
  last_error TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  worker_id UUID
);

-- Worker heartbeat table
CREATE TABLE IF NOT EXISTS elephantq_workers (
  id UUID PRIMARY KEY,
  hostname TEXT NOT NULL,
  pid INTEGER NOT NULL,
  queues TEXT[] DEFAULT '{}',
  concurrency INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'stopping', 'stopped')),
  last_heartbeat TIMESTAMP NOT NULL DEFAULT NOW(),
  started_at TIMESTAMP NOT NULL DEFAULT NOW(),
  version TEXT,
  metadata JSONB DEFAULT '{}'
);

-- Foreign key from jobs to workers (SET NULL on delete to avoid orphan errors)
ALTER TABLE elephantq_jobs
  ADD CONSTRAINT elephantq_jobs_worker_id_fkey
  FOREIGN KEY (worker_id) REFERENCES elephantq_workers(id) ON DELETE SET NULL;

-- Recurring jobs table
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

-- Job dependencies table
CREATE TABLE IF NOT EXISTS elephantq_job_dependencies (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES elephantq_jobs(id) ON DELETE CASCADE,
  depends_on_job_id UUID NOT NULL,
  dependency_status VARCHAR(20) DEFAULT 'pending',
  timeout_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(job_id, depends_on_job_id)
);

---
--- Indexes
---

-- Jobs: status + priority partial index for queued job selection
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_status_priority
  ON elephantq_jobs (status, priority) WHERE status = 'queued';

-- Jobs: queue + status for queue-specific queries
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_queue_status
  ON elephantq_jobs (queue, status);

-- Jobs: composite index covering the worker's hot fetch query
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_queue_status_priority
  ON elephantq_jobs (queue, status, priority, scheduled_at) WHERE status = 'queued';

-- Jobs: scheduled_at for timed job selection
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_scheduled_at
  ON elephantq_jobs (scheduled_at) WHERE scheduled_at IS NOT NULL;

-- Jobs: expiry for cleanup
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_expires_at
  ON elephantq_jobs (expires_at) WHERE expires_at IS NOT NULL;

-- Jobs: unique job deduplication
CREATE UNIQUE INDEX IF NOT EXISTS idx_elephantq_jobs_unique_queued
  ON elephantq_jobs (job_name, args_hash) WHERE status = 'queued' AND unique_job = TRUE;
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_args_hash
  ON elephantq_jobs (args_hash) WHERE unique_job = TRUE;

-- Jobs: worker tracking
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_worker_id
  ON elephantq_jobs (worker_id) WHERE worker_id IS NOT NULL;

-- Workers: heartbeat and status
CREATE INDEX IF NOT EXISTS idx_elephantq_workers_last_heartbeat
  ON elephantq_workers (last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_elephantq_workers_status
  ON elephantq_workers (status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_elephantq_workers_host_pid
  ON elephantq_workers (hostname, pid);

-- Recurring jobs: scheduling
CREATE INDEX IF NOT EXISTS idx_elephantq_recurring_jobs_status
  ON elephantq_recurring_jobs (status);
CREATE INDEX IF NOT EXISTS idx_elephantq_recurring_jobs_next_run
  ON elephantq_recurring_jobs (next_run);

-- Dependencies: lookup indexes
CREATE INDEX IF NOT EXISTS idx_elephantq_job_deps_job_id
  ON elephantq_job_dependencies (job_id);
CREATE INDEX IF NOT EXISTS idx_elephantq_job_deps_depends_on
  ON elephantq_job_dependencies (depends_on_job_id);
