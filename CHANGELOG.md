# Changelog

All notable changes to ElephantQ will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Breaking Changes
- `StorageBackend` protocol gained a required `reschedule_job(job_id, *, delay_seconds, attempts, reason=None)` method, used by the new `Snooze` return type. All in-tree backends (Postgres, SQLite, Memory) implement it. Any third-party backend must add an implementation; otherwise `isinstance(backend, StorageBackend)` checks fail and handlers that return `Snooze` will raise `AttributeError`.
- Advisory-lock leader election (see below) requires Postgres in session-pooling mode. **Transaction-pooling PgBouncer deployments must either switch to session-pooling or disable the feature** - `pg_try_advisory_lock` releases between statements under transaction-pooling, making the lock unsafe. Single-writer deployments (SQLite, Memory, or a single Postgres worker) are unaffected.

### Added
- `Snooze(seconds, reason=None)` return type (`elephantq.Snooze`). Returning it from a job handler re-schedules the job without consuming a retry slot. Useful for rate-limited APIs (HTTP 429) and webhook backpressure. Capped by the new `snooze_max_seconds` setting (default `86400`).
- `retry_jitter` parameter on `@elephantq.job` (default `True`). Applies full-jitter to the exponential backoff when `retry_backoff=True`, sampling uniformly in `[computed/2, computed]` to prevent thundering-herd retries after batch failures. Set `retry_jitter=False` for deterministic timing.
- `elephantq/core/leadership.py`: `advisory_key(name)` (blake2b-derived, cross-process stable) and `with_advisory_lock(backend, name)` async context manager. Backends without native support fall through to always-leader mode.
- `PostgresBackend.with_advisory_lock(name)`: session-scoped `pg_try_advisory_lock` on a dedicated connection for the lifetime of the context.
- `examples/snooze_on_rate_limit.py`: HTTP 429 demo wiring `Snooze` to `Retry-After`.

### Changed
- Exponential backoff (`retry_backoff=True`) now applies full-jitter by default. Jobs that depended on deterministic retry timing will see delays uniformly sampled in `[computed/2, computed]`. Set `retry_jitter=False` on the `@elephantq.job` decorator to restore the previous behavior.
- `Worker._maybe_cleanup` (pruner + stale-worker rescuer) and `EnhancedRecurringScheduler._scheduler_loop` now run under an advisory-lock leader guard. Multi-worker deployments stop duplicating maintenance work N times per tick. Single-worker deployments see no change. The per-job optimistic lock in `_claim_and_advance_run` remains the correctness floor for recurring job claims.

### Fixed
- Removed orphan `asyncio.create_task(db_handler.setup_database())` call in `LoggingConfig.setup_enterprise_logging`. The target was a no-op, so the task never did anything; dropping it also eliminates a warning about an un-awaited coroutine when logging is configured synchronously.

### Added (tests)
- `tests/unit/test_no_orphan_tasks.py`: AST-walk guard against new orphan `asyncio.create_task` / `asyncio.ensure_future` calls.
- `tests/integration/test_dead_letter_recursion.py`: bounded-time regression coverage for the `_rows_affected` recursion fix.
- `tests/integration/test_schedule_builder_race.py`: 50-way concurrent-enqueue test pinning the `JobScheduleBuilder` dedup_key contract.
- `tests/unit/test_no_depends_on.py`: expanded to `hasattr`, direct-import `ImportError`, and `__all__` assertions so the removed `depends_on` API cannot silently return.
- `tests/unit/test_retry_backoff.py`: full-jitter bounds, RNG injection, and `retry_max_delay` cap under jitter.
- `tests/unit/test_advisory_key.py` + `tests/integration/test_leader_election.py`: key stability across processes and exclusive-leader semantics under concurrent holders.
- `tests/unit/test_snooze.py` + `tests/integration/test_snooze_postgres.py`: Snooze requeue path, attempts roll-back, cap enforcement, and end-to-end Postgres flow.

## [0.3.0] - 2026-03-27

### Architecture
- **Pluggable storage backends** — `StorageBackend` Protocol with PostgreSQL, SQLite, and Memory implementations
- **Auto-detection** — backend selected automatically from `database_url` (`.db` → SQLite, `postgresql://` → Postgres)
- **Worker extraction** — `elephantq/worker.py` extracted from `client.py` (-247 lines)
- **Three-tier test architecture** — smoke/unit/functional/integration with proper conftest isolation

### Added
- `PostgresBackend` — all SQL extracted from inline code into dedicated backend
- `SQLiteBackend` — zero-setup local development (`pip install elephantq[sqlite]`)
- `MemoryBackend` — in-memory backend for unit tests (zero external deps)
- `@elephantq.periodic(cron="...", every_minutes=N)` — first-class decorator for recurring jobs
- `JobContext` — runtime metadata injection for running jobs (`ctx: JobContext`)
- `queueing_lock` parameter for flexible job deduplication
- `elephantq.reset()` — test fixture cleanup via backend
- Module discovery: auto `sys.path` fix, multi-module support, batch error reporting
- Clean import paths: `from elephantq import every, cron` (no more `elephantq.features.X`)
- `docs/backends.md`, `docs/agents.md`

