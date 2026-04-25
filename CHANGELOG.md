# Changelog

All notable changes to Soniq are documented in this file.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Breaking changes

None for single-repo users. Existing code that uses
`@app.job(...)` and `app.enqueue(my_func, x=1)` keeps working
unchanged.

### Added

- **Cross-service enqueue.** `app.enqueue` now accepts three input
  shapes selected by the type of the first argument:
  - **Callable** (single-repo): `app.enqueue(my_func, x=1)` -
    unchanged from earlier versions.
  - **String task name** (cross-service / by-name):
    `app.enqueue("users.task", args={"x": 1})`. The producer does
    not need to import the consumer's handler.
  - **`TaskRef`** (typed cross-repo stub):
    `app.enqueue(my_ref, args={"x": 1})`. Validates `args` against
    the ref's `args_model` and uses its `default_queue` when no
    explicit `queue=` is passed.
- **`@app.job(name=...)` for stable wire-protocol identifiers.**
  When omitted the task name is derived from
  `f"{module}.{qualname}"` (matching Celery / Dramatiq / RQ).
  Cross-service deployments should pass `name=` explicitly; explicit
  names are validated against `SONIQ_TASK_NAME_PATTERN`.

- `SONIQ_ENQUEUE_VALIDATION` setting (`"strict"` / `"warn"` /
  `"none"`). Governs how `enqueue("string-name", ...)` handles a name
  not registered locally. Default `"strict"` raises
  `SONIQ_UNKNOWN_TASK_NAME`. `"warn"` emits a rate-limited
  per-process warning.
- `SONIQ_TASK_NAME_PATTERN` setting. Default rejects whitespace,
  uppercase, and leading/trailing dots. Validates explicit `name=`
  values at registration and string targets at enqueue time.
- New error codes: `SONIQ_UNKNOWN_TASK_NAME`,
  `SONIQ_INVALID_TASK_NAME`, `SONIQ_TASK_ARGS_INVALID`.
- `soniq migrate-enqueue` codemod for projects that want to switch
  from the callable form to the by-name form (e.g. when carving a
  consumer service out of a monolith). Optional - the callable form
  keeps working.

### Documentation

- New cross-service jobs guide at
  `docs/guides/cross-service-jobs.md`.
- New migration guide at
  `docs/migration/0.0.x-to-cross-service.md`.
- README cross-service section.

### Migration

Most single-repo code does not need to change. The callable form
of `enqueue` keeps working and `@app.job()` continues to derive task
names automatically.

For projects switching to the by-name form (e.g. carving a consumer
service out of a monolith), the codemod handles the rewrite:

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
