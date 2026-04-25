# Scheduling

Soniq supports one-off delayed jobs and recurring schedules. Both require the scheduling feature flag.

## Setup

```bash
export SONIQ_SCHEDULING_ENABLED=true
pip install soniq[scheduling]  # installs croniter for cron expressions
```

## One-off scheduling

Schedule a job to run at a specific time or after a delay.

**Absolute time:**

```python
from datetime import datetime, timezone

await app.schedule(
    send_welcome_email,
    run_at=datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc),
    user_id=42,
)
```

**Relative delay:**

```python
from datetime import timedelta

# Using the global API
await soniq.schedule(send_report, run_in=timedelta(minutes=30), report_id="q4")
await soniq.schedule(send_report, run_in=600, report_id="q4")  # 600 seconds
```

Under the hood, `schedule()` calls `enqueue()` with a `scheduled_at` timestamp. The worker ignores scheduled jobs until their time arrives.

## Recurring jobs

### `@soniq.periodic()` decorator

The simplest way to define recurring jobs. Declares both the job and its schedule at definition time.

```python
import soniq

@soniq.periodic(cron="0 9 * * *")
async def daily_sales_report():
    ...

@soniq.periodic(every_minutes=10, queue="maintenance")
async def cleanup_temp_files():
    ...

@soniq.periodic(every_hours=2)
async def sync_inventory():
    ...
```

The scheduler picks up all `@periodic` functions automatically.

### Fluent builder API

For schedules defined at runtime, use the fluent builders:

```python
from soniq.features.recurring import every, daily, weekly, monthly, cron

# Every 5 minutes
await every(5).minutes().schedule(cleanup_temp_files)

# Every 2 hours, background priority
await every(2).hours().background().schedule(sync_inventory)

# Daily at 9:00 AM
await daily().at("09:00").schedule(daily_sales_report)

# Weekly on Monday at 9:00 AM, high priority
await weekly().on("monday").at("09:00").high_priority().schedule(weekly_digest)

# Monthly on the 1st at noon
await monthly().on_day(1).at("12:00").schedule(generate_invoice)

# Raw cron expression
await cron("*/15 * * * *").schedule(health_check)
```

The fluent API supports chaining priority and queue settings:

```python
await every(30).minutes().queue("reports").priority(10).schedule(generate_dashboard)
```

### `@recurring()` decorator

An alternative decorator that accepts shorthand expressions:

```python
from soniq.features.recurring import recurring

@recurring("*/15 * * * *")  # cron
async def health_check():
    ...

@recurring("1h", priority="high", queue="urgent")  # interval shorthand
async def urgent_cleanup():
    ...
```

Shorthand units: `s` (seconds), `m` (minutes), `h` (hours), `d` (days).

## JobScheduleBuilder

For advanced one-off scheduling with metadata, use `JobScheduleBuilder`:

```python
from soniq.features.scheduling import schedule_job

await (
    schedule_job(cleanup_temp_files)
    .in_hours(2)
    .with_priority(20)
    .in_queue("maintenance")
    .with_timeout(120)
    .with_tags("nightly", "cleanup")
    .enqueue()
)
```

Available methods:

| Method | Description |
| --- | --- |
| `.in_seconds()`, `.in_minutes()`, `.in_hours()`, `.in_days()` | Delay relative to now |
| `.at_time("2025-06-01T09:00:00")` | Specific datetime (ISO format or `HH:MM`) |
| `.with_priority(n)` | Override priority |
| `.in_queue("name")` | Override queue |
| `.with_retries(n)` | Set retry count |
| `.with_timeout(n)` | Set timeout in seconds |
| `.with_tags("a", "b")` | Add metadata tags |
| `.if_condition(lambda: ...)` | Skip unless predicate returns `True` |
| `.dry_run()` | Return config dict instead of enqueuing |

### Batch scheduling

Schedule multiple jobs together:

```python
from soniq.features.scheduling import create_batch

batch = create_batch()
batch.add(send_report, report_id="daily").with_priority(10)
batch.add(send_report, report_id="weekly").in_queue("reports")
job_ids = await batch.enqueue_all(batch_priority=5)
```

## Scheduler process

Recurring jobs need a running scheduler to check for due jobs and enqueue them. Start it separately from your worker:

```bash
soniq scheduler --check-interval 60
```

The scheduler checks for due recurring jobs every `--check-interval` seconds (default: 60). When a job is due, it enqueues a new instance into the regular job queue. Workers then pick it up as usual.

Multiple scheduler instances are safe. Soniq uses optimistic locking on the `next_run` timestamp -- only one scheduler claims each run.

### Checking scheduler status

```bash
soniq scheduler --status
```

### Programmatic start

```python
from soniq.features.recurring import start_recurring_scheduler

await start_recurring_scheduler(check_interval=30)
```

## Persistence

Recurring job schedules are stored in the `soniq_recurring_jobs` table. If the scheduler restarts, it reloads all active schedules and resumes where it left off. No schedules are lost.
