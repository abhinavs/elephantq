# Migrate from Celery

This guide is for teams running `Celery + Redis` (or `Celery + RabbitMQ`) who want to move to Soniq. We assume you have a working Celery setup and you understand its core ideas: tasks, brokers, result backends, and Beat for scheduled jobs.

The migration is gradual. You can run Celery and Soniq side-by-side, move job definitions one at a time, and decommission Celery once the queue drains. The compatibility mode below is what makes that possible.

## Concept map

| Celery | Soniq | Notes |
|---|---|---|
| `@celery.task` | `@app.job()` | Soniq's native API. The `()` is optional. |
| `task.delay(arg)` | `await app.enqueue(task, arg=arg)` | Soniq is async-native. Enqueue must be awaited. |
| `task.apply_async(countdown=30)` | `await app.enqueue(task, delay=30)` | Pass `delay=` (seconds) or `scheduled_at=datetime`. |
| `task.apply_async(queue="emails")` | `await app.enqueue(task, queue="emails")` | Same idea, keyword arg. |
| `@celery.task(bind=True)` -> `self` | `ctx: JobContext` parameter | Injected automatically when the handler accepts it. |
| `celery beat` + `@periodic_task` | `soniq scheduler` + `@app.periodic(cron=...)` | Run the scheduler as a sidecar process. |
| `celery -A myapp worker` | `soniq start` | Reads `SONIQ_DATABASE_URL` and `SONIQ_JOBS_MODULES`. |
| `CELERY_BROKER_URL` | `SONIQ_DATABASE_URL` | No broker needed. Postgres handles both rows and notifications. |
| `CELERY_RESULT_BACKEND` | Built-in. No separate config. | Job results are stored in `soniq_jobs.result_data`. |
| Flower | `soniq dashboard` | Web UI for queues, workers, dead-letter. |
| `task.retry(exc=e)` | Just raise the exception | Soniq retries automatically based on the job's `max_retries` and retry policy. |
| `chain`, `group`, `chord` | Not supported | Soniq does not have workflow orchestration. See "What you give up" below. |

## What you gain

- **Transactional enqueue.** Insert the job in the same transaction as your business write. If the transaction rolls back, the job never existed. Celery cannot do this because the broker is a separate service.
- **One less moving part.** No Redis, no RabbitMQ. Your `DATABASE_URL` is your queue.
- **Async workers.** If you're on FastAPI / Starlette / async SQLAlchemy, your jobs use the same async runtime as your web app.
- **Dead-letter queue, built in.** No setup. Failed jobs that exhaust retries land in `soniq_dead_letter_jobs` for inspection and replay.
- **Dashboard, built in.** `pip install soniq[dashboard]` and `soniq dashboard`. No separate Flower deployment.

## What you give up

We want to be plain about this:

- **Sustained 10k+ jobs/sec.** Postgres row locking (`SELECT ... FOR UPDATE SKIP LOCKED`) is excellent but not infinite. If your throughput needs are very high, Celery + Redis remains a better fit.
- **Cross-language consumers.** Soniq is Python-only. Celery has clients in many languages.
- **DAG-based workflow orchestration.** Celery's `chain`, `group`, and `chord` primitives have no Soniq equivalent. If you rely on them, look at Prefect or Airflow before considering Soniq.

## Compatibility mode

For teams who want to migrate gradually rather than running a flag day, Soniq ships a thin compatibility subclass that aliases `@app.task` to `@app.job`. It exists in the `soniq.celery` submodule -- the import line is intentionally distinct so every file using it advertises that it is mid-migration.

```python
# Step 1: swap the import. Existing decorators keep working.
from soniq.celery import Soniq          # instead of: from soniq import Soniq

app = Soniq(database_url=os.environ["SONIQ_DATABASE_URL"])

@app.task()  # alias for @app.job() -- works during migration
async def send_welcome(to: str):
    print(f"Welcome to {to}")
```

When you're done migrating a file, change two lines:

```python
from soniq import Soniq                  # remove .celery

@app.job()                                # remove .task -> .job
async def send_welcome(to: str):
    ...
```

### What is and is not aliased

Aliased: `@app.task` and `@app.task(...)`.

**Not aliased: `.delay(...)` and `.apply_async(...)`.** These methods would hide the `await` that Soniq requires, which creates subtle async bugs (an enqueue that returns a coroutine you forget to await). Replace those call sites:

