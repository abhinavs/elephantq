# Architecture

This document describes how ElephantQ works under the hood.

## Core design

ElephantQ uses PostgreSQL as the single backend for job storage, coordination, and notification. There is no Redis, no RabbitMQ, no external broker. The design leans on three PostgreSQL features:

1. **`LISTEN/NOTIFY`** — instant wake-up when new jobs arrive.
2. **`FOR UPDATE SKIP LOCKED`** — safe concurrent job fetching without contention.
3. **Transactions** — atomic enqueue alongside your application writes.

## Worker loop

Each worker runs a continuous async loop:

```
┌──────────────────────────────────────────┐
│  1. LISTEN on elephantq_jobs_channel     │
│  2. Fetch queued jobs (SKIP LOCKED)      │
│  3. Execute job function                 │
│  4. Update status (done / failed)        │
│  5. Handle retries / dead-letter         │
│  6. Sleep until NOTIFY or poll interval  │
└──────────────────────────────────────────┘
```

Workers use a semaphore-based concurrency model. `ELEPHANTQ_DEFAULT_CONCURRENCY` controls how many jobs a single worker processes simultaneously.

## LISTEN/NOTIFY flow

When a job is enqueued:

1. The job row is INSERTed into `elephantq_jobs`.
2. A `NOTIFY elephantq_jobs_channel` is sent with the job ID.
3. All listening workers wake up immediately.
4. Workers compete to lock the job with `SELECT ... FOR UPDATE SKIP LOCKED`.
5. The winner processes the job; losers move on.

This makes job pickup near-instant (typically <10ms) without polling overhead.

## Job lifecycle

```
enqueued ──► queued ──► processing ──► done
                │              │
                │              ▼
                │           failed ──► retry ──► queued
                │              │
                │              ▼
                │         dead_letter
                ▼
           cancelled
```

## Database schema

### `elephantq_jobs` (core)

The main job table. Every job lives here.

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `job_name` | TEXT | Fully qualified function name |
| `args` | JSONB | Job arguments |
| `args_hash` | TEXT | SHA-256 hash for uniqueness dedup |
| `status` | TEXT | Current state |
| `attempts` | INT | How many times this job has been tried |
| `max_attempts` | INT | Retry budget |
| `queue` | TEXT | Queue name |
| `priority` | INT | Lower = higher priority |
| `scheduled_at` | TIMESTAMP | When to execute (null = immediate) |
| `expires_at` | TIMESTAMP | Result TTL expiry |
| `last_error` | TEXT | Most recent failure message |
| `created_at` | TIMESTAMP | When enqueued |
| `updated_at` | TIMESTAMP | Last status change |

Key indexes:
- `(status, priority)` — fast job selection.
- `(queue, status)` — queue-filtered queries.
- `(scheduled_at)` — scheduled job lookup.
- `(args_hash)` — conditional unique index for dedup.

### `elephantq_workers`

Worker heartbeat table. Used to detect stale workers and display worker status in the dashboard.

### `elephantq_recurring_jobs`

Persistent recurring job schedules (interval and cron). Reloaded on scheduler restart.

### Optional tables

Created on demand when features are enabled:
- `elephantq_dead_letter_jobs` — failed jobs beyond retry budget.
- `elephantq_job_dependencies` — job ordering constraints.
- `elephantq_pro_job_timeouts` — per-job timeout configuration.

## Migration system

Migrations live in `elephantq/db/migrations/` and run automatically via `elephantq setup`. The `elephantq_migrations` table tracks which migrations have been applied. Migrations are idempotent and safe to re-run.

## Job registry

The `JobRegistry` maps function names to metadata (retries, queue, priority, unique flag). Jobs are registered via the `@elephantq.job()` decorator at import time. Workers use `ELEPHANTQ_JOBS_MODULES` to discover and import job modules.

## Connection pool management

ElephantQ manages an `asyncpg` connection pool. The pool is sized by `ELEPHANTQ_DB_POOL_MIN_SIZE` and `ELEPHANTQ_DB_POOL_MAX_SIZE`. A safety margin (`ELEPHANTQ_DB_POOL_SAFETY_MARGIN`, default 2) reserves connections for the LISTEN/NOTIFY listener and the heartbeat writer — these long-lived connections should not compete with job processing connections.

## Graceful shutdown

Workers handle `SIGINT` and `SIGTERM`:

1. Stop accepting new jobs.
2. Wait for in-flight jobs to complete (up to a timeout).
3. Update worker status to `stopped`.
4. Close the connection pool.

This makes ElephantQ safe in Docker, Kubernetes, and systemd environments.
