# Transactional Enqueue

Enqueue a job inside a database transaction. If the transaction rolls back, the job never enters the queue.

## How it works

When you pass `connection=conn` to `enqueue()`, the job row is inserted into `soniq_jobs` using that connection. The INSERT is part of your transaction, so the job only becomes visible to workers after `COMMIT`.

Either both your business data and the job are committed, or neither is.

## Basic pattern

```python
pool = await eq.get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders (id, total) VALUES ($1, $2)", order_id, total)
        await eq.enqueue(
            "myapp.tasks.send_invoice",
            args={"order_id": order_id},
            connection=conn,
        )
```

The `connection=conn` parameter is the only thing that changes from a normal enqueue call. Everything else works the same -- job options, priority, scheduling.

## FastAPI route example

A real-world order creation endpoint where the order record and the follow-up job are committed atomically:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from soniq import Soniq

eq = Soniq(database_url="postgresql://localhost/myapp")

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await eq.close()

app = FastAPI(lifespan=lifespan)


@eq.job(queue="invoices", max_retries=5)
async def send_invoice(order_id: int):
    order = await get_order(order_id)
    await generate_and_send_invoice(order)


@app.post("/orders")
async def create_order(product_id: int, quantity: int):
    pool = await eq.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            order_id = await conn.fetchval(
                "INSERT INTO orders (product_id, quantity) VALUES ($1, $2) RETURNING id",
                product_id, quantity,
            )
            await eq.enqueue(
            "myapp.tasks.send_invoice",
            args={"order_id": order_id},
            connection=conn,
        )

    return {"order_id": order_id}
```

If the INSERT fails or anything else raises inside the transaction block, both the order row and the job are rolled back.

## Use cases

**Order + invoice.** Create the order and enqueue the invoice generation in one transaction. No orphaned orders without invoices.

**User signup + welcome email.** Insert the user row and enqueue the welcome email together. If the INSERT hits a unique constraint, no phantom email gets sent.

**Payment + receipt.** Record the payment and enqueue the receipt delivery atomically. No "payment recorded but receipt never sent" bugs.

The common thread: any workflow where "row exists but job is missing" would be a data integrity bug.

## Delivery semantics

Transactional enqueue guarantees the job enters the queue if and only if the transaction commits. It does not guarantee single execution.

Soniq provides **at-least-once delivery**. If a worker crashes after executing the job but before marking it done, stale worker recovery will re-queue it. Design your job functions to be idempotent -- use upserts, deduplication keys, or check-before-act patterns for side effects like sending emails or charging payments.

## What transactional enqueue does NOT guarantee

- **Single execution.** The guarantee applies to enqueue only. Re-execution after worker crashes is still possible.
- **Rollback after commit.** Once committed, the job is in the queue. You can cancel it with `eq.cancel_job(job_id)`, but a fast worker might pick it up first.

## Global API

The same pattern works with the global API:

```python
import soniq

pool = await soniq.get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders ...")
        await soniq.enqueue(
            "myapp.tasks.send_invoice",
            args={"order_id": order_id},
            connection=conn,
        )
```

> **Note:** Transactional enqueue requires PostgreSQL. It is not available with the SQLite or Memory backends. Calling `enqueue(..., connection=conn)` on a non-PostgreSQL backend raises a `ValueError`.
