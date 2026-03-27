# Getting Started (about 60 seconds)

This guide walks through the minimal sequence to enqueue, run, and observe a job with ElephantQ. No database server required for local development.

## 1. Install

```bash
pip install elephantq
```

Optional extras:

```bash
pip install elephantq[sqlite]       # SQLite backend for local dev
pip install elephantq[scheduling]   # Recurring jobs (croniter)
pip install elephantq[webhooks]     # Webhooks + signing (aiohttp, cryptography)
pip install elephantq[dashboard]    # Web dashboard (fastapi, uvicorn)
pip install elephantq[monitoring]   # Metrics (prometheus-client, psutil)
pip install elephantq[full]         # Everything
```

## 2. Local development (SQLite — zero setup)

No PostgreSQL needed. ElephantQ auto-detects SQLite from a `.db` file path:

```python
import elephantq

elephantq.configure(database_url="elephantq.db")

@elephantq.job()
async def send_welcome(name: str):
    print(f"Welcome, {name}!")

await elephantq.enqueue(send_welcome, name="Alice")
await elephantq.run_worker(run_once=True)
```

## 3. Production (PostgreSQL)

For production, point at PostgreSQL:

```bash
export ELEPHANTQ_DATABASE_URL="postgresql://postgres@localhost/elephantq_dev"
export ELEPHANTQ_JOBS_MODULES="my_app.jobs"
```

ElephantQ auto-detects PostgreSQL from the `postgresql://` URL prefix. The worker imports the modules listed in `ELEPHANTQ_JOBS_MODULES`.

## 3. Define a job

```python
# my_app/jobs.py
import elephantq

@elephantq.job(queue="default", retries=3)
async def welcome_email(user_id: int):
    print("Sending welcome to", user_id)
```

The decorator registers the job with ElephantQ and keeps it available even if the worker restarts.

## 4. Prepare the database

```bash
elephantq setup
```

This creates all required tables (`elephantq_jobs`, tracking tables for heartbeats, recurring jobs, etc.) and can be re-run safely before every deployment.

## 5. Start workers

```bash
elephantq start --concurrency 4 --queues=default
```

Workers run in a separate terminal or process. You can run multiple workers against the same Postgres host. They poll with `LISTEN/NOTIFY` and `FOR UPDATE SKIP LOCKED` to avoid clobbering each other.

## 6. Enqueue a job

```python
import elephantq
from my_app.jobs import welcome_email

await elephantq.enqueue(welcome_email, user_id=42)
```

Use `elephantq.get_queue_stats()` to inspect queue depth or the dashboard when enabled.

## 7. Scheduler & dashboard (optional)

Recurring jobs or cron-like schedules require:

```bash
ELEPHANTQ_SCHEDULING_ENABLED=true elephantq scheduler
```

The dashboard lives behind:

```bash
ELEPHANTQ_DASHBOARD_ENABLED=true elephantq dashboard
```

Add `ELEPHANTQ_DASHBOARD_WRITE_ENABLED=true` only in trusted environments if you need retry/delete buttons.

## 8. Delivery semantics and idempotency

ElephantQ provides **at-least-once delivery**. Jobs may execute more than once if a worker crashes after running the job but before updating its status. Design your job functions to be idempotent — for example, use database upserts or deduplication keys for side effects like emails or payments.

Every job has a default **300-second timeout**. If your job needs more time, override it with `@elephantq.job(timeout=600)` or disable it with `timeout=None`. See [retries.md](retries.md) for details.

## 9. Troubleshooting tips

- **Jobs not appearing?** Confirm `ELEPHANTQ_JOBS_MODULES` matches the module path your worker loads.
- **Tables missing?** Re-run `elephantq setup` before starting the worker.
- **Need quick development loop?** Point `ELEPHANTQ_DATABASE_URL` at a local Postgres container and reuse the same commands above.

For deeper detail, see the [scheduling](scheduling.md), [features](features.md), and [production](production.md) guides.
