-- Normalize all timestamp columns to TIMESTAMP WITH TIME ZONE.
-- Existing data is interpreted as UTC (enforced by application code).
-- This migration is idempotent: columns already using TIMESTAMPTZ are unchanged.

ALTER TABLE elephantq_jobs
  ALTER COLUMN scheduled_at TYPE TIMESTAMP WITH TIME ZONE USING scheduled_at AT TIME ZONE 'UTC',
  ALTER COLUMN expires_at TYPE TIMESTAMP WITH TIME ZONE USING expires_at AT TIME ZONE 'UTC',
  ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC',
  ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING updated_at AT TIME ZONE 'UTC';

ALTER TABLE elephantq_workers
  ALTER COLUMN last_heartbeat TYPE TIMESTAMP WITH TIME ZONE USING last_heartbeat AT TIME ZONE 'UTC',
  ALTER COLUMN started_at TYPE TIMESTAMP WITH TIME ZONE USING started_at AT TIME ZONE 'UTC';

ALTER TABLE elephantq_recurring_jobs
  ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC',
  ALTER COLUMN last_run TYPE TIMESTAMP WITH TIME ZONE USING last_run AT TIME ZONE 'UTC',
  ALTER COLUMN next_run TYPE TIMESTAMP WITH TIME ZONE USING next_run AT TIME ZONE 'UTC',
  ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING updated_at AT TIME ZONE 'UTC';

ALTER TABLE elephantq_job_dependencies
  ALTER COLUMN timeout_at TYPE TIMESTAMP WITH TIME ZONE USING timeout_at AT TIME ZONE 'UTC',
  ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC';

ALTER TABLE elephantq_job_timeouts
  ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC',
  ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING updated_at AT TIME ZONE 'UTC';

ALTER TABLE elephantq_config
  ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING updated_at AT TIME ZONE 'UTC';
