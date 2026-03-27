# ElephantQ

Background jobs for Python. Powered by the Postgres you already have.

## Quick start (30 seconds, no database server)

```bash
pip install elephantq
```

```python
# quickstart.py
import asyncio
import elephantq

app = elephantq.ElephantQ(database_url="jobs.db")

@app.job(retries=3)
async def send_welcome(to: str):
    print(f"Sending welcome to {to}")

async def main():
    await app.setup()
    await app.enqueue(send_welcome, to="team@example.com")
    await app.run_worker(run_once=True)

asyncio.run(main())
```

```bash
$ python quickstart.py
Sending welcome to team@example.com
```

One file. Copy, paste, run. No database server, no configuration.

## The killer feature: transactional enqueue

Insert a row and enqueue a job in the same database transaction. If the transaction rolls back, the job never existed. No Redis can give you this.

```python
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders ...")
        await elephantq.enqueue(send_invoice, connection=conn, order_id=order_id)
        # Both commit atomically, or neither does
```

## Move to production

```bash
export ELEPHANTQ_DATABASE_URL="postgresql://postgres@localhost/elephantq"
elephantq setup   # create tables
elephantq start --concurrency 4 --queues default,emails
```

Your code stays the same. ElephantQ auto-detects PostgreSQL from the URL and unlocks concurrent workers, push notifications (`pg_notify`), and transactional enqueue.

## Why ElephantQ

**No Redis. No RabbitMQ. No extra infrastructure.**

Most Python job queues force you to run Redis or RabbitMQ alongside your database. That's another service to deploy, monitor, back up, and debug when things go wrong at 3am.

ElephantQ uses your existing PostgreSQL database as the job queue. One dependency. One place your data lives. One thing to back up.

- **Transactional enqueue**: insert a row and enqueue a job atomically. No eventual consistency.
- **Zero-setup dev**: SQLite backend for local development. No servers needed.
- **Production-ready**: `FOR UPDATE SKIP LOCKED` for safe concurrent workers, `pg_notify` for instant job pickup, retries with backoff, dead-letter queue.
- **Async-native**: built for FastAPI and modern Python. `@job`, `await enqueue`, done.

## How it compares

| Feature             | ElephantQ | Celery         | RQ     | Dramatiq       | Arq    |
| ------------------- | --------- | -------------- | ------ | -------------- | ------ |
| No Redis dependency | yes       | no             | no     | no             | no     |
| Async native        | yes       | partial        | no     | partial        | yes    |
| Transactional enq.  | yes       | no             | no     | no             | no     |
| Setup complexity    | Low       | High           | Medium | Medium         | Medium |
| Infra dependencies  | Postgres  | Redis/RabbitMQ | Redis  | Redis/RabbitMQ | Redis  |

## When things go wrong

- **Retries with backoff**: failed jobs are retried automatically with configurable delay and exponential backoff.
- **Dead-letter queue**: after max retries, jobs move to dead-letter for inspection and manual retry.
- **Dashboard**: monitor queues, workers, and job status in a built-in web UI.
- **CLI**: `elephantq status` shows queue health at a glance.

## Works great for

- Sending emails after user signup
- Processing file uploads in the background
- Running nightly reports and data syncs
- Webhook delivery with retry logic

## Deploy to production

Ready-to-use configs for systemd, supervisor, Docker Compose, and Kubernetes:

[Deployment guide](docs/deployment.md) — systemd, supervisor, Docker Compose, Kubernetes configs

## Optional extras

```bash
pip install elephantq[sqlite]       # SQLite backend
pip install elephantq[scheduling]   # cron-based recurring jobs
pip install elephantq[webhooks]     # webhook delivery
pip install elephantq[dashboard]    # web dashboard
pip install elephantq[monitoring]   # Prometheus metrics
```

## Documentation

- [Getting started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [Scheduling](docs/scheduling.md)
- [Testing](docs/testing.md)
- [Production guide](docs/production.md)
- [Deployment](docs/deployment.md)
- [Backends](docs/backends.md)
- [Feature flags](docs/feature-flags.md)

**Note:** if you need 10k+ jobs/sec or cross-language consumers, a Redis-backed queue is a better fit.

## License

MIT License
