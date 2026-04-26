-- Add a nullable producer_id column to soniq_jobs.
--
-- Producer-side observability: each row carries a small string the producer
-- stamped at enqueue time so an oncall can answer 'who enqueued this poison
-- message?' from the dashboard without grepping logs across services.
--
-- The column is NULLABLE on purpose. Pre-migration rows have no producer_id
-- and that is expected; the dashboard / soniq tasks CLI must render NULL
-- gracefully (display as 'unknown' or '-', never as a Python None repr or
-- an empty string that looks like a UI glitch).
--
-- Forward-only migration. Reverting requires dropping the column manually.

ALTER TABLE soniq_jobs ADD COLUMN IF NOT EXISTS producer_id TEXT;
