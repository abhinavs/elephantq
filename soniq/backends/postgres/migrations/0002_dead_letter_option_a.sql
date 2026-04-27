-- DLQ Option A: destructive cleanup + schema tightening for soniq_jobs.status.
--
-- See docs/contracts/dead_letter.md (truth spec) and
-- docs/design/dlq_option_a.md (engineering notes) for the why and how.
--
-- This migration is one-way (alpha; no downgrade). Operators on 0.0.2
-- installs who care about pre-existing soniq_jobs.status='dead_letter'
-- rows must hand-export them BEFORE upgrading. Running this migration
-- deletes them.

-- 1. Destructive cleanup: drop any pre-existing soniq_jobs rows in
--    status='dead_letter'. With Option A, the soniq_dead_letter_jobs
--    table is the single source of truth; the value is leaving the
--    soniq_jobs.status enum.
DELETE FROM soniq_jobs WHERE status = 'dead_letter';

-- 2. Schema tightening: drop the column-level CHECK from 0001_core.sql
--    and replace it with one that excludes 'dead_letter'. The original
--    CHECK was created inline (no explicit name) but Postgres assigns
--    it the deterministic name 'soniq_jobs_status_check'. DROP IF
--    EXISTS keeps this idempotent on re-run.
ALTER TABLE soniq_jobs DROP CONSTRAINT IF EXISTS soniq_jobs_status_check;
ALTER TABLE soniq_jobs ADD CONSTRAINT soniq_jobs_status_check
  CHECK (status IN ('queued', 'processing', 'done', 'failed', 'cancelled'));

-- 3. Defensive CHECK that re-asserts dead_letter is rejected. Redundant
--    with the rebuilt CHECK above but kept as a named, explicit guard so
--    operators reading pg_constraint see the contract intent directly.
ALTER TABLE soniq_jobs DROP CONSTRAINT IF EXISTS soniq_jobs_status_no_dead_letter;
ALTER TABLE soniq_jobs ADD CONSTRAINT soniq_jobs_status_no_dead_letter
  CHECK (status <> 'dead_letter');
