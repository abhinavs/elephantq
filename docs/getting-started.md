# Getting Started (about 60 seconds)

This guide walks through the minimal sequence to enqueue, run, and observe a job with ElephantQ. It assumes you already have PostgreSQL running.

## 1. Install

```bash
pip install elephantq
```

Optional extras add the dashboard and monitoring dependencies:

```bash
pip install elephantq[dashboard]
pip install elephantq[monitoring]
```

## 2. Configure the environment

```bash
export ELEPHANTQ_DATABASE_URL="postgresql://postgres@localhost/elephantq_dev"
export ELEPHANTQ_JOBS_MODULES="my_app.jobs"
```

The worker imports the modules listed in `ELEPHANTQ_JOBS_MODULES`, so ensure it resolves to the files where you decorated your jobs.

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

## 8. Troubleshooting tips

- **Jobs not appearing?** Confirm `ELEPHANTQ_JOBS_MODULES` matches the module path your worker loads.
- **Tables missing?** Re-run `elephantq setup` before starting the worker.
- **Need quick development loop?** `ELEPHANTQ_DATABASE_URL` can point to SQLite-backed Postgres containers; `elephantq dev` spins up worker + scheduler + dashboard for you.

For deeper detail, see the [scheduling](scheduling.md), [features](features.md), and [production](production.md) guides.
