# ElephantQ Class

The `ElephantQ` class is the central object in ElephantQ. It owns a database connection,
a job registry, and all configuration. You can run multiple independent instances in
the same process.

## Constructor

```python
from elephantq import ElephantQ

app = ElephantQ(
    database_url="postgresql://localhost/myapp",
    config_file=None,
    backend=None,
    **settings_overrides,
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `database_url` | `str \| None` | `None` (falls back to `ELEPHANTQ_DATABASE_URL` or `postgresql://postgres@localhost/elephantq`) | PostgreSQL connection URL. Also accepts paths ending in `.db`/`.sqlite`/`.sqlite3` for SQLite. |
| `config_file` | `Path \| None` | `None` | Path to a `.env`-style config file. |
| `backend` | `StorageBackend \| str \| None` | `None` | Storage backend instance, or one of `"postgres"`, `"sqlite"`, `"memory"`. When `None`, auto-detected from `database_url`. |
| `**settings_overrides` | | | Any field from `ElephantQSettings` (see below). |

Common settings you can pass as keyword arguments:

| Keyword | Type | Default | Env var |
|---|---|---|---|
| `concurrency` | `int` | `4` | `ELEPHANTQ_CONCURRENCY` |
| `max_retries` | `int` | `3` | `ELEPHANTQ_MAX_RETRIES` |
| `priority` | `int` | `100` | `ELEPHANTQ_PRIORITY` |
| `queues` | `list[str]` | `["default"]` | `ELEPHANTQ_QUEUES` (comma-separated) |
| `result_ttl` | `int` | `300` | `ELEPHANTQ_RESULT_TTL` |
| `job_timeout` | `float \| None` | `300.0` | `ELEPHANTQ_JOB_TIMEOUT` (0 to disable) |
| `pool_min_size` | `int` | `5` | `ELEPHANTQ_POOL_MIN_SIZE` |
| `pool_max_size` | `int` | `20` | `ELEPHANTQ_POOL_MAX_SIZE` |
| `pool_headroom` | `int` | `2` | `ELEPHANTQ_POOL_HEADROOM` |
| `poll_interval` | `float` | `5.0` | `ELEPHANTQ_POLL_INTERVAL` |
| `heartbeat_interval` | `float` | `5.0` | `ELEPHANTQ_HEARTBEAT_INTERVAL` |
| `heartbeat_timeout` | `float` | `300.0` | `ELEPHANTQ_HEARTBEAT_TIMEOUT` |
| `cleanup_interval` | `float` | `300.0` | `ELEPHANTQ_CLEANUP_INTERVAL` |
| `error_retry_delay` | `float` | `5.0` | `ELEPHANTQ_ERROR_RETRY_DELAY` |
| `log_level` | `str` | `"INFO"` | `ELEPHANTQ_LOG_LEVEL` |
| `log_format` | `str` | `"simple"` | `ELEPHANTQ_LOG_FORMAT` (`simple` or `structured`) |
| `debug` | `bool` | `False` | `ELEPHANTQ_DEBUG` |
| `environment` | `str` | `"production"` | `ELEPHANTQ_ENVIRONMENT` |

Feature flags (all `False` by default):

| Keyword | Env var | Unlocks |
|---|---|---|
| `dashboard_enabled` | `ELEPHANTQ_DASHBOARD_ENABLED` | Web dashboard |
| `dashboard_write_enabled` | `ELEPHANTQ_DASHBOARD_WRITE_ENABLED` | Retry/delete/cancel buttons in dashboard |
| `scheduling_enabled` | `ELEPHANTQ_SCHEDULING_ENABLED` | Advanced scheduling and recurring jobs |
| `dead_letter_queue_enabled` | `ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED` | Dead-letter queue management |
| `metrics_enabled` | `ELEPHANTQ_METRICS_ENABLED` | Metrics collection |
| `logging_enabled` | `ELEPHANTQ_LOGGING_ENABLED` | Structured logging features |
| `webhooks_enabled` | `ELEPHANTQ_WEBHOOKS_ENABLED` | Webhook notifications |
| `timeouts_enabled` | `ELEPHANTQ_TIMEOUTS_ENABLED` | Job timeout processing |
| `signing_enabled` | `ELEPHANTQ_SIGNING_ENABLED` | Signing and secret helpers |


## Global configure()

If you prefer the module-level API (`import elephantq`) over creating an instance,
configure settings with `elephantq.configure()`:

```python
import elephantq

elephantq.configure(
    database_url="postgresql://localhost/myapp",
    concurrency=8,
    max_retries=5,
    result_ttl=600,
    debug=True,
)
```

All keyword arguments match the constructor's `**settings_overrides`. Calling
`configure()` replaces the internal global instance, so registered jobs carry over
automatically.


## Lifecycle

### close()

Closes the connection pool and releases resources. Calling `close()` twice is
harmless.

```python
await app.close()
```

### Async context manager

`close()` is called automatically on exit:

```python
async with ElephantQ(database_url="postgresql://localhost/myapp") as app:
    await app.enqueue(my_job, message="hello")
```

The connection pool initializes lazily on first use. No explicit init call is needed.

!!! note "Database migrations"
    Use the `elephantq setup` CLI command in your deploy pipeline to create
    tables and run migrations. Don't run migrations from application code --
    it causes race conditions when multiple replicas start simultaneously.


## get_pool()

Returns the underlying `asyncpg` connection pool. Useful when you need direct
database access, for example to run a job enqueue inside an application transaction.

```python
pool = await app.get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders ...")
        await app.enqueue(send_receipt, connection=conn, order_id=42)
```

Returns `None` for SQLite and in-memory backends (they do not use asyncpg).


## get_queue_stats()

Returns a list of dictionaries, one per queue, sorted by queue name:

```python
stats = await app.get_queue_stats()
```

Each dictionary contains:

```python
{
    "queue": "default",
    "total": 150,
    "queued": 12,
    "processing": 3,
    "done": 130,
    "dead_letter": 4,
    "cancelled": 1,
}
```

Returns an empty list when no jobs exist.


## Job management methods

These are thin wrappers over the storage backend. Each accepts a `job_id` string
(the UUID returned by `enqueue()`).

| Method | Returns | Description |
|---|---|---|
| `get_job_status(job_id)` | `dict \| None` | Full job record or `None` if not found. |
| `get_result(job_id)` | `Any \| None` | Return value of a completed job, or `None`. |
| `cancel_job(job_id)` | `bool` | `True` if the job was cancelled. |
| `retry_job(job_id)` | `bool` | `True` if the job was re-queued. |
| `delete_job(job_id)` | `bool` | `True` if the job was deleted. |
| `list_jobs(queue?, status?, limit=100, offset=0)` | `list[dict]` | Filtered list of job records. |


## Environment variable configuration

Every setting can be set via an environment variable prefixed with `ELEPHANTQ_`.
Environment variables take precedence over `.env` files, which take precedence over
defaults. The full priority order:

1. Keyword arguments passed to the constructor
2. Environment variables (`ELEPHANTQ_*`)
3. `.env` file (or custom `config_file`)
4. Default values

Example `.env` file:

```
ELEPHANTQ_DATABASE_URL=postgresql://user:pass@db.example.com/myapp
ELEPHANTQ_CONCURRENCY=8
ELEPHANTQ_MAX_RETRIES=5
ELEPHANTQ_QUEUES=default,urgent,background
ELEPHANTQ_LOG_LEVEL=DEBUG
ELEPHANTQ_DASHBOARD_ENABLED=true
```
