# Scheduling & Recurring Jobs

Enable scheduling features:

```bash
export ELEPHANTQ_SCHEDULING_ENABLED=true
```

## Basic scheduling workflow

### One-off scheduling

```python
import elephantq
from datetime import timedelta

@elephantq.job()
async def send_email(to: str):
    pass

# schedule in 10 minutes
await elephantq.schedule(send_email, run_in=timedelta(minutes=10), to="user@example.com")
```

### Transactional scheduling

If you need the schedule to be part of an existing database transaction, pass a connection:

```python
pool = await elephantq.get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        await elephantq.schedule(send_email, run_in=60, connection=conn, to="user@example.com")
```

### Recurring (cron)

```python
import elephantq

@elephantq.job()
async def daily_report():
    pass

await elephantq.features.recurring.cron("0 9 * * *").schedule(daily_report)
```

### Recurring (interval)

```python
elephantq.features.recurring.every(10).minutes().schedule(daily_report)
```

## Fluent scheduling builders

When your workflow needs richer expressions, use the builders under `elephantq.features.recurring` and `elephantq.features.scheduling`. They still rely on the same `@elephantq.job()` registry, but group scheduling metadata into reusable helpers.

### Fluent recurring builder

```python
await elephantq.features.recurring.every(1).days().at("09:00").high_priority().schedule(daily_report)
```

Behind the scenes the fluent builder collects cron/interval parameters, priority, queue overrides, and dependency tags, then calls `EnhancedRecurringManager.schedule_job()` to insert the row that drives the scheduler loop. All of those knobs respect the `ELEPHANTQ_SCHEDULING_ENABLED` flag.

### Job scheduler builder

```python
builder = elephantq.features.scheduling.schedule_job(cleanup_task)
await (
    builder.with_queue("maintenance")
    .with_priority(20)
    .with_timeout(120)
    .with_dependency("snapshot_job")
    .enqueue(connection=conn)
)
```

`JobScheduleBuilder` keeps a single configuration dict that eventually hits `JobScheduleBuilder._enqueue()`, so you can mutate the same builder before enqueuing in a transaction. It also wires retries, dependency checks, and timeout tracking into that transaction via `ElephantQ.core.queue`.

### Batch scheduling

```python
batch = elephantq.features.scheduling.create_batch()
batch.add(job_a).with_priority(30)
batch.add(job_b).with_queue("reports")
await batch.enqueue_all(batch_priority=10)
```

`BatchScheduler` tags every builder with `batch:<name>` metadata and enqueues all jobs in sequence, so queue stats and dashboard traces show the logical grouping. It still uses PostgreSQL transactions for each enqueue call.

## Scheduler process

```bash
elephantq scheduler
```

## Persistence

Recurring jobs are persisted in the database (table: `elephantq_recurring_jobs`) and are reloaded when the scheduler starts. If the scheduler restarts, previously scheduled recurring jobs resume automatically.
