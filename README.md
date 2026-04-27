# Soniq

Background jobs for Python. Powered by the Postgres you already have.

[![PyPI version](https://img.shields.io/pypi/v/soniq)](https://pypi.org/project/soniq/)
[![Python versions](https://img.shields.io/pypi/pyversions/soniq)](https://pypi.org/project/soniq/)
[![License](https://img.shields.io/github/license/abhinavs/soniq)](https://github.com/abhinavs/soniq/blob/main/LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/abhinavs/soniq/test.yml?label=tests)](https://github.com/abhinavs/soniq/actions)

## Quickstart

```bash
pip install soniq
```

```python
# jobs.py
from soniq import Soniq

app = Soniq(database_url="postgresql://localhost/myapp")

@app.job(max_retries=3)
async def send_welcome(to: str):
    print(f"Sending welcome email to {to}")
```

```python
# enqueue from anywhere in your app
await app.enqueue(send_welcome, to="dev@example.com")
```

```bash
# set up tables and start processing
soniq setup
soniq start --concurrency 4
```

Four steps. Define a job, enqueue it, set up the database, start a worker.

> **Local dev without Postgres?** Use SQLite: `Soniq(database_url='local.db')`.
> For production, always use PostgreSQL.

## Transactional enqueue

Enqueue a job inside your database transaction. If the transaction rolls back, the job never existed.

```python
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders ...")
        await app.enqueue(send_invoice, connection=conn, order_id=order_id)
        # Both commit together, or neither does
```

No Redis queue can do this. Your job and your data land in the same commit. If something fails halfway through, both roll back. No stale jobs, no ghost tasks, no cleanup scripts.

## Cross-service enqueue

Service A enqueues; service B owns and runs the handler. Both share a Postgres database, neither imports the other's code.

```python
# Producer (service A) - no local registry
producer = Soniq(
    database_url="postgresql://shared-pg/jobs",
    enqueue_validation="none",
)
await producer.enqueue("billing.invoices.send.v2", args={"order_id": "o1"})
```

```python
# Consumer (service B) - registers the handler
# myservice/tasks.py
consumer = Soniq(database_url="postgresql://shared-pg/jobs")

@consumer.job(name="billing.invoices.send.v2", validate=InvoiceArgs)
async def send_invoice(order_id: str): ...
```

```bash
# Run the worker via the CLI (run from your process manager)
export SONIQ_JOBS_MODULES="myservice.tasks"
soniq start
```

Soniq is at-least-once, not exactly-once: handlers should be idempotent. See [docs/guides/cross-service-jobs.md](docs/guides/cross-service-jobs.md) for the full delivery-semantics details.

## Why Soniq

Most Python job queues force you to run Redis or RabbitMQ alongside your database. That's another service to deploy, monitor, back up, and debug when things go wrong at 3am.

Soniq uses your existing PostgreSQL. One dependency. One place your data lives. One thing to back up.

| Feature             | Soniq | Celery      | RQ     |
| ------------------- | ----- | ----------- | ------ |
| No Redis dependency | Yes   | No          | No     |
| Async native        | Yes   | Partial     | No     |
| Transactional enq.  | Yes   | No          | No     |
| Setup complexity    | Low   | High        | Medium |
| Built-in dashboard  | Yes   | No (Flower) | No     |
| Dead-letter queue   | Yes   | No          | No     |

## Features

- **Retries with backoff** - configurable delays, exponential backoff, per-attempt delay lists
- **Dead-letter queue** - failed jobs preserved for inspection and manual retry
- **Job priorities** - lower number = higher priority, processed first
- **Scheduled jobs** - run at a specific time or after a delay
- **Recurring jobs** - cron-based periodic tasks with `@app.periodic(cron="0 * * * *")`
- **Transactional enqueue** - atomic with your database writes
- **Multiple queues** - route jobs by type, run dedicated workers per queue
- **Middleware hooks** - `before_job`, `after_job`, `on_error` for logging, metrics, tracing
- **Worker heartbeat** - auto-detect crashed workers, requeue their jobs
- **Job results** - store and retrieve return values from completed jobs
- **Deduplication** - prevent duplicate jobs with `dedup_key` or `unique=True`
- **CLI** - `setup`, `start`, `status`, `workers`, dead-letter management
- **Dashboard** - web UI for monitoring queues, workers, and job state

## Dashboard

Monitor queues, workers, retries, and system health from a built-in web UI.

```bash
pip install soniq[dashboard]
soniq dashboard
```

## Install

```bash
pip install soniq              # core (Postgres backend)
pip install soniq[full]        # everything below
pip install soniq[sqlite]      # SQLite backend for local dev
pip install soniq[scheduling]  # cron-based recurring jobs
pip install soniq[dashboard]   # web dashboard
pip install soniq[monitoring]  # Prometheus metrics
pip install soniq[webhooks]    # webhook delivery + signing
```

## Known limitations

Worth knowing before you adopt. Also called out in the production checklist linked below.

- **No named concurrency limits (per-key execution gates).** `unique=True` and `dedup_key` prevent *queueing* duplicates, but nothing caps concurrent *execution* for a logical resource. If you need "at most 3 jobs for `user_id=42` at a time," that belongs upstream of Soniq today. Planned, not in this release.
- **Recurring scheduler uses a Postgres session-scoped advisory lock.** PgBouncer deployments must run in session-pooling mode. Transaction-pooling releases the lock between statements and breaks the leader guarantee.
- **Python-only consumers.** Workers are Python processes. Cross-language workers (Go, Node, etc.) need a broker like RabbitMQ instead.
- **SQLite backend is single-writer.** Good enough for local dev and prototyping; PostgreSQL for anything production-shaped.

## When NOT to use Soniq

- **You need 10k+ jobs/sec sustained throughput.** PostgreSQL row locking has limits. Redis-backed queues like Celery or Arq are built for this.
- **You need cross-language consumers.** Soniq is Python-only. If your workers are in Go or Node, use RabbitMQ or a similar broker.
- **You're not using PostgreSQL.** The production backend requires PostgreSQL. If your stack is MySQL or MongoDB, this isn't for you.
- **You need DAG-based workflow orchestration.** Soniq handles individual jobs, not pipelines. Look at Prefect or Airflow.

## Documentation

- [Quickstart](docs/getting-started/quickstart.md)
- [FastAPI integration](docs/guides/fastapi.md)
- [Jobs and concepts](docs/concepts/jobs.md)
- [Production checklist](docs/production/checklist.md)
- [Deployment](docs/production/deployment.md)
- [CLI reference](docs/cli/commands.md)
- [API reference](docs/api/soniq.md)

## License

MIT
