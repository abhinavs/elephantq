# Changelog

All notable changes to ElephantQ will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
