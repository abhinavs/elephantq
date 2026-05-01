# Soniq

Background jobs for Python. Powered by the Postgres you already have.

## How it works

Soniq stores background jobs as rows in your existing PostgreSQL database. There is no broker, no Redis, no extra service to run. When you enqueue a job, Soniq inserts a row. When a worker is ready, it claims the row using `SELECT ... FOR UPDATE SKIP LOCKED` -- a Postgres-native locking primitive that lets multiple workers compete safely without polling. Pickup is push-based via `LISTEN/NOTIFY`, so latency is typically under 10 ms.

Your job data lives in the same database as the rest of your application. Backed up together. Monitored together. Transacted together.

## Quickstart

```bash
pip install soniq
```

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

```bash
soniq setup                          # one-time: create tables
SONIQ_JOBS_MODULES=jobs soniq start  # run a worker
python jobs.py                       # enqueue
```

Four steps. Define a job, set up the database, run a worker, enqueue.

[Full quickstart guide](quickstart.md){ .md-button }

## Transactional enqueue

The reason most teams choose a Postgres-backed queue. Enqueue a job inside the same transaction as your business writes - if the transaction rolls back, the job never existed:

```python
# Borrow a connection from Soniq's asyncpg pool. Any active asyncpg
# connection works here; it does not have to be Soniq's pool. If your
# app already has its own pool (or a SQLAlchemy session), pass that
# connection instead - see guides/transactional-enqueue.md.
async with app.backend.acquire() as conn:
    async with conn.transaction():
        # Your business write. The order row only becomes visible once
        # this transaction commits.
        await conn.execute(
            "INSERT INTO orders (id, total) VALUES ($1, $2)",
            order_id, total,
        )

        # Same connection -> same transaction. The job row goes into
        # soniq_jobs as part of *this* COMMIT, not a separate one.
        # connection=conn is the only thing that differs from a normal
        # enqueue() call.
        await app.enqueue(
            send_invoice,
            connection=conn,
            order_id=order_id,
        )

        # If anything inside this `with` block raises, both writes
        # roll back together. The order is never created without the
        # follow-up job, and the job is never created for an order
        # that does not exist.
```

No Redis-backed queue can do this. Your job and your data land in the same commit. No stale jobs, no ghost jobs, no outbox table to drain.

## When NOT to use Soniq

- **You need 10k+ jobs/sec sustained throughput.** PostgreSQL row locking has limits. Redis-backed queues like Celery or Arq are built for this.
- **You need cross-language workers.** Soniq is Python-only. If your workers are in Go or Node, use RabbitMQ or similar.
- **You are not using PostgreSQL.** The production backend requires PostgreSQL.
- **You need DAG-based workflow orchestration.** Soniq runs individual jobs, not pipelines. Look at Prefect or Airflow.

## Where to next

- [Quickstart](quickstart.md) - five minutes from `pip install` to first job
- [Tutorial](tutorial/01-defining-jobs.md) - the six chapters that cover every Soniq concept
- [Going to production](production/going-to-production.md) - the eight things that matter
- [Reference](reference/index.md) - Python API, CLI, configuration
