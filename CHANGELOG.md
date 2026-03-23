# Changelog

All notable changes to ElephantQ will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
