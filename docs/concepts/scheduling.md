# Scheduling

Soniq supports one-off delayed jobs and recurring schedules.

## Setup

```bash
pip install soniq[scheduling]   # installs croniter for cron expressions
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

### `@app.periodic()` decorator

The single decorator that registers a job and its schedule together. The scheduler process picks up all `@periodic` functions automatically.

```python
import soniq
from datetime import timedelta
from soniq import cron, daily, every, monthly, weekly

# Cron expression (string or builder).
@soniq.periodic(cron=daily().at("09:00"), name="reports.daily")
async def daily_sales_report():
    ...

# Plain cron strings work too.
@soniq.periodic(cron="0 9 * * 1-5", name="weekday.morning")
async def weekday_summary():
    ...

# Interval (cron has no sub-minute resolution; pass a timedelta).
@soniq.periodic(every=timedelta(seconds=30), name="metrics.flush")
async def flush_metrics():
    ...
```

`@app.periodic` accepts the same kwargs as `@app.job` (`name`, `queue`, `priority`, `retries`, `validate`, etc.) - it is `@app.job` plus the periodic stamp. `name` is optional and falls back to `f"{module}.{qualname}"`.

### Cron-string builders

`soniq.schedules` exposes a small DSL that returns plain cron strings - a readability layer over the 5-field grammar:

```python
from datetime import timedelta
from soniq import cron, daily, every, monthly, weekly

every(5).minutes()                 # "*/5 * * * *"
every(2).hours()                   # "0 */2 * * *"
every(30).seconds()                # timedelta(seconds=30) - use with every=
daily().at("09:00")                # "0 9 * * *"
weekly().on("monday").at("09:00")  # "0 9 * * 1"
monthly().on_day(15).at("12:00")   # "0 12 15 * *"
cron("*/15 * * * *")               # identity passthrough
```

Each terminal returns a `str`, so `cron=daily().at("09:00")` works without `.expr`.

### Imperative API for dynamic schedules

When a schedule is computed at runtime (per-tenant, per-feature-flag, ...), use `app.scheduler.add(...)`:

```python
await app.scheduler.add(
    target=cleanup,                # callable, registered task name, or use name=
    cron="0 9 * * *",
    args={"region": "US"},
    queue="reports",
    priority=10,
)

await app.scheduler.pause("reports.daily")
await app.scheduler.resume("reports.daily")
await app.scheduler.remove("reports.daily")

schedules = await app.scheduler.list(status="active")
sched = await app.scheduler.get("reports.daily")
```

Schedules are keyed by the resolved task name. Calling `add()` again with the same name updates the schedule in place rather than creating a duplicate.

## Scheduler process

Recurring jobs need a running scheduler to check for due jobs and enqueue them. Start it separately from your worker:

```bash
soniq scheduler --check-interval 60
```

The scheduler checks for due recurring jobs every `--check-interval` seconds (default: 60). When a job is due, it enqueues a new instance into the regular job queue. Workers then pick it up as usual.

Multiple scheduler instances are safe. Soniq elects a single tick leader via a Postgres advisory lock per interval, and the per-job claim runs as an atomic compare-and-swap on `next_run` inside a single transaction with the enqueue: if anyone wins the race, exactly one job lands in the queue.

### Checking scheduler status

```bash
soniq scheduler --status
```

### Programmatic start

```python
await app.scheduler.start(check_interval=30)
# ...later...
await app.scheduler.stop()
```

## Persistence

Recurring job schedules are stored in the `soniq_recurring_jobs` table on Postgres. If the scheduler restarts, it reloads all active schedules and resumes where it left off. No schedules are lost. The Memory and SQLite backends keep schedules in-process (single-writer, useful for tests and local dev).
