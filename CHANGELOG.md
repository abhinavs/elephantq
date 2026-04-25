# Changelog

All notable changes to Soniq are documented in this file.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.2] - unreleased

First public release.

### Highlights

- PostgreSQL-backed async job queue with `asyncpg`. Also ships a SQLite backend for local dev and an in-memory backend for tests.
- Transactional enqueue: pass an existing `asyncpg` connection to `app.enqueue(...)` and the job is inserted inside your own transaction. Commits or rolls back with your data.
- Recurring jobs via `@app.periodic(cron="...")` or `@app.periodic(every_minutes=N)`. **Requires a separate `soniq scheduler` process** alongside `soniq start`; the worker alone does not fire periodic jobs.
- Job results: return values from completed jobs are persisted and retrievable via `await app.get_result(job_id)`.
- Dead-letter queue, per-job timeouts, deduplication (`unique=True` and `dedup_key`), priorities, and multiple queues.
- Graceful shutdown with worker heartbeat + stale-worker sweep.
- CLI: `soniq setup`, `soniq start`, `soniq scheduler`, `soniq dashboard`, `soniq status`, `soniq workers`, dead-letter management.
- Optional web dashboard (`soniq dashboard`), behind a feature flag.
- Structured logging, webhook delivery, and metrics behind optional extras.

### Operational notes

- `SONIQ_DATABASE_URL` is the primary configuration input. Every other setting (`SONIQ_CONCURRENCY`, `SONIQ_POOL_MAX_SIZE`, feature flags) has a sensible default.
- Baseline database schema is applied by the single migration `001_soniq_baseline.sql` on first run of `soniq setup`. All tables are namespaced `soniq_*`.
- LISTEN/NOTIFY channel is `soniq_new_job`. Advisory-lock namespaces are `soniq.maintenance` (worker cleanup) and `soniq.migrations` (migration runner).
- Default SQLite backend filename is `soniq.db`.
- Connection pool sizing is validated at worker startup: `SONIQ_POOL_MAX_SIZE` must be at least `SONIQ_CONCURRENCY + SONIQ_POOL_HEADROOM`; the worker refuses to start otherwise.
