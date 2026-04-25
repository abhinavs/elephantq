# Jobs

Everything about defining, enqueueing, scheduling, and inspecting jobs.


## @app.job decorator

Registers a function as a job. Works on both instance and global APIs. Both `@app.job` (no parens) and `@app.job(...)` (with kwargs) are accepted.

```python
# Instance API
app = Soniq(database_url="postgresql://localhost/myapp")

@app.job
async def send_email(to: str, subject: str, body: str):
    ...

# Global API
import soniq

@soniq.job
async def send_email(to: str, subject: str, body: str):
    ...
```

### Parameters

All parameters are optional.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str \| None` | `None` | Explicit task name. When omitted, derived from `f"{module}.{qualname}"` (Celery-style). Pass an explicit value for cross-service deployments where the name is a wire-protocol identifier. |
| `retries` | `int` | `3` | Maximum retry attempts on failure. Alias: `max_retries`. |
| `priority` | `int` | `100` | Lower number = higher priority. Range: 1--1000. |
| `queue` | `str` | `"default"` | Queue name for this job. |
| `unique` | `bool` | `False` | Deduplicate by arguments hash. If a matching job is already queued, the enqueue is skipped. |
| `retry_delay` | `int \| float \| list[int \| float]` | `0` | Seconds to wait before each retry. Pass a list to set per-attempt delays (e.g. `[1, 5, 30]`). |
| `retry_backoff` | `bool` | `False` | Apply exponential backoff to `retry_delay`. |
| `retry_max_delay` | `int \| float \| None` | `None` | Cap on retry delay in seconds. |
| `timeout` | `int \| float \| None` | `None` | Per-job timeout in seconds. `None` uses the global `job_timeout` setting (default 300s). |
| `validate` | `type[BaseModel] \| None` | `None` | Pydantic model for argument validation at enqueue time. Alias: `args_model`. |

```python
@app.job(
    retries=5,
    priority=10,
    queue="urgent",
    retry_delay=[1, 5, 30, 60],
    timeout=120,
)
async def process_payment(order_id: int, amount: float):
    ...
```


## enqueue()

Dispatches a registered job for processing.

```python
job_id = await app.enqueue(
    "myapp.tasks.send_email",
    args={"to": "a@b.com", "subject": "Hi", "body": "Hello"},
)
```

### Signature

```python
async def enqueue(
    name_or_ref,        # Task name string, or a TaskRef (see below)
    *,
    args: dict | None = None,  # Arguments passed to the job function
    priority: int = None,      # Override the job's default priority
    queue: str = None,         # Override the job's default queue
    scheduled_at: datetime = None,  # Run at a specific time (UTC)
    unique: bool = None,       # Override the job's default uniqueness
    dedup_key: str = None,     # Custom deduplication key (instead of args hash)
    connection = None,         # Asyncpg connection for transactional enqueue
) -> str                       # Returns job UUID
```

`args` defaults to `{}`. All option parameters are optional. When omitted, the values from the `@app.job` registration apply (or system defaults if no local registration).

`name_or_ref` accepts a string task name or a `TaskRef` (typed cross-service stub). When a `TaskRef` is passed, its `args_model` validates `args` and its `default_queue` is used if `queue=` is not passed explicitly.

### Transactional enqueue

Pass a `connection` to enqueue a job inside an existing database transaction.
If the transaction rolls back, the job is never created.

```python
pool = await app.get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders (id) VALUES ($1)", order_id)
        await app.enqueue(
            "myapp.tasks.fulfill_order",
            args={"order_id": order_id},
            connection=conn,
        )
```

Transactional enqueue requires the PostgreSQL backend.


## schedule()

Schedule a job for future execution. Two calling conventions exist:

### Instance API

```python
job_id = await app.schedule(send_report, run_at=tomorrow_9am, user_id=42)
```

`app.schedule()` is a thin wrapper around `app.enqueue()` that sets `scheduled_at`.

### Global API

The global `soniq.schedule()` supports both absolute and relative times:

```python
import soniq
from datetime import datetime, timedelta, timezone

# Absolute time
await soniq.schedule(send_report, run_at=datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc))

# Relative delay in seconds
await soniq.schedule(send_reminder, run_in=3600)

# Relative delay as timedelta
await soniq.schedule(send_reminder, run_in=timedelta(hours=1))
```

```python
async def schedule(
    job_func,
    *,
    run_at: datetime | None = None,    # Absolute UTC datetime
    run_in: int | float | timedelta | None = None,  # Relative delay
    connection=None,
    **kwargs,
) -> str  # Returns job UUID
```

Exactly one of `run_at` or `run_in` is required.


## @app.periodic() / @soniq.periodic()

Declares a job that runs on a recurring schedule. The scheduler process
(`soniq scheduler`) picks up all `@periodic` functions automatically.

```python
@soniq.periodic(cron="0 9 * * *")
async def daily_report():
    ...

