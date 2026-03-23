-- Fix worker_id foreign key to SET NULL on delete.
-- Prevents FK constraint errors if a worker record is manually deleted.
ALTER TABLE elephantq_jobs
    DROP CONSTRAINT IF EXISTS elephantq_jobs_worker_id_fkey;

ALTER TABLE elephantq_jobs
    ADD CONSTRAINT elephantq_jobs_worker_id_fkey
    FOREIGN KEY (worker_id) REFERENCES elephantq_workers(id) ON DELETE SET NULL;
