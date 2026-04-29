# Changelog

All notable changes to Soniq are documented in this file.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.3] - unreleased

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
- Pluggable extension points: `RetryPolicy` and `MetricsSink`. Each ships a default and a `Soniq(...)` constructor parameter. `PrometheusMetricsSink` (importable from a plain `pip install soniq` - `prometheus_client` is a default dependency) emits `soniq_jobs_started_total`, `soniq_jobs_completed_total`, `soniq_job_duration_seconds`, and `soniq_jobs_in_progress` against a configurable registry / prefix.

### Cross-service enqueue

- `app.enqueue` accepts three input shapes selected by the type of the first argument:
  - **Callable** (single-repo): `app.enqueue(my_func, x=1)`.
  - **String task name** (cross-service / by-name):
    `app.enqueue("users.task", args={"x": 1})`. The producer does
    not need to import the consumer's handler.
  - **`TaskRef`** (typed cross-repo stub):
    `app.enqueue(my_ref, args={"x": 1})`. Validates `args` against
    the ref's `args_model` and uses its `default_queue` when no
    explicit `queue=` is passed.
- `@app.job(name=...)` for stable wire-protocol identifiers. When
  omitted the task name is derived from `f"{module}.{qualname}"`
  (matching Celery / Dramatiq / RQ). Cross-service deployments should
  pass `name=` explicitly; explicit names are validated against
  `SONIQ_TASK_NAME_PATTERN`.
- `SONIQ_ENQUEUE_VALIDATION` setting (`"strict"` / `"warn"` /
  `"none"`). Governs how `enqueue("string-name", ...)` handles a name
  not registered locally. Default `"strict"` raises
  `SONIQ_UNKNOWN_TASK_NAME`. `"warn"` emits a rate-limited
  per-process warning.
- `SONIQ_TASK_NAME_PATTERN` setting. Default rejects whitespace,
  uppercase, and leading/trailing dots. Validates explicit `name=`
  values at registration and string targets at enqueue time.
- Error codes: `SONIQ_UNKNOWN_TASK_NAME`, `SONIQ_INVALID_TASK_NAME`,
  `SONIQ_TASK_ARGS_INVALID`.

### Contracts

- `soniq.types.QueueStats` is the canonical 6-key shape returned by
  every backend's `queue_stats()` and surfaced in CLI / dashboard:
  `{total, queued, processing, done, dead_letter, cancelled}`. No
  aliases, no extra keys.
- DLQ is a table-of-record under `soniq_dead_letter_jobs`. The runtime
  is the only path that creates DLQ rows; there is no public
  `move(job_id)` helper. List, replay, and purge operations remain on
  `DeadLetterService`.
- Bounded sync handler thread pool: `sync_handler_pool_size` (default
  `8`) caps concurrent sync handler threads per `Soniq` instance, with
  a post-claim `asyncio.Semaphore` so claimed `processing` rows can
  never exceed worker concurrency. Async handlers bypass the pool
  entirely.
- `shutdown_timeout` (default `30s`) and `sync_handler_grace_seconds`
  settings drive the `RUNNING -> DRAINING -> FORCE_TIMEOUT_PATH`
  shutdown state machine. Async jobs nack on force-timeout; sync jobs
  receive an extra grace window before the executor is torn down.
- Two-instance isolation: no module-level `get_settings()` calls
  outside the constructor allowlist, validated by
  `check_no_global_settings.py` (pre-commit + CI) and the
  cross-instance bleed integration test.

### Operational notes

- `SONIQ_DATABASE_URL` is the primary configuration input. Every other setting (`SONIQ_CONCURRENCY`, `SONIQ_POOL_MAX_SIZE`, feature flags) has a sensible default.
- Baseline database schema is applied by the core migration set on first run of `soniq setup`. All tables are namespaced `soniq_*`.
- LISTEN/NOTIFY channel is `soniq_new_job`. Advisory-lock namespaces are `soniq.maintenance` (worker cleanup) and `soniq.migrations` (migration runner).
- Default SQLite backend filename is `soniq.db`.
- Connection pool sizing is validated at worker startup: `SONIQ_POOL_MAX_SIZE` must be at least `SONIQ_CONCURRENCY + SONIQ_POOL_HEADROOM`; the worker refuses to start otherwise.

### Breaking

- `app.enqueue(...)` with `unique=True` or `dedup_key=...` now always
  returns the canonical row id. The old code path could return a
  synthetic id when the dedup row transitioned mid-flight; the
  single-statement `INSERT ... ON CONFLICT DO UPDATE` rewrite removes
  that fallback. Callers that compared returned ids against
  `synthetic-*` strings need to drop that branch.
- DLQ rows are written by the runtime only. There is no public
  `DeadLetterService.move(job_id)` helper; manual DLQ insertion was
  never a documented operation and is removed.
