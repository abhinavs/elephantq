# Quickstart

Get a job running in under 5 minutes.

## 1. Install

```bash
pip install soniq
```

You will need a running PostgreSQL. If you do not have one handy, `docker run -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16` will do.

## 2. Define a job

```python
# jobs.py
import asyncio
from soniq import Soniq

app = Soniq(database_url="postgresql://localhost/myapp")

@app.job
async def send_welcome(to: str):
    print(f"Sending welcome email to {to}")

if __name__ == "__main__":
    asyncio.run(app.enqueue(send_welcome, to="dev@example.com"))
```

## 3. Set up the database

```bash
soniq setup
```

Creates the tables Soniq needs. Idempotent - safe to re-run on every deploy.

## 4. Start a worker

```bash
SONIQ_DATABASE_URL="postgresql://localhost/myapp" \
SONIQ_JOBS_MODULES="jobs" \
soniq start --concurrency 4
```

`SONIQ_JOBS_MODULES` tells the worker which Python modules to import so the `@app.job` decorators run. The worker process needs to be able to import your job code - see [Job module discovery](getting-started/installation.md#job-module-discovery) for cross-service setups and per-worker overrides.

## 5. Enqueue a job

In another terminal:

```bash
python jobs.py
```

The worker prints "Sending welcome email to dev@example.com". You have a working background queue.

## What changes in production

The code above works, but you will want to tighten a few things before deploying for real:

- **Use environment variables** instead of hardcoding `database_url`. Soniq reads `SONIQ_DATABASE_URL` automatically.
- **Set `SONIQ_JOBS_MODULES`** so workers can import your job functions on startup.
- **Run `soniq setup` only once per deploy**, not from every replica's startup. See [going to production](production/going-to-production.md).
- **Make handlers idempotent.** Soniq is at-least-once: a job may run more than once if a worker crashes mid-handler. Use upserts, dedup keys, or idempotency tokens for any side effect you would not want repeated.
- **Tune timeouts.** Every job has a default 300-second timeout. Override per-job with `@app.job(timeout=600)`.

## Where to go next

- [Tutorial](tutorial/01-defining-jobs.md) - the six chapters that cover every Soniq concept end to end
- [Going to production](production/going-to-production.md) - the eight things that matter for a healthy deploy
- [FastAPI guide](guides/fastapi.md) - the most common producer shape
- [Migrating from Celery](migration/from-celery.md) or [from RQ](migration/from-rq.md)
