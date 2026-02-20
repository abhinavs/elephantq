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

When your workflow needs richer expressions, use the builders under `elephantq.features.recurring` or `elephantq.features.scheduling`. They still rely on the same `@elephantq.job()` registry, but collect scheduling metadata for km-of-the-day jobs.

### Fluent recurring builder

```python
await elephantq.features.recurring.every(1).days().at("09:00").high_priority().schedule(daily_report)
```

Behind the scenes the recurring builder builds cron/interval expressions and forwards them to `EnhancedRecurringManager.schedule_job()`. The same `ELEPHANTQ_SCHEDULING_ENABLED` flag gates the feature.

### JobScheduleBuilder (advanced workers)

```python
builder = elephantq.features.scheduling.schedule_job(cleanup_task)
await (
    builder.with_queue("maintenance")
    .with_priority(20)
    .with_timeout(120)
    .depends_on(latest_snapshot_job_id)
    .enqueue(connection=conn)
)
```

`JobScheduleBuilder` exposes the following methods:

| Method | Description |
| --- | --- |
| `.in_seconds()`, `.in_minutes()`, `.in_hours()`, `.in_days()` | Delay execution relative to now. |
| `.at_time()` | Interpret an ISO datetime or `HH:MM` string. |
| `.with_priority()` / `.in_queue()` | Override priority and queue for this run. |
| `.with_retries()` / `.with_timeout()` | Set retries or timeout metadata (stored alongside the job row). |
| `.with_tags()` | Add structured tags for dashboards or metadata. |
| `.depends_on()` | Declare other job IDs that must finish first (requires dependencies feature). |
| `.if_condition()` | Skip scheduling unless the provided predicate returns `True`. |
| `.dry_run()` | Return the final configuration dict instead of enqueuing (useful for previews). |

After calling `.enqueue()`, ElephantQ wires metadata, dependency tracking, and timeout propagation into the same transaction that writes the job row. `_scheduler_metadata` retains extra information for Observability APIs such as `elephantq.features.scheduling.get_job_metadata()`.

### Batch scheduling

```python
batch = elephantq.features.scheduling.create_batch()
batch.add(job_a).with_priority(30)
batch.add(job_b).with_queue("reports")
await batch.enqueue_all(batch_priority=10)
```

`BatchScheduler` tags every builder with `batch:<name>` metadata, enqueues them in sequence, and keeps each enqueue in Postgres transaction scope so all batch tags appear in queue stats and the dashboard.

### Unified `schedule()` helper

For simple delays you can call `elephantq.features.scheduling.schedule(job_func, when)` with:

- `when` as a `datetime` → schedules at the exact moment.
- `when` as an `int`/`float` → schedules after that many seconds.
- `when` as a `timedelta` → converts to seconds internally.

This helper still respects the scheduling feature flag and returns the job ID produced by the builder.

### Quick convenience helpers

These wrappers sit on top of `schedule_job()`:

- `schedule_high_priority()` → immediate `priority=1`, `queue="urgent"`.
- `schedule_background()` → immediate background job (`priority=100`, queue `background`).
- `schedule_urgent()` → another alias for urgent jobs.

Use them when you only need to change priority/queue without touching scheduled times.

### `@scheduled()` decorator

```python
@scheduled("delay", minutes=30, queue="maintenance")
async def cleanup_task():
    ...
```

The decorator stamps configuration metadata on the function via `func._schedule_config`. You can consume that metadata when wiring custom schedulers or just keep it for documentation.

## Scheduler process

```bash
elephantq scheduler
```

## Persistence

Recurring jobs are persisted in the database (table: `elephantq_recurring_jobs`) and are reloaded when the scheduler starts. If the scheduler restarts, previously scheduled recurring jobs resume automatically.