### Removed
- `depends_on()` — experimental, unimplemented in worker
- `EnterpriseFeatures` / `enterprise` aliases
- All legacy/backward-compat code and comments
- Legacy Fernet decryption path

### Changed
- Multi-scheduler safety via optimistic locking (`_claim_and_advance_run`)
- Getting-started docs lead with SQLite (zero-setup) instead of requiring PostgreSQL
- CI split into unit+sqlite (no Postgres) and integration (real Postgres) jobs

## [0.2.0] - 2026-03-24

### Breaking Changes
- Default `job_timeout` changed from `None` (no timeout) to `300` seconds. Jobs exceeding 5 minutes are now treated as failures. Override per-job with `@elephantq.job(timeout=None)` or globally with `ELEPHANTQ_JOB_TIMEOUT=0`.
- All timestamp columns normalized to `TIMESTAMP WITH TIME ZONE` in the base migration files.
- Removed `EnterpriseFeatures` and `enterprise` aliases from `elephantq.features`.

### Fixed
- Fixed fragile error classification that silently dead-lettered retryable jobs when error messages contained "argument" or "parameter"
- Fixed broken `examples/recurring_jobs.py` (used non-existent API)
- Fixed broken `examples/transactional_enqueue.py` (passed unsupported arg to `setup()`)
- Fixed LISTEN connection leak in worker loop (connection acquired outside try block)
- Fixed `ELEPHANTQ_SKIP_UPDATE_LOCK` env var now only honored in debug/testing mode
- Replaced 11 dead `docs.elephantq.dev` URLs with GitHub doc links

### Added
- Default 300-second job execution timeout with per-job override via `@elephantq.job(timeout=N)`
- `py.typed` marker for PEP 561 type checker support
- `init` callback on instance connection pool for UTC timezone initialization
- End-to-end crash recovery tests
- Concurrent dequeue race condition tests
- Timeout enforcement tests
- Connection pool exhaustion tests
- Missing job handler tests
- Example import smoke tests in CI
- Coverage reporting in CI
- mypy configuration and CI integration
- Dead URL regression guard in CI

### Changed
- `list_jobs` default limit harmonized to 100 across all API entry points
- Simplified `features/features.py` imports (35 aliased imports replaced with deferred module imports)
- Per-query `SET timezone = 'UTC'` removed from processor (now handled by pool init callback)

### Documentation
- Added job timeout documentation to retries.md and getting-started.md
- Rewrote stuck-job-recovery.md to document automatic heartbeat-based recovery
- Added `__all__` exports to `features/recurring.py`

## [Unreleased]

### Fixed
- Fixed infinite recursion in `dead_letter.py` `_rows_affected()` that crashed all dead letter operations
- Fixed fire-and-forget `create_task()` calls in recurring.py that caused silent data loss
- Fixed non-atomic state update in recurring job execution (in-memory updated before DB write)
- Fixed `datetime.now()` without timezone in health.py
- Fixed logging handler holding asyncio lock during database I/O
- Removed unnecessary `async` from `high_priority()`, `background()`, `urgent()` convenience functions
- Added experimental warning to `depends_on()` (dependency enforcement not yet implemented in worker)
- Capped webhook response body reads at 4KB to prevent OOM
- Added backpressure to webhook delivery queue (maxsize=1000)

### Changed
- Moved `_rows_affected()` to shared `elephantq/db/helpers.py` (deduplicated from 3 files)
- Moved `croniter`, `aiohttp`, `structlog`, `cryptography` from core deps to optional extras
- Core install now only requires `asyncpg`, `pydantic`, `pydantic-settings`
- Refactored `process_jobs` and `process_jobs_with_registry` to share common logic
- Replaced O(n) metrics lookup with O(1) dict index
- Increased PBKDF2 iterations from 100k to 310k (NIST 2023 recommendation)
- Moved dependencies table DDL from inline runtime creation to migration 004

### Added
- Migration 004: composite index on (queue, status, priority, scheduled_at) for the hottest query
- Migration 004: `elephantq_job_dependencies` table (previously created inline)
- GitHub Actions CI workflows for tests, linting, and PyPI publishing
- At-least-once delivery semantics documented in getting-started, retries, production, and transactional-enqueue docs
- Idempotency guidance added to docs
- CHANGELOG.md

### Documentation
- Fixed false "exactly-once delivery" claim in transactional-enqueue docs
- Marked `depends_on()` as experimental in docs/features.md and docs/scheduling.md
- Added delivery semantics and idempotency sections across docs

## [0.1.1] - 2025-05-01

### Fixed
- Fixed SQL injection vectors and TOCTOU race conditions
- Fixed timezone bugs and memory leaks
- Fixed zombie job handling and secret key leak
- Replaced hardcoded PBKDF2 salt with random salt

## [0.1.0] - 2025-04-15

### Added
- Initial release
- PostgreSQL-backed async job queue with SKIP LOCKED
- Transactional enqueue support
- Retry engine with fixed, exponential, and per-attempt delays
- Dead letter queue management
- Worker heartbeat and stale worker recovery
- Job scheduling with fluent builder API
- Recurring jobs with cron and interval support
- Webhook notifications for job lifecycle events
- CLI for setup, worker management, and job inspection
- Optional FastAPI dashboard
- Health checks and metrics collection
