# Migrating from RQ

A practical guide to replacing RQ (Redis Queue) with ElephantQ. Covers concept
mapping, code translation, and an honest look at trade-offs.

## Why migrate

- **No more Redis dependency.** ElephantQ uses PostgreSQL as its job store. If
  your app already talks to PostgreSQL, you can drop Redis from your stack entirely.
- **Async-native.** RQ workers are synchronous and block on each job. ElephantQ
  runs jobs as `async def` functions on an asyncio event loop with configurable
  concurrency.
- **Built-in scheduling, DLQ, retries, and dashboard.** RQ needs rq-scheduler,
  rq-dashboard, and manual retry logic as separate installs. ElephantQ ships
  all of these out of the box.
- **Transactional enqueue.** Enqueue a job inside the same PostgreSQL transaction
  that writes your application data. If the transaction rolls back, the job
  never exists.

## Concept mapping

| RQ | ElephantQ |
|----|-----------|
| `@job` decorator or `queue.enqueue(fn, ...)` | `@app.job()` + `await app.enqueue(fn, ...)` |
| `Queue("low", connection=redis)` | `@app.job(queue="low")` |
| `queue.enqueue_at(dt, fn, ...)` | `await app.schedule(fn, run_at=dt, ...)` |
| `queue.enqueue_in(timedelta, fn, ...)` | `await app.schedule(fn, run_at=now+delta, ...)` |
| `rq worker` | `elephantq start` |
| rq-dashboard | `elephantq dashboard` |
| rq-scheduler | `@elephantq.periodic()` + `elephantq scheduler` |
| `FailedJobRegistry` | Dead-letter queue (`elephantq dead-letter list`) |
| `job.retry()` | `await app.retry_job(job_id)` |
| Redis connection URL | PostgreSQL connection URL |

## Code translation

### Job definition

**RQ:**

```python
import redis
from rq import Queue
from rq.decorators import job

conn = redis.Redis()

@job("default", connection=conn, timeout=300)
def process_image(image_id):
    img = load_image(image_id)
    return resize(img)
```

**ElephantQ:**

```python
from elephantq import ElephantQ

app = ElephantQ(database_url="postgresql://localhost/myapp")

@app.job(queue="default", timeout=300)
async def process_image(image_id: int):
    img = await load_image(image_id)
    return await resize(img)
```

Key differences: jobs are `async def`, and you pass keyword arguments instead
of positional ones.

### Enqueuing a job

**RQ:**

```python
from rq import Queue

q = Queue("default", connection=redis.Redis())

# Immediate
q.enqueue(process_image, 42)

# Delayed
from datetime import timedelta
q.enqueue_in(timedelta(minutes=5), process_image, 42)

# Scheduled at a specific time
from datetime import datetime
q.enqueue_at(datetime(2025, 1, 1, 9, 0), process_image, 42)
```

**ElephantQ:**

```python
# Immediate
await app.enqueue(process_image, image_id=42)

# Scheduled at a specific time
from datetime import datetime, timedelta

run_at = datetime.utcnow() + timedelta(minutes=5)
await app.schedule(process_image, run_at=run_at, image_id=42)
```

### Transactional enqueue (new capability)

This is not possible with RQ and Redis. With ElephantQ you can guarantee that a
job only exists if the associated database write succeeds:

```python
pool = await app.get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("UPDATE images SET status=$1 WHERE id=$2", "processing", image_id)
        await app.enqueue(process_image, connection=conn, image_id=image_id)
# If the transaction fails, the job is never created.
```

### Queue priority

**RQ:**

```python
high = Queue("high", connection=redis.Redis())
low = Queue("low", connection=redis.Redis())

# Worker processes high before low
# rq worker high default low
```

**ElephantQ:**

```python
@app.job(queue="high", priority=1)
async def urgent_task(data: str):
    ...

@app.job(queue="low", priority=10)
async def background_task(data: str):
    ...
```

```bash
elephantq start --queues high,default,low
```

### Retries

**RQ:**

```python
from rq import Retry

q.enqueue(process_image, 42, retry=Retry(max=3, interval=60))
```

**ElephantQ:**

```python
@app.job(max_retries=3)
async def process_image(image_id: int):
    ...
```

Retry backoff is handled automatically by ElephantQ.

### Recurring / periodic jobs

**rq-scheduler:**

```python
from rq_scheduler import Scheduler

scheduler = Scheduler(connection=redis.Redis())
scheduler.cron(
    "0 9 * * *",
    func=daily_report,
    queue_name="default",
)
```

**ElephantQ:**

```python
import elephantq

@elephantq.periodic(cron="0 9 * * *")
async def daily_report():
    await generate_and_send_report()
```

Then run the scheduler:

