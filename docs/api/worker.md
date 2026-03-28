# Worker

Workers fetch jobs from the database, execute them, and update their status.
Most users start workers through the CLI (`elephantq start`) or `app.run_worker()`.
The `Worker` class itself is documented here for advanced use cases.


## run_worker()

The recommended way to start processing jobs from application code.

```python
app = ElephantQ(database_url="postgresql://localhost/myapp")

await app.run_worker(
    concurrency=4,
    run_once=False,
    queues=None,
)
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `concurrency` | `int` | `4` | Number of concurrent asyncio tasks fetching and executing jobs. |
| `run_once` | `bool` | `False` | Process all available jobs and exit. Useful for testing and cron-driven setups. |
| `queues` | `list[str] \| None` | `None` | Restrict to these queue names. `None` means process all queues. |

The global API exposes the same function:

```python
import elephantq

await elephantq.run_worker(concurrency=8, queues=["urgent", "default"])
```

### What happens during run_worker

1. The app auto-initializes if needed (connects to the database, runs lazy setup).
2. A `Worker` instance is created with the app's backend, job registry, settings, and hooks.
3. In continuous mode, the worker registers itself in the database, starts a heartbeat loop, subscribes to `LISTEN/NOTIFY` for instant job pickup, and launches `concurrency` processing tasks.
4. In `run_once` mode, the worker processes available jobs sequentially until the queue is empty, then returns.


## Worker configuration via environment variables

These environment variables control worker behavior when using the CLI or default
settings:

| Env var | Default | Description |
|---|---|---|
| `ELEPHANTQ_CONCURRENCY` | `4` | Default concurrency (overridden by `--concurrency` flag). |
| `ELEPHANTQ_QUEUES` | `default` | Comma-separated queue list (overridden by `--queues` flag). |
| `ELEPHANTQ_POLL_INTERVAL` | `5.0` | Seconds to wait when no jobs are available before polling again. Also the `LISTEN/NOTIFY` timeout. |
| `ELEPHANTQ_HEARTBEAT_INTERVAL` | `5.0` | Seconds between heartbeat updates. |
| `ELEPHANTQ_HEARTBEAT_TIMEOUT` | `300.0` | Seconds after which a worker with no heartbeat is considered stale. |
| `ELEPHANTQ_CLEANUP_INTERVAL` | `300.0` | Seconds between expired-job and stale-worker cleanup runs. |
| `ELEPHANTQ_ERROR_RETRY_DELAY` | `5.0` | Seconds to sleep after an unexpected worker-level error before resuming. |
| `ELEPHANTQ_JOBS_MODULE` | `jobs` | Module name for automatic job discovery. |
| `ELEPHANTQ_JOBS_MODULES` | (empty) | Comma-separated list of modules to import on worker startup. Required by the CLI. |


## Worker class (advanced)

Most users never instantiate `Worker` directly. It is documented here for
contributors and users who need fine-grained control.

```python
from elephantq.worker import Worker
from elephantq.core.registry import JobRegistry
from elephantq.settings import ElephantQSettings

worker = Worker(
    backend=backend,       # A StorageBackend instance
    registry=registry,     # A JobRegistry with registered jobs
    settings=settings,     # ElephantQSettings (optional, uses global defaults)
    hooks=hooks,           # Dict of hook lists (optional)
)
```

### Constructor parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `backend` | `StorageBackend` | (required) | The storage backend (PostgresBackend, SQLiteBackend, or MemoryBackend). |
| `registry` | `JobRegistry` | (required) | Job registry containing all `@app.job()` registrations. |
| `settings` | `ElephantQSettings \| None` | `None` | Settings instance. Falls back to global settings when `None`. |
| `hooks` | `dict \| None` | `None` | Hook dictionary with keys `"before_job"`, `"after_job"`, `"on_error"`, each mapping to a list of callables. |

### run()

```python
async def run(
    self,
    concurrency: int = 4,
    run_once: bool = False,
    queues: list[str] | None = None,
) -> bool
```

Returns `True` if any jobs were processed.

### run_once()

```python
async def run_once(
    self,
    queues: list[str] | None = None,
    max_jobs: int | None = None,
) -> bool
```

Process available jobs and return. Pass `max_jobs` to cap how many jobs are
processed in one call.


## Graceful shutdown

In continuous mode, the worker installs signal handlers for `SIGINT` and `SIGTERM`.
On receiving either signal:

1. The shutdown event is set.
2. Running job tasks are cancelled.
3. The worker deregisters itself from the database.
4. The `LISTEN/NOTIFY` connection is released.

A second signal during shutdown forces an immediate exit.


## LISTEN/NOTIFY

When the backend supports push notifications (PostgreSQL), the worker subscribes
to the `elephantq_new_job` channel. When a job is enqueued, the worker wakes up
immediately instead of waiting for the next poll cycle. This keeps latency low
without hammering the database with frequent polls.

If `LISTEN/NOTIFY` setup fails (for example behind PgBouncer in transaction mode),
the worker falls back to polling at `poll_interval`.
