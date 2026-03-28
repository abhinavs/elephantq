# Migrating from Celery

A practical guide to replacing Celery with ElephantQ. Covers concept mapping,
code translation, and an honest look at what you gain and lose.

## Why migrate

- **No more Redis/RabbitMQ infrastructure.** ElephantQ uses PostgreSQL as its
  broker and result backend. If you already run PostgreSQL, you have zero new
  infrastructure to deploy, monitor, or pay for.
- **Transactional enqueue.** Enqueue a job inside the same database transaction
  that writes your application data. If the transaction rolls back, the job
  never exists. This is impossible with a Redis broker.
- **Simpler ops.** One database to back up, one connection string to configure,
  one system to monitor.
- **Async-native.** No thread pool workarounds. Jobs are plain `async def`
  functions running on an asyncio event loop.

## Concept mapping

| Celery | ElephantQ |
|--------|-----------|
| `@app.task` | `@app.job()` |
| `task.delay(*args)` | `await app.enqueue(task, **kwargs)` |
| `task.apply_async(args, countdown=60)` | `await app.schedule(task, run_at=dt, **kwargs)` |
| `celery.conf` / `celeryconfig.py` | `ELEPHANTQ_*` env vars or `ElephantQ()` constructor kwargs |
| Celery Beat | `@app.periodic(cron="...")` + `elephantq scheduler` |
| Flower | `elephantq dashboard` |
| Result backend (Redis/DB) | Built-in job results stored in PostgreSQL |
| Redis / RabbitMQ broker | PostgreSQL (your existing database) |
| `celery worker` | `elephantq start` |
| `celery inspect` | `elephantq status` |

## Code translation

### Task definition

**Celery:**

```python
from celery import Celery

app = Celery("myapp", broker="redis://localhost:6379/0")

@app.task(bind=True, max_retries=3)
def send_email(self, to, subject, body):
    # synchronous code
    smtp.send(to, subject, body)
```

**ElephantQ:**

```python
from elephantq import ElephantQ

app = ElephantQ(database_url="postgresql://localhost/myapp")

@app.job(max_retries=3, queue="email")
async def send_email(to: str, subject: str, body: str):
    await smtp.send(to, subject, body)
```

Key differences: jobs are `async def`, arguments are keyword-only, and there is
no `bind=True` / `self` parameter.

### Enqueuing a job

**Celery:**

```python
# Fire and forget
send_email.delay("a@b.com", "Hello", "World")

# With options
send_email.apply_async(
    args=("a@b.com", "Hello", "World"),
    countdown=60,
    queue="email",
)
```

**ElephantQ:**

```python
# Fire and forget
await app.enqueue(send_email, to="a@b.com", subject="Hello", body="World")

# Scheduled for the future
from datetime import datetime, timedelta
run_at = datetime.utcnow() + timedelta(seconds=60)
await app.schedule(send_email, run_at=run_at, to="a@b.com", subject="Hello", body="World")
```

### Transactional enqueue (new capability)

This pattern is impossible with Celery. With ElephantQ you can enqueue a job
inside the same PostgreSQL transaction that writes your data:

```python
async with app.get_pool() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders (id, ...) VALUES ($1, ...)", order_id)
        await app.enqueue(send_email, connection=conn, to=user.email, subject="Order confirmed", body="...")
# If the transaction fails, the job is never created.
```

### Periodic / recurring jobs

**Celery Beat:**

```python
# celeryconfig.py
from celery.schedules import crontab

app.conf.beat_schedule = {
    "daily-report": {
        "task": "tasks.daily_report",
        "schedule": crontab(hour=9, minute=0),
    },
}
```

**ElephantQ:**

```python
import elephantq

@elephantq.periodic(cron="0 9 * * *")
async def daily_report():
    await generate_and_send_report()
```

Then run the scheduler alongside your worker:

```bash
elephantq scheduler
```

### Hooks (replacing signals)

**Celery:**

```python
from celery.signals import task_prerun, task_failure

@task_prerun.connect
def on_task_start(sender, **kwargs):
    ...

@task_failure.connect
def on_task_fail(sender, exception, **kwargs):
    ...
```

**ElephantQ:**

```python
@app.before_job
async def on_start(job):
    ...

@app.on_error
async def on_fail(job, exception):
    ...
```

## What you gain

- **No Redis/RabbitMQ dependency.** Fewer moving parts, fewer failure modes.
- **Transactional enqueue.** Enqueue jobs atomically with your application writes.
- **Simpler deployment.** One database, one connection string.
- **Built-in dashboard.** `elephantq dashboard` replaces Flower with no extra install.
- **Built-in dead-letter queue.** Failed jobs land in the DLQ automatically.
- **Built-in scheduling.** No separate Beat process config file -- just decorate your functions.
- **Async-native.** No prefork pool, no thread surprises.

## What you lose

Be honest with yourself about whether these matter for your workload:

- **Extreme throughput.** Redis can push 10k--50k+ jobs/sec. PostgreSQL tops out
  lower (hundreds to low thousands/sec depending on hardware). If you are
  processing millions of jobs per minute, ElephantQ is not the right fit.
- **Cross-language workers.** Celery has Go, Node, and Rust clients.
  ElephantQ is Python-only.
- **Complex routing.** Topic exchanges, header-based routing, and multi-broker
  topologies have no equivalent in ElephantQ.
- **Canvas primitives.** Chains, groups, chords, and other composition patterns
  are not built in. You can compose jobs manually, but there is no declarative
  workflow engine.
- **Synchronous job support.** ElephantQ is async-only. Blocking code must be
  wrapped in `asyncio.to_thread()` or similar.

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

3. **Rewrite task decorators.** Replace `@app.task` with `@app.job()`. Convert
   functions to `async def`. Switch positional args to keyword args.

4. **Replace `.delay()` / `.apply_async()` calls.** Use `await app.enqueue()`
   and `await app.schedule()`. This is the most tedious part -- search your
   codebase for `.delay(` and `.apply_async(`.

5. **Move Beat schedules to `@elephantq.periodic()`.** Each scheduled task
   becomes a decorated function instead of a config dictionary.

6. **Migrate signal handlers to hooks.** Replace `@task_prerun.connect` with
   `@app.before_job`, `@task_postrun.connect` with `@app.after_job`, and
   `@task_failure.connect` with `@app.on_error`.

7. **Replace `celery worker` with `elephantq start`.**

   ```bash
   elephantq start --concurrency 4 --queues default,email
   ```

8. **Replace Flower with `elephantq dashboard`.**

   ```bash
   elephantq dashboard
   ```

9. **Remove Redis/RabbitMQ from your infrastructure.** Update your Docker
   Compose, Kubernetes manifests, Terraform configs, or whatever you use.
   Remove the broker URL from your environment.

10. **Run your test suite.** ElephantQ supports a memory backend for testing:

    ```python
    app = ElephantQ(backend="memory")
    ```

## Tips for a smooth migration

- **Migrate one queue at a time.** Run Celery and ElephantQ side by side during
  the transition. Move the lowest-risk queue first.
- **Keep Celery running** until you have verified every job type works in
  ElephantQ. There is no rush to cut over all at once.
- **Watch connection pool sizing.** Each ElephantQ worker holds open database
  connections. Set `ELEPHANTQ_POOL_MAX_SIZE` based on your concurrency and
  available PostgreSQL connections.
