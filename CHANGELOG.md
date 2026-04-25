# Changelog

All notable changes to Soniq are documented in this file.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Breaking changes

- **`Soniq.enqueue` shape replaced.** `app.enqueue(my_func, x=1)` is
  removed; use `app.enqueue("task.name", args={"x": 1})`. Function
  args travel as an explicit `args=` dict; enqueue options
  (`queue`, `priority`, `scheduled_at`, `unique`, `dedup_key`,
  `connection`) stay at the top level. Module-level
  `soniq.enqueue` follows the same shape.
- **`@app.job(name=...)` is mandatory.** Module-derived names
  (`module.qualname`) are removed. `@app.job()` without `name=` raises
  `SoniqError(SONIQ_INVALID_TASK_NAME)` at decoration time.
  `@app.periodic` derives `name=func.__name__` when you don't pass one.

### Added

- Cross-service enqueue via task names. Service A can enqueue jobs
  service B owns and executes; both share a Postgres database, neither
  imports the other's code.
- `Soniq(producer_only=True)` flag. Refuses `run_worker`, the
  recurring scheduler entry point, and `@app.job` registration;
  allows enqueue, schedule, and the read-only management API.
  Suppresses the recurring-scheduler startup warning.
- `SONIQ_ENQUEUE_VALIDATION` setting (`"strict"` / `"warn"` /
  `"none"`). Governs how `enqueue()` handles a string name not
  registered locally. Default `"strict"` raises
  `SONIQ_UNKNOWN_TASK_NAME`. `"warn"` emits a rate-limited
  per-process warning.
- `SONIQ_TASK_NAME_PATTERN` setting. Default rejects whitespace,
  uppercase, and leading/trailing dots. Validates at registration and
  enqueue time.
- New error codes: `SONIQ_UNKNOWN_TASK_NAME`,
  `SONIQ_INVALID_TASK_NAME`, `SONIQ_TASK_ARGS_INVALID`,
  `SONIQ_PRODUCER_ONLY`.
- `soniq migrate-enqueue` codemod. AST-based rewrite of the old
  shapes to the new ones. Refuses to invent canonical names by
  default; callers supply a `migrate-enqueue.toml` mapping or pass
  `--use-derived-names` for a quick-start fallback.

### Documentation

- New cross-service jobs guide at
  `docs/guides/cross-service-jobs.md`.
- New migration guide at
  `docs/migration/0.0.x-to-cross-service.md`.
- README cross-service section.

### Migration

```bash
soniq migrate-enqueue --use-derived-names .
```

Or supply explicit canonical names in `migrate-enqueue.toml`. See
the migration guide for the full walkthrough.

## [0.0.2] - 2026-04-25

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
- Pluggable extension points: `RetryPolicy`, `Serializer`, `LogSink`, and `MetricsSink`. Each ships a default and a `Soniq(...)` constructor parameter. `PrometheusMetricsSink` (under `pip install soniq[monitoring]`) emits `soniq_jobs_started_total`, `soniq_jobs_completed_total`, `soniq_job_duration_seconds`, and `soniq_jobs_in_progress` against a configurable registry / prefix.

### Operational notes

- `SONIQ_DATABASE_URL` is the primary configuration input. Every other setting (`SONIQ_CONCURRENCY`, `SONIQ_POOL_MAX_SIZE`, feature flags) has a sensible default.
- Baseline database schema is applied by the single migration `001_soniq_baseline.sql` on first run of `soniq setup`. All tables are namespaced `soniq_*`.
- LISTEN/NOTIFY channel is `soniq_new_job`. Advisory-lock namespaces are `soniq.maintenance` (worker cleanup) and `soniq.migrations` (migration runner).
- Default SQLite backend filename is `soniq.db`.
- Connection pool sizing is validated at worker startup: `SONIQ_POOL_MAX_SIZE` must be at least `SONIQ_CONCURRENCY + SONIQ_POOL_HEADROOM`; the worker refuses to start otherwise.

### Recurring jobs need a scheduler sidecar (action required if upgrading from a pre-release)

`soniq start` runs the worker only. If you use `@app.periodic(...)` jobs, deploy a separate `soniq scheduler` process. The worker prints a one-time WARN at startup if it detects `@periodic` decorators and no scheduler is configured. Suppress with `SONIQ_SCHEDULER_SUPPRESS_WARNING=1`.

The shipped deployment templates (systemd, Docker Compose, Kubernetes, Supervisor) all include the sidecar; see `docs/production/deployment.md`.
