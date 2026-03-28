# FastAPI Integration

ElephantQ's Instance API is the natural fit for FastAPI applications. You get explicit lifecycle control, clean dependency injection, and easy testing.

## Setup

Create an `ElephantQ` instance and wire it into FastAPI's lifespan:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from elephantq import ElephantQ

eq = ElephantQ(database_url="postgresql://localhost/myapp")

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await eq.close()     # closes the connection pool

app = FastAPI(lifespan=lifespan)
```

The connection pool initializes lazily on first use (first `enqueue()` call). `close()` shuts it down cleanly when the process exits.

!!! warning "Run migrations at deploy time, not app startup"
    Use `elephantq setup` in your deploy pipeline (CI step, Dockerfile entrypoint, k8s init container) — not in the lifespan. Running migrations on every app boot creates race conditions when multiple replicas start simultaneously.

## Defining jobs

Register jobs with the `@eq.job()` decorator. These are regular async functions:

```python
@eq.job(queue="emails", max_retries=3)
async def send_welcome(user_id: int):
    user = await get_user(user_id)
    await send_email(to=user.email, template="welcome")
```

## Enqueuing from route handlers

Call `eq.enqueue()` from any route:

```python
@app.post("/users")
async def create_user(name: str, email: str):
    user = await save_user(name=name, email=email)
    await eq.enqueue(send_welcome, user_id=user.id)
    return {"id": user.id, "queued": True}
```

## Running the worker

Workers run as a separate process. Point them at the module where your jobs are defined:

```bash
ELEPHANTQ_DATABASE_URL="postgresql://localhost/myapp" \
ELEPHANTQ_JOBS_MODULES="app.jobs" \
elephantq start --concurrency 4
```

`ELEPHANTQ_JOBS_MODULES` is a comma-separated list of Python modules. The worker imports them on startup so it discovers all `@eq.job()` decorators.

You can also limit a worker to specific queues:

```bash
elephantq start --concurrency 2 --queues emails,notifications
```

## Complete example

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from elephantq import ElephantQ

eq = ElephantQ(database_url="postgresql://localhost/myapp")

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await eq.close()

app = FastAPI(lifespan=lifespan)


@eq.job(queue="emails", max_retries=3, retry_delay=30)
async def send_welcome(user_id: int):
    user = await get_user(user_id)
    await send_email(to=user.email, template="welcome")


@eq.job(queue="default")
async def process_order(order_id: int):
    order = await get_order(order_id)
    await fulfill(order)


@app.post("/users")
async def create_user(name: str, email: str):
    user = await save_user(name=name, email=email)
    await eq.enqueue(send_welcome, user_id=user.id)
    return {"id": user.id}


@app.post("/orders")
async def create_order(product_id: int, quantity: int):
    order = await save_order(product_id=product_id, quantity=quantity)
    await eq.enqueue(process_order, order_id=order.id)
    return {"order_id": order.id}
```

Run the API and worker separately:

```bash
# Terminal 1: API server
uvicorn app.main:app --reload

# Terminal 2: Worker
ELEPHANTQ_DATABASE_URL="postgresql://localhost/myapp" \
ELEPHANTQ_JOBS_MODULES="app.main" \
elephantq start --concurrency 4
```

## Global API vs Instance API

| Scenario | Recommended |
| --- | --- |
| FastAPI or any ASGI app | Instance API |
| Multiple databases or tenants | Instance API |
| Testing with isolated state | Instance API |
| Simple scripts and CLIs | Global API |
| Quick prototyping | Global API |

The Instance API gives you explicit control over initialization and shutdown. The Global API uses a shared singleton under the hood, which is convenient for scripts but awkward when you need precise lifecycle management.

In FastAPI apps, always use the Instance API. It integrates cleanly with the lifespan pattern and avoids hidden global state.

## Multiple instances

Each `ElephantQ` instance is fully isolated with its own connection pool and job registry. This is useful for multi-tenant setups:

```python
tenant_a = ElephantQ(database_url="postgresql://localhost/tenant_a")
tenant_b = ElephantQ(database_url="postgresql://localhost/tenant_b")

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await tenant_a.close()
    await tenant_b.close()
```

## Accessing the connection pool

For advanced use cases like [transactional enqueue](transactional-enqueue.md), you can access the underlying connection pool:

```python
pool = await eq.get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders ...")
        await eq.enqueue(send_invoice, connection=conn, order_id=order_id)
```
