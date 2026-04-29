# Quickstart

Get a job running in under 5 minutes.

## 1. Install

```bash
pip install soniq
```

## 2. Define a job

```python
# jobs.py
from soniq import Soniq

app = Soniq(database_url="postgresql://localhost/myapp")

@app.job(max_retries=3)
async def send_welcome(to: str):
    print(f"Sending welcome email to {to}")
```

## 3. Enqueue

```python
await app.enqueue(send_welcome, to="dev@example.com")
```

## 4. Set up the database

```bash
soniq setup
```

This creates all required tables (`soniq_jobs`, heartbeat tracking, recurring jobs, etc.) and is safe to re-run on every deploy.

## 5. Start a worker

```bash
SONIQ_DATABASE_URL="postgresql://localhost/myapp" \
SONIQ_JOBS_MODULES="jobs" \
soniq start --concurrency 4
```

`SONIQ_JOBS_MODULES` tells the worker where to find your job definitions. It accepts comma-separated Python module paths, so a larger project might use `"app.jobs,billing.tasks,notifications.handlers"`. The current directory is automatically added to `sys.path`, so running the command from your project root is enough -- no `PYTHONPATH` gymnastics required.

!!! tip "Try without Postgres"
    For quick experiments, use SQLite -- no server needed:
    `Soniq(database_url="local.db")` (requires `pip install soniq[sqlite]`).
    SQLite is single-worker and polling-only. Use PostgreSQL for production.

## What changes in production

The code above works, but you'll want to tighten a few things before deploying for real:

- **Use environment variables** instead of hardcoding `database_url`. Soniq reads `SONIQ_DATABASE_URL` automatically.
- **Set `SONIQ_JOBS_MODULES`** so workers can import your job functions on startup (e.g., `SONIQ_JOBS_MODULES=myapp.tasks`).
- **Tune concurrency.** The default is 4 concurrent job slots per worker. Raise it for I/O-heavy workloads, lower it for CPU-bound ones.
- **Tune timeouts and retries per job.** `@app.job(timeout=..., max_retries=...)` covers the common cases; `SONIQ_JOB_TIMEOUT` and `SONIQ_MAX_RETRIES` set the global defaults.

See [installation.md](installation.md) for optional extras (`dashboard`, `webhooks`, `sqlite`).

## Delivery semantics

Soniq provides **at-least-once delivery**. A job may execute more than once if a worker crashes after running the handler but before marking the job as complete. Design your job functions to be idempotent -- use database upserts, deduplication keys, or idempotency tokens for side effects like emails or payments.

Every job has a default **300-second timeout**. Override it per-job with `@app.job(timeout=600)` or disable it with `timeout=None`.