```python
# Before
send_welcome.delay("dev@example.com")
send_welcome.apply_async(args=["dev@example.com"], countdown=30)

# After
await app.enqueue(send_welcome, to="dev@example.com")
await app.enqueue(send_welcome, delay=30, to="dev@example.com")
```

The migration guide on the website intentionally skips a `.delay` shim. The friction is the point: it surfaces exactly what changed and prevents bugs you'd otherwise discover at runtime.

## Migration sequence

The pattern that has worked best for migrating production fleets:

### 1. Install Soniq alongside Celery

```bash
pip install soniq
```

Both libraries can coexist. Don't remove Celery yet.

### 2. Run `soniq setup`

```bash
SONIQ_DATABASE_URL=postgresql://... soniq setup
```

This creates `soniq_jobs`, `soniq_workers`, `soniq_dead_letter_jobs`, and the recurring-job tables. It is idempotent and safe to re-run on every deploy.

### 3. Start Soniq workers next to Celery workers

```bash
SONIQ_JOBS_MODULES=app.jobs soniq start --concurrency 4
```

At this point you have Celery workers consuming from Redis and Soniq workers consuming from Postgres. Both fleets sit idle for jobs that are not theirs.

### 4. Move job definitions one at a time

Open a job module. Change two things:

```python
# Before
from celery import Celery
celery_app = Celery("myapp", broker="redis://...", backend="redis://...")

@celery_app.task
def send_welcome(to: str):
    ...

# After
from soniq.celery import Soniq
app = Soniq(database_url=os.environ["SONIQ_DATABASE_URL"])

@app.task()
async def send_welcome(to: str):
    ...
```

Then update every call site that enqueues that job:

```python
# Before
send_welcome.delay("dev@example.com")

# After
await app.enqueue(send_welcome, to="dev@example.com")
```

Deploy. The job is now flowing through Postgres instead of Redis. Repeat for the next job.

### 5. Convert async correctness as you go

Celery's tasks are typically synchronous. Soniq prefers `async def` handlers. You can keep sync handlers (Soniq runs them on a bounded thread pool) but the win is when you make them `async def` and use async DB libraries. This is also the moment to enable transactional enqueue -- see the [transactional enqueue guide](../guides/transactional-enqueue.md).

### 6. Move recurring jobs

Celery Beat tasks become `@app.periodic(cron=...)`. Run `soniq scheduler` as a separate sidecar process. Only one scheduler instance does any work at a time -- multiple replicas coordinate via a Postgres advisory lock, so it's safe to run more than one for redundancy.

```python
@app.periodic(cron="0 9 * * *", name="daily.report")
async def daily_report():
    ...
```

```bash
SONIQ_JOBS_MODULES=app.jobs soniq scheduler
```

### 7. Drain Celery and decommission

Stop enqueueing into Celery. Wait until Celery's queues empty (Flower's "Active" count hits zero, then "Reserved" drains). Stop Celery workers. Remove `celery` from `pyproject.toml`. Remove the Redis instance if nothing else uses it.

You can now also switch the import back to `from soniq import Soniq` and rename `@app.task()` to `@app.job()`. Or do this as a final cleanup PR after the production rollout has soaked.

## Common gotchas

- **`@app.job` requires unique task names.** If two job functions register the same name (e.g. both have `name="send_welcome"`), registration raises. Celery's behaviour was to last-write-wins. We chose loud errors over silent overwrites.
- **`enqueue()` is `await`-only.** Calling it without `await` returns a coroutine object that is never scheduled. The job never runs and you get no error. This is the single most common mistake when migrating from Celery's `.delay()`. If you're seeing "enqueue worked but the job never ran," check for missed `await`.
- **`SONIQ_JOBS_MODULES` must be set.** The CLI worker needs to know which modules to import to populate the registry. See [Job module discovery](../getting-started/installation.md#job-module-discovery).
- **PgBouncer in transaction-pooling mode breaks the recurring scheduler.** The advisory-lock leader guard requires the lock to persist across statements on a session. Switch to session-pooling for the scheduler connection (a single direct connection is fine).

## See also

- [Quickstart](../quickstart.md) -- run a Soniq job in five minutes if you want to try the API before committing to the migration
- [Transactional enqueue](../guides/transactional-enqueue.md) -- the headline feature Celery cannot match
- [FastAPI guide](../guides/fastapi.md) -- if your producer is FastAPI
- [Going to production](../production/going-to-production.md) -- before flipping the switch