@soniq.periodic(every_minutes=10, queue="maintenance")
async def cleanup_old_sessions():
    ...
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `cron` | `str` | Standard cron expression (5 fields: minute hour day month weekday). |
| `every_seconds` | `int` | Run every N seconds. |
| `every_minutes` | `int` | Run every N minutes. |
| `every_hours` | `int` | Run every N hours. |
| `**job_kwargs` | | Any parameter accepted by `@app.job` (name, queue, priority, retries, etc.). |

Rules:
- Specify exactly one of `cron` or one `every_*` parameter.
- You cannot combine `cron` with any `every_*` parameter.
- You cannot combine multiple `every_*` parameters.

Requires `SONIQ_SCHEDULING_ENABLED=true` and a running `soniq scheduler`
process.


## JobContext

Runtime metadata injected into your job function. Declare a parameter with
type annotation `JobContext` and Soniq fills it in automatically.

```python
from soniq import JobContext

@app.job
async def process_order(order_id: int, ctx: JobContext):
    print(f"Job {ctx.job_id}, attempt {ctx.attempt} of {ctx.max_attempts}")
```

### Attributes

| Attribute | Type | Description |
|---|---|---|
| `job_id` | `str` | UUID of this job. |
| `job_name` | `str` | Fully qualified name (`module.function`). |
| `attempt` | `int` | Current attempt number (starts at 1). |
| `max_attempts` | `int` | Total allowed attempts (`retries + 1`). |
| `queue` | `str` | Queue this job is running in. |
| `worker_id` | `str \| None` | UUID of the worker processing this job. |
| `scheduled_at` | `datetime \| None` | When the job was scheduled to run, if it was delayed. |
| `created_at` | `datetime \| None` | When the job was created. |

`JobContext` is a frozen dataclass. It is read-only.


## JobStatus

Enum of all job lifecycle states.

```python
from soniq import JobStatus
```

| Value | Meaning |
|---|---|
| `JobStatus.QUEUED` | Waiting to be picked up by a worker. |
| `JobStatus.PROCESSING` | Currently being executed. |
| `JobStatus.DONE` | Completed successfully. |
| `JobStatus.FAILED` | Failed but may be retried. |
| `JobStatus.DEAD_LETTER` | Exhausted all retries. Moved to the dead-letter queue. |
| `JobStatus.CANCELLED` | Cancelled before execution. |


## JobScheduleBuilder (advanced scheduling)

A fluent interface for building complex schedules. Requires
`SONIQ_SCHEDULING_ENABLED=true`.

```python
from soniq.features.scheduling import schedule_job

job_id = await (
    schedule_job(send_report)
    .in_minutes(30)
    .with_priority(5)
    .in_queue("reports")
    .with_retries(2)
    .enqueue(user_id=42)
)
```

### Builder methods

All methods return `self` for chaining.

| Method | Description |
|---|---|
| `.in_seconds(n)` | Run in N seconds from now. |
| `.in_minutes(n)` | Run in N minutes from now. |
| `.in_hours(n)` | Run in N hours from now. |
| `.in_days(n)` | Run in N days from now. |
| `.at_time(time_str)` | Run at a specific time. Accepts ISO 8601 datetime or `"HH:MM"` for today (schedules tomorrow if the time has passed). |
| `.with_priority(n)` | Set priority (lower = higher). |
| `.in_queue(name)` | Set target queue. |
| `.with_retries(n)` | Set max retry attempts. |
| `.with_tags(*tags)` | Add tags for categorization. |
| `.with_timeout(seconds)` | Set execution timeout. |
| `.if_condition(fn)` | Only enqueue if `fn()` returns `True`. |
| `.dry_run()` | Return configuration dict instead of enqueueing. |

### Terminal method

```python
async def enqueue(self, connection=None, **kwargs) -> str | dict
```

Enqueues the job and returns its UUID. In dry-run mode, returns a configuration
dictionary instead.


## BatchScheduler

Enqueue multiple jobs as a logical batch:

```python
from soniq.features.scheduling import create_batch

batch = create_batch()
batch.add(send_email, to="a@b.com").with_priority(10)
batch.add(send_email, to="c@d.com").with_priority(10)
job_ids = await batch.enqueue_all()
```

## Recurring schedule helpers

The `every()` and `cron()` helpers provide a fluent API for registering recurring
jobs. They require `SONIQ_SCHEDULING_ENABLED=true`.

```python
import soniq

# Every 5 minutes
await soniq.every(5).minutes().schedule(cleanup_task)

# Cron expression
await soniq.cron("0 9 * * *").schedule(daily_report)
```
