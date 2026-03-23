-- Worker registration and heartbeat tracking.
-- Workers register on startup, send heartbeats, and stale ones get cleaned up.

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

CREATE INDEX IF NOT EXISTS idx_elephantq_workers_last_heartbeat
  ON elephantq_workers (last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_elephantq_workers_status
  ON elephantq_workers (status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_elephantq_workers_host_pid
  ON elephantq_workers (hostname, pid);

-- Track which worker processed each job (SET NULL if worker record is deleted)
ALTER TABLE elephantq_jobs
  ADD COLUMN IF NOT EXISTS worker_id UUID;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'elephantq_jobs_worker_id_fkey'
  ) THEN
    ALTER TABLE elephantq_jobs
      ADD CONSTRAINT elephantq_jobs_worker_id_fkey
      FOREIGN KEY (worker_id) REFERENCES elephantq_workers(id) ON DELETE SET NULL;
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_worker_id
  ON elephantq_jobs (worker_id) WHERE worker_id IS NOT NULL;
