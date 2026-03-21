# Instance API

ElephantQ offers two ways to interact with the queue: the **global API** (module-level functions) and the **instance API** (an `ElephantQ` object you create and manage).

## When to use each

| Scenario | Recommended API |
| --- | --- |
| Single database, simple app | Global API |
| FastAPI lifespan management | Instance API |
| Multiple databases or tenants | Instance API |
| Testing with isolated state | Instance API |
| Scripts and one-off jobs | Global API |

## Configuring the instance API

```python
from elephantq import ElephantQ

app = ElephantQ(database_url="postgresql://localhost/myapp")
```

The instance manages its own connection pool, job registry, and settings. You can run multiple instances side-by-side — each is fully isolated.

### Registering jobs

```python
@app.job(queue="emails", retries=3)
async def send_welcome(to: str):
    print(f"Sending to {to}")
```

### Enqueuing

```python
job_id = await app.enqueue(send_welcome, to="user@example.com")
```

### Running a worker

```python
await app.run_worker(concurrency=4, queues=["default", "emails"])
```

## FastAPI lifespan integration

The instance API pairs naturally with FastAPI's lifespan pattern. Initialize ElephantQ when the app starts and shut it down cleanly when it stops.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from elephantq import ElephantQ

eq = ElephantQ(database_url="postgresql://localhost/myapp")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await eq.setup()
    yield
    await eq.shutdown()

app = FastAPI(lifespan=lifespan)

@eq.job()
async def process_order(order_id: int):
    ...

@app.post("/orders")
async def create_order(order_id: int):
    await eq.enqueue(process_order, order_id=order_id)
    return {"queued": True}
```

Run the worker in a separate process:

```bash
ELEPHANTQ_DATABASE_URL="postgresql://localhost/myapp" \
ELEPHANTQ_JOBS_MODULES="app.jobs" \
elephantq start --concurrency 4
```

## Multiple-database setups

Each `ElephantQ` instance points at its own database. Use this when you have per-tenant databases or separate read/write pools.

```python
tenant_a = ElephantQ(database_url="postgresql://localhost/tenant_a")
tenant_b = ElephantQ(database_url="postgresql://localhost/tenant_b")

@tenant_a.job()
async def job_for_a():
    ...

@tenant_b.job()
async def job_for_b():
    ...

# Each instance enqueues into its own database
await tenant_a.enqueue(job_for_a)
await tenant_b.enqueue(job_for_b)
```

## Accessing the pool

```python
pool = await app.get_pool()
async with pool.acquire() as conn:
    # Use for transactional enqueue or direct queries
    ...
```

## See also

- [docs/transactional-enqueue.md](transactional-enqueue.md) — atomic enqueue with `connection=conn`
- [docs/getting-started.md](getting-started.md) — global API quickstart