```bash
elephantq scheduler
```

### Checking job status

**RQ:**

```python
from rq.job import Job

job = Job.fetch("some-job-id", connection=redis.Redis())
print(job.get_status())  # "queued", "started", "finished", "failed"
print(job.result)
```

**ElephantQ:**

```python
status = await app.get_job_status("some-job-id")
result = await app.get_result("some-job-id")
```

### Failed jobs

**RQ:**

```python
from rq import Queue
from rq.registry import FailedJobRegistry

registry = FailedJobRegistry(queue=Queue("default", connection=redis.Redis()))
for job_id in registry.get_job_ids():
    job = Job.fetch(job_id, connection=redis.Redis())
    job.requeue()
```

**ElephantQ:**

```bash
# List failed jobs
elephantq dead-letter list

# Retry a specific job
elephantq dead-letter retry <job-id>

# Retry all
elephantq dead-letter retry-all
```

Or programmatically:

```python
await app.retry_job("some-job-id")
```

## What you gain

- **No Redis.** One fewer service to run, monitor, and back up.
- **Async concurrency.** A single ElephantQ worker can process multiple jobs
  concurrently. RQ workers process one job at a time (you scale by running
  more worker processes).
- **Transactional enqueue.** Atomically enqueue jobs with your database writes.
- **Built-in retries with backoff.** No extra `Retry` import or configuration.
- **Built-in scheduling.** No separate rq-scheduler process or package.
- **Built-in dashboard.** No separate rq-dashboard install.
- **Built-in dead-letter queue.** Failed jobs are automatically captured with
  full error details, and can be retried from the CLI or dashboard.
- **Job priorities.** Numeric priority on individual jobs, not just queue ordering.

## What you lose

Be honest about whether these matter for your use case:

- **Redis ecosystem.** If you use Redis for caching, pub/sub, or rate limiting
  alongside RQ, dropping Redis means finding alternatives for those features.
  (You may still want Redis for caching even after switching to ElephantQ.)
- **Synchronous job support.** RQ runs plain `def` functions. ElephantQ
  requires `async def`. Blocking code needs to be wrapped in
  `asyncio.to_thread()`:

  ```python
  @app.job()
  async def legacy_sync_work(data: str):
      await asyncio.to_thread(blocking_function, data)
  ```

- **Simplicity of RQ's mental model.** RQ is deliberately minimal. ElephantQ
  has more features, which means more to learn. If you only need
  "enqueue a function and run it later," RQ's simplicity is a real strength.

## Step-by-step migration checklist

1. **Install ElephantQ.**

   ```bash
   pip install elephantq
   ```

2. **Set up the database.**

   ```bash
   export ELEPHANTQ_DATABASE_URL="postgresql://localhost/myapp"
   elephantq setup
   ```

3. **Create your ElephantQ app instance.**

   ```python
   from elephantq import ElephantQ
   app = ElephantQ(database_url="postgresql://localhost/myapp")
   ```

4. **Rewrite job functions.** Convert `def` to `async def`. Replace positional
   arguments with keyword arguments. Add `@app.job()` decorators.

5. **Replace `queue.enqueue()` calls.** Search your codebase for
   `.enqueue(` and replace with `await app.enqueue()`. Replace
   `enqueue_at` / `enqueue_in` with `await app.schedule()`.

6. **Move rq-scheduler cron jobs to `@elephantq.periodic()`.** Each cron
   entry becomes a decorated function.

7. **Replace `rq worker` with `elephantq start`.**

   ```bash
   elephantq start --concurrency 4 --queues default,low
   ```

8. **Replace rq-dashboard with `elephantq dashboard`.**

   ```bash
   elephantq dashboard
   ```

9. **Migrate failed job handling.** Replace `FailedJobRegistry` usage with
   `elephantq dead-letter` CLI commands or `await app.retry_job()`.

10. **Remove Redis from your infrastructure** (if nothing else depends on it).
    Update your Docker Compose, Kubernetes manifests, or deployment configs.

11. **Run your test suite.** ElephantQ has a memory backend for testing:

    ```python
    app = ElephantQ(backend="memory")
    ```

## Tips for a smooth migration

- **Wrap blocking code early.** Before migrating, identify synchronous
  functions that do I/O (HTTP calls, file operations, subprocess). Wrap them
  with `asyncio.to_thread()` so the async conversion goes smoothly.
- **Migrate one queue at a time.** Run RQ and ElephantQ side by side. Move
  the lowest-risk queue first and verify it works before moving on.
- **Watch your PostgreSQL connection count.** Each ElephantQ worker uses a
  connection pool. Set `ELEPHANTQ_POOL_MAX_SIZE` based on your concurrency
  and available PostgreSQL connections.
