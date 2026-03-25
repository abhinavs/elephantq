# Transactional Enqueue

ElephantQ lets you enqueue a job inside an existing database transaction. If the transaction rolls back, the job never enters the queue.

## The guarantee

When you pass `connection=conn` to `enqueue()`, the job row is written to `elephantq_jobs` using that connection. Because the INSERT is part of your transaction, it only becomes visible (and therefore pickable by a worker) after `COMMIT`.

This gives you **atomic data + job semantics**: either both your business data and the job are committed, or neither is.

## Usage

### Global API

```python
import elephantq

pool = await elephantq.get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders ...")
        await elephantq.enqueue(send_invoice, connection=conn, order_id=order_id)
```

### Instance API

```python
from elephantq import ElephantQ

app = ElephantQ(database_url="postgresql://localhost/myapp")

pool = await app.get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders ...")
        await app.enqueue(send_invoice, connection=conn, order_id=order_id)
```

## Delivery semantics

ElephantQ provides **at-least-once delivery**. A job may execute more than once if a worker crashes after executing the job function but before updating the job's status in the database. Stale worker recovery will reset the job back to `queued`, causing it to run again.

**Design your job functions to be idempotent.** Use database-level deduplication keys, upserts, or check-before-act patterns for side effects like sending emails or charging payments.

## What transactional enqueue does NOT guarantee

- **Single execution.** The transactional guarantee applies to enqueue (the job enters the queue if and only if the transaction commits). It does not prevent re-execution after worker crashes. See the delivery semantics section above.
- **Rollback after commit.** Once committed, the job is in the queue. You can cancel it with `elephantq.cancel_job(job_id)`, but there is a window where a fast worker might pick it up first.

## When to use it

- Creating a database record and sending a follow-up (email, webhook, notification).
- Writing to multiple tables where the job must only run if all writes succeed.
- Any workflow where "row exists but job is missing" would be a data integrity bug.

## See also

- `examples/transactional_enqueue.py` — runnable FastAPI demo
- [docs/scheduling.md](scheduling.md) — transactional scheduling with `JobScheduleBuilder`
