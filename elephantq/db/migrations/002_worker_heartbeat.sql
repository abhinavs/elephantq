-- Migration 002: Worker Heartbeat System
-- Adds worker tracking and heartbeat functionality for production monitoring

CREATE TABLE IF NOT EXISTS elephantq_workers (
  id UUID PRIMARY KEY,
  hostname TEXT NOT NULL,
  pid INTEGER NOT NULL,
  queues TEXT[] DEFAULT '{}',  -- Array of queue names this worker processes
  concurrency INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'stopping', 'stopped')),
  last_heartbeat TIMESTAMP NOT NULL DEFAULT NOW(),
  started_at TIMESTAMP NOT NULL DEFAULT NOW(),
  version TEXT,
  metadata JSONB DEFAULT '{}'  -- Additional worker metadata (OS, CPU, memory, etc.)
);

-- Index for efficient heartbeat queries
CREATE INDEX IF NOT EXISTS idx_elephantq_workers_last_heartbeat ON elephantq_workers (last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_elephantq_workers_status ON elephantq_workers (status);

-- Unique constraint to prevent duplicate workers from same host/pid
CREATE UNIQUE INDEX IF NOT EXISTS idx_elephantq_workers_host_pid ON elephantq_workers (hostname, pid);

-- Add worker_id column to jobs table to track which worker processed the job
ALTER TABLE elephantq_jobs ADD COLUMN IF NOT EXISTS worker_id UUID REFERENCES elephantq_workers(id);

-- Index for worker job tracking
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_worker_id ON elephantq_jobs (worker_id) WHERE worker_id IS NOT NULL;