-- Composite index for the hottest query pattern: queue + status + priority + scheduled_at
-- The worker's _fetch_and_lock_job query filters by queue and status='queued',
-- then orders by priority and scheduled_at. This index covers the full query.
CREATE INDEX IF NOT EXISTS idx_elephantq_jobs_queue_status_priority
ON elephantq_jobs (queue, status, priority, scheduled_at)
WHERE status = 'queued';

-- Job dependencies table (previously created inline in dependencies.py)
CREATE TABLE IF NOT EXISTS elephantq_job_dependencies (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES elephantq_jobs(id) ON DELETE CASCADE,
    depends_on_job_id UUID NOT NULL,
    dependency_status VARCHAR(20) DEFAULT 'pending',
    timeout_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(job_id, depends_on_job_id)
);

CREATE INDEX IF NOT EXISTS idx_elephantq_job_deps_job_id
ON elephantq_job_dependencies (job_id);

CREATE INDEX IF NOT EXISTS idx_elephantq_job_deps_depends_on
ON elephantq_job_dependencies (depends_on_job_id);