- Packaging is batteries-included for runtime. `croniter` and
  `prometheus_client` are now default dependencies of `soniq` (so
  `@periodic` and `PrometheusMetricsSink` work from a plain
  `pip install soniq`). The `soniq[scheduling]` and `soniq[monitoring]`
  extras are removed - operators with those in their requirements files
  must drop the markers (the bare `pip install soniq` covers both).
  `psutil` is no longer a dependency of any extra (it was only used by
  the deleted `soniq.features.metrics` module). The `dashboard`,
  `sqlite`, `webhooks`, and `logging` extras are unchanged.

### Fixed

- `soniq setup` against a missing Postgres database now creates the
  database before initializing the connection pool, instead of failing
  at pool init.
- Dashboard DLQ semantics: `get_job_stats`, `get_queue_stats`,
  `get_job_timeline`, `get_system_health`, and `get_task_registry_drift`
  read DLQ counts from `soniq_dead_letter_jobs` rather than the
  legacy `status='dead_letter'` filter on `soniq_jobs`. Retry from the
  dashboard resurrects the DLQ row in a single transaction.

### Changed

- All soniq-owned tables (`soniq_jobs`, `soniq_dead_letter_jobs`,
  `soniq_scheduled_jobs`, `soniq_webhook_*`, `soniq_logs`) are created
  unconditionally by the core migration set. The `--features` flag and
  per-feature setup gating are gone; tables for features the operator
  doesn't use are empty but present.
- Every CLI subcommand (`setup`, `start`, `status`, `workers`,
  `dashboard`, `dead-letter`, `scheduler`, `migrate-status`, `tasks`)
  routes through a single `--database-url` resolution helper. No
  subcommand reaches for a process-global Soniq.
- Two-instance isolation is now a tested contract: per-instance
  settings, registries, and backends. The `check_no_global_settings.py`
  pre-commit hook + the cross-instance bleed integration test pin it.

### Removed

- The process-global Soniq convenience surface is gone. There is no
  module-level `soniq.job`, `soniq.enqueue`, `soniq.run_worker`,
  `soniq.configure`, `soniq.get_global_app`, `soniq.schedule`, or any
  other top-level helper that operated on a hidden global app. All
  public APIs hang off a `Soniq` instance: construct one
  (`app = Soniq(database_url=...)`), decorate with `@app.job(...)` /
  `@app.periodic(...)`, and call `await app.enqueue(...)` /
  `await app.run_worker(...)`. The CLI builds its own `Soniq` instance
  per subcommand from `SONIQ_DATABASE_URL` and discovered job modules;
  there is no shared state between processes. Logging configuration is
  the only state that is still process-global.
- The `soniq tasks-list` CLI subcommand is removed. With per-instance
  registries it had no well-defined notion of "all tasks" outside a
  running app. Use `app.list_jobs(...)` against an instance instead.
- The `serializer=` constructor knob (and the matching `app.serializer`
  property) is removed. It was stored on the instance but no code path
  read it, so custom values were silently ignored. The `Serializer`
  Protocol and `JSONSerializer` helper (`soniq.utils.serialization`)
  are removed alongside it. Job arguments and results continue to be
  JSON-encoded end-to-end against JSONB / JSON-text columns. The
  `log_sink=` constructor parameter and the `LogSink` Protocol in
  `soniq.features.logging` are removed for the same reason: they were
  publicly documented, but no runtime path read `_log_sink`. Apps that
  need custom log routing should configure stdlib `logging` directly
  (the same handlers worked before; the knob just never plumbed them
  anywhere).
- The `soniq.features.metrics` module is removed, along with the
  `soniq metrics` CLI subcommand. The in-memory `MetricsCollector` /
  `MetricsAnalyzer` / `AlertManager` / `MetricsService` stack was an
  analytics-on-historical-state layer that overlapped the
  runtime-events-out `MetricsSink` seam in `soniq.observability`. There
  is now exactly one metrics surface: implement
  `soniq.observability.MetricsSink` (or use the bundled
  `PrometheusMetricsSink`, importable from a plain `pip install soniq`
  since `prometheus_client` is a default dependency) and
  pass it as `Soniq(metrics_sink=...)`. Dashboards that need historical
  rollups should query the `soniq_*` tables directly or scrape the
  Prometheus sink.

### Known limitations

- Sync handler hard-kill on shutdown can re-deliver a job whose handler
  was mid-flight when the executor was forced down. There is no
  exactly-once guarantee for sync handlers under
  `shutdown_timeout`-triggered force-paths; design handlers to be
  idempotent.

### Recurring jobs need a scheduler sidecar

`soniq start` runs the worker only. If you use `@app.periodic(...)` jobs, deploy a separate `soniq scheduler` process. The worker prints a one-time WARN at startup if it detects `@periodic` decorators and no scheduler is configured. Suppress with `SONIQ_SCHEDULER_SUPPRESS_WARNING=1`.

The shipped deployment templates (systemd, Docker Compose, Kubernetes, Supervisor) all include the sidecar; see `docs/production/deployment.md`.
