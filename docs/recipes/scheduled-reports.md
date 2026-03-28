# Recipe: Scheduled Reports

A pattern for generating recurring reports on a cron schedule using `@elephantq.periodic`.

## The job

```python
import elephantq

@elephantq.periodic(cron="0 9 * * 1")  # Every Monday at 9 AM
async def weekly_sales_report():
    start, end = get_last_week_range()
    data = await fetch_sales_data(start, end)
    report = generate_report(data)
    await send_report(
        to="team@example.com",
        subject=f"Sales report: {start:%b %d} - {end:%b %d}",
        attachment=report,
    )
```

The `@elephantq.periodic` decorator registers both the job and its schedule. The scheduler picks it up automatically.

## Enabling the scheduler

The scheduler is a separate process that creates job instances on schedule. Enable it and run it alongside your worker:

```bash
# Required environment variable
export ELEPHANTQ_SCHEDULING_ENABLED=true

# Terminal 1: Scheduler (creates jobs on schedule)
elephantq scheduler

# Terminal 2: Worker (processes created jobs)
ELEPHANTQ_JOBS_MODULES="app.reports" elephantq start
```

The scheduler checks registered periodic jobs and enqueues them when their schedule fires. The worker processes them like any other job.

## Schedule options

Cron expressions for specific times:

```python
@elephantq.periodic(cron="0 9 * * *")       # Daily at 9 AM
async def daily_digest():
    ...

@elephantq.periodic(cron="0 0 1 * *")       # First of every month
async def monthly_summary():
    ...

@elephantq.periodic(cron="*/15 * * * *")     # Every 15 minutes
async def check_stale_orders():
    ...
```

Interval helpers for simpler cases:

```python
@elephantq.periodic(every_minutes=10)
async def cleanup_temp_files():
    ...

@elephantq.periodic(every_hours=1)
async def sync_inventory():
    ...

@elephantq.periodic(every_seconds=30)
async def health_ping():
    ...
```

You can combine `@periodic` with any `@job` option:

```python
@elephantq.periodic(cron="0 9 * * 1", queue="reports", max_retries=2, timeout=300)
async def weekly_report():
    ...
```

## Instance API

With the Instance API, define periodic jobs on your `ElephantQ` instance. Note that `periodic` is only available on the global API. Register the job normally and configure the schedule separately, or use the global decorator:

```python
import elephantq
from elephantq import ElephantQ

eq = ElephantQ(database_url="postgresql://localhost/myapp")

@elephantq.periodic(cron="0 9 * * 1")
async def weekly_report():
    data = await fetch_weekly_data()
    await send_report(data)
```

## Complete example

```python
# app/reports.py
import elephantq

@elephantq.periodic(cron="0 9 * * 1", queue="reports", timeout=300)
async def weekly_sales_report():
    start, end = get_last_week_range()
    data = await fetch_sales_data(start, end)
    report = generate_csv(data)
    await upload_to_s3(report, key=f"reports/sales-{start:%Y%m%d}.csv")
    await send_email(
        to="team@example.com",
        subject=f"Weekly sales: {start:%b %d} - {end:%b %d}",
        attachment_url=report.url,
    )


@elephantq.periodic(cron="0 6 * * *", queue="reports")
async def daily_error_digest():
    errors = await fetch_errors_since_yesterday()
    if not errors:
        return  # Nothing to report
    await send_email(
        to="oncall@example.com",
        subject=f"Error digest: {len(errors)} errors",
        body=format_error_summary(errors),
    )
```

```bash
# Run everything
ELEPHANTQ_DATABASE_URL="postgresql://localhost/myapp" \
ELEPHANTQ_SCHEDULING_ENABLED=true \
ELEPHANTQ_JOBS_MODULES="app.reports"

# In separate terminals:
elephantq scheduler
elephantq start --queues reports --concurrency 2
```
