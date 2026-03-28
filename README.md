# ElephantQ

Background jobs for Python. Powered by the Postgres you already have.

## Quick start

```bash
pip install elephantq
```

```python
# jobs.py
import elephantq

app = elephantq.ElephantQ(database_url="postgresql://postgres@localhost/elephantq")

@app.job(max_retries=3)
async def send_welcome(to: str):
    print(f"Sending welcome to {to}")
```

```python
# enqueue from your app (FastAPI, CLI, script, etc.)
await app.enqueue(send_welcome, to="team@example.com")
```

```bash
# set up the database and start a worker
elephantq setup
elephantq start --concurrency 4
```

That's it. Define a job, enqueue it, start a worker.

## Transactional enqueue

Enqueue a job inside your database transaction. If the transaction rolls back, the job never existed. No Redis queue can do this.

```python
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders ...")
        await app.enqueue(send_invoice, connection=conn, order_id=order_id)
        # Both commit atomically, or neither does
```

## Why ElephantQ

**No Redis. No RabbitMQ. No extra infrastructure.**

Most Python job queues force you to run Redis or RabbitMQ alongside your database. That's another service to deploy, monitor, back up, and debug when things go wrong at 3am.

ElephantQ uses your existing PostgreSQL database as the job queue. One dependency. One place your data lives. One thing to back up.

| Feature             | ElephantQ | Celery         | RQ     | Dramatiq       | Arq    |
| ------------------- | --------- | -------------- | ------ | -------------- | ------ |
| No Redis dependency | yes       | no             | no     | no             | no     |
| Async native        | yes       | partial        | no     | partial        | yes    |
| Transactional enq.  | yes       | no             | no     | no             | no     |
| Setup complexity    | Low       | High           | Medium | Medium         | Medium |
| Infra dependencies  | Postgres  | Redis/RabbitMQ | Redis  | Redis/RabbitMQ | Redis  |

## Features

- **Retries with backoff** — failed jobs are retried automatically with configurable delays and exponential backoff
- **Dead-letter queue** — after max retries, jobs move to dead-letter for inspection and manual retry
- **Job priorities** — lower number = higher priority, processed first
- **Scheduled jobs** — enqueue jobs to run at a specific time or after a delay
- **Recurring jobs** — cron-based periodic tasks with `@app.periodic(cron="0 * * * *")`
- **Dedup** — prevent duplicate jobs with `dedup_key` or `unique=True`
- **Middleware hooks** — `@app.before_job`, `@app.after_job`, `@app.on_error` for logging, metrics, tracing
- **Job results** — store and retrieve return values from completed jobs
- **Multiple queues** — route jobs to named queues, run workers per queue
- **Worker heartbeat** — track worker liveness, auto-requeue jobs from crashed workers
- **Async context manager** — `async with ElephantQ(...) as app:` for clean lifecycle management
- **CLI** — `elephantq setup`, `elephantq start`, `elephantq status`, `elephantq workers`

## Dashboard

Monitor queues, workers, retries, and system health from a built-in web UI.

```bash
pip install elephantq[dashboard]
elephantq dashboard
```

![ElephantQ Dashboard](https://raw.githubusercontent.com/abhinavs/elephantq/main/docs/assets/elephantq_dashboard.png)

## Install

```bash
pip install elephantq              # core (PostgreSQL backend included)
pip install elephantq[full]        # everything below
pip install elephantq[sqlite]      # SQLite backend for local dev
pip install elephantq[scheduling]  # cron-based recurring jobs
pip install elephantq[webhooks]    # webhook delivery
pip install elephantq[dashboard]   # web dashboard
pip install elephantq[monitoring]  # Prometheus metrics
```

## Works great for

- Sending emails after user signup
- Processing file uploads in the background
- Running nightly reports and data syncs
- Webhook delivery with retry logic

## Documentation

- [Getting started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [Scheduling](docs/scheduling.md)
- [Testing](docs/testing.md)
- [Production guide](docs/production.md)
- [Deployment](docs/deployment.md)
- [Backends](docs/backends.md)
- [Feature flags](docs/feature-flags.md)

## Deploy to production

Ready-to-use configs for systemd, supervisor, Docker Compose, and Kubernetes:

[Deployment guide](docs/deployment.md)

**Note:** if you need 10k+ jobs/sec or cross-language consumers, a Redis-backed queue is a better fit.

## License

MIT License
