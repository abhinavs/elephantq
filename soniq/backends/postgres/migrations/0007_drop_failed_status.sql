-- Drop 'failed' from soniq_jobs.status; reconcile pre-existing rows.
--
-- Per docs/contracts/job_lifecycle.md the only live row states are
-- queued, processing, done, cancelled. Failures either re-queue
-- (status flips back to queued) or move into soniq_dead_letter_jobs.
-- 'failed' as a row state has no place in the new lifecycle.
--
-- This migration is one-way (alpha; no downgrade). It runs inside the
-- migration runner's transaction, so the rebuilt CHECK applies
-- atomically with the row reconciliation.

-- 1. Reconcile pre-existing 'failed' rows: re-queue them so they keep a
--    chance of being processed. The CHECK rebuilt below would reject
--    them otherwise, and silently dropping rows would lose work.
UPDATE soniq_jobs
SET status = 'queued',
    worker_id = NULL,
    updated_at = NOW(),
    scheduled_at = NOW()
WHERE status = 'failed';

-- 2. Schema tightening: drop the previous CHECK and the redundant
--    no_dead_letter guard added by 0002, replace with a single
--    constraint pinning the four live row states. DROP IF EXISTS keeps
--    re-runs idempotent.
ALTER TABLE soniq_jobs DROP CONSTRAINT IF EXISTS soniq_jobs_status_check;
ALTER TABLE soniq_jobs DROP CONSTRAINT IF EXISTS soniq_jobs_status_no_dead_letter;
ALTER TABLE soniq_jobs ADD CONSTRAINT soniq_jobs_status_check
  CHECK (status IN ('queued', 'processing', 'done', 'cancelled'));
