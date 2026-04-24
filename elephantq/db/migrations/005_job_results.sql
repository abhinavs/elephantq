-- Job return values. The README advertises "store and retrieve return values from
-- completed jobs" but prior to this migration the jobs table had no column to
-- hold them. Added as a nullable JSONB column so existing rows upgrade in place.

ALTER TABLE elephantq_jobs
  ADD COLUMN IF NOT EXISTS result JSONB;
