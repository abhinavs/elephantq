# ElephantQ

Background jobs for Python. Powered by the Postgres you already have.

[![PyPI version](https://img.shields.io/pypi/v/elephantq)](https://pypi.org/project/elephantq/)
[![Python versions](https://img.shields.io/pypi/pyversions/elephantq)](https://pypi.org/project/elephantq/)
[![License](https://img.shields.io/github/license/abhinavs/elephantq)](https://github.com/abhinavs/elephantq/blob/main/LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/abhinavs/elephantq/tests.yml?label=tests)](https://github.com/abhinavs/elephantq/actions)

## Quickstart

```bash
pip install elephantq
```

```python
# jobs.py
from elephantq import ElephantQ

app = ElephantQ(database_url="postgresql://localhost/myapp")

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
elephantq setup
elephantq start --concurrency 4
```

Four steps. Define a job, enqueue it, set up the database, start a worker.

> **Local dev without Postgres?** Use SQLite: `ElephantQ(database_url='local.db')`.
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

## Why ElephantQ

Most Python job queues force you to run Redis or RabbitMQ alongside your database. That's another service to deploy, monitor, back up, and debug when things go wrong at 3am.

ElephantQ uses your existing PostgreSQL. One dependency. One place your data lives. One thing to back up.

| Feature             | ElephantQ | Celery         | RQ     |
| ------------------- | --------- | -------------- | ------ |
| No Redis dependency | Yes       | No             | No     |
| Async native        | Yes       | Partial        | No     |
| Transactional enq.  | Yes       | No             | No     |
| Setup complexity    | Low       | High           | Medium |
| Built-in dashboard  | Yes       | No (Flower)    | No     |
| Dead-letter queue   | Yes       | No             | No     |

## Features

- **Retries with backoff** -- configurable delays, exponential backoff, per-attempt delay lists
- **Dead-letter queue** -- failed jobs preserved for inspection and manual retry
- **Job priorities** -- lower number = higher priority, processed first
- **Scheduled jobs** -- run at a specific time or after a delay
- **Recurring jobs** -- cron-based periodic tasks with `@app.periodic(cron="0 * * * *")`
- **Transactional enqueue** -- atomic with your database writes
- **Multiple queues** -- route jobs by type, run dedicated workers per queue
- **Middleware hooks** -- `before_job`, `after_job`, `on_error` for logging, metrics, tracing
- **Worker heartbeat** -- auto-detect crashed workers, requeue their jobs
- **Job results** -- store and retrieve return values from completed jobs
- **Deduplication** -- prevent duplicate jobs with `dedup_key` or `unique=True`
- **CLI** -- `setup`, `start`, `status`, `workers`, dead-letter management
- **Dashboard** -- web UI for monitoring queues, workers, and job state

## Dashboard

Monitor queues, workers, retries, and system health from a built-in web UI.

```bash
pip install elephantq[dashboard]
elephantq dashboard
```

![ElephantQ Dashboard](https://raw.githubusercontent.com/abhinavs/elephantq/main/docs/assets/elephantq_dashboard.png)

## Install

```bash
pip install elephantq              # core (Postgres backend)
pip install elephantq[full]        # everything below
pip install elephantq[sqlite]      # SQLite backend for local dev
pip install elephantq[scheduling]  # cron-based recurring jobs
pip install elephantq[dashboard]   # web dashboard
pip install elephantq[monitoring]  # Prometheus metrics
pip install elephantq[webhooks]    # webhook delivery + signing
```

## When NOT to use ElephantQ

- **You need 10k+ jobs/sec sustained throughput.** PostgreSQL row locking has limits. Redis-backed queues like Celery or Arq are built for this.
- **You need cross-language consumers.** ElephantQ is Python-only. If your workers are in Go or Node, use RabbitMQ or a similar broker.
- **You're not using PostgreSQL.** The production backend requires PostgreSQL. If your stack is MySQL or MongoDB, this isn't for you.
- **You need DAG-based workflow orchestration.** ElephantQ handles individual jobs, not pipelines. Look at Prefect or Airflow.

## Documentation

- [Quickstart](docs/getting-started/quickstart.md)
- [FastAPI integration](docs/guides/fastapi.md)
- [Jobs and concepts](docs/concepts/jobs.md)
- [Production checklist](docs/production/checklist.md)
- [Deployment](docs/production/deployment.md)
- [CLI reference](docs/cli/commands.md)
- [API reference](docs/api/elephantq.md)

## License

MIT
