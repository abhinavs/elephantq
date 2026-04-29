# Installation

## Requirements

Python 3.10 or later.

## Core install (batteries-included)

```bash
pip install soniq
```

This pulls in `asyncpg` (PostgreSQL driver), `pydantic-settings`,
`croniter` (so `@periodic` and the recurring scheduler work out of the
box), and `prometheus_client` (so `PrometheusMetricsSink` is importable).
Enough to run jobs, schedules, and metrics on PostgreSQL right away.

The scheduler and Prometheus sink stay dormant unless you wire them: the
scheduler only runs if you start it, and the default `MetricsSink` is
`NoopMetricsSink`.

## Optional extras

Install only what you need:

```bash
pip install soniq[sqlite]       # aiosqlite -- SQLite backend for local dev
pip install soniq[webhooks]     # aiohttp + cryptography -- HTTP callbacks and payload signing
pip install soniq[dashboard]    # fastapi + uvicorn -- web dashboard
pip install soniq[logging]      # structlog -- structured JSON logging
pip install soniq[full]         # everything above
```

Combine extras freely: `pip install soniq[sqlite,dashboard]`.

## Backend auto-detection

Soniq picks the storage backend from your `database_url`:

| URL pattern | Backend | Driver |
|---|---|---|
| `postgresql://...` or `postgres://...` | PostgreSQL | asyncpg (included) |
| `*.db`, `*.sqlite`, `*.sqlite3` | SQLite | aiosqlite (extra) |
| `backend="memory"` | In-memory | none |

```python
from soniq import Soniq

# PostgreSQL -- production
app = Soniq(database_url="postgresql://localhost/myapp")

# SQLite -- local dev, no server
app = Soniq(database_url="local.db")

# In-memory -- unit tests
app = Soniq(backend="memory")
```

**PostgreSQL** is the only production-grade backend. It supports multiple concurrent workers, instant job delivery via `LISTEN/NOTIFY`, and transactional enqueue (enqueue a job inside your application's database transaction so the job only exists if the transaction commits).

**SQLite** is single-worker, polling-only, and doesn't support transactional enqueue. Good for prototyping and simple single-process deployments.

**Memory** stores jobs in a Python dict. Useful for unit tests where you don't want any external dependencies.

## Feature flags

Every optional feature is **disabled by default**. Enable them with environment variables or a `.env` file:

```bash
# .env
SONIQ_DASHBOARD_ENABLED=true
SONIQ_SCHEDULING_ENABLED=true
SONIQ_DEAD_LETTER_QUEUE_ENABLED=true
```

Here are the available flags:

| Environment variable | What it enables | Extra needed |
|---|---|---|
| `SONIQ_SCHEDULING_ENABLED` | Recurring jobs and cron schedules | -- (default) |
| `SONIQ_DEAD_LETTER_QUEUE_ENABLED` | Dead-letter queue for permanently failed jobs | -- |
| `SONIQ_TIMEOUTS_ENABLED` | Per-job timeout enforcement | -- |
| `SONIQ_METRICS_ENABLED` | Prometheus-style counters and health metrics | -- (default) |
| `SONIQ_LOGGING_ENABLED` | Structured JSON logging | `logging` |
| `SONIQ_WEBHOOKS_ENABLED` | HTTP webhook notifications on job events | `webhooks` |
| `SONIQ_SIGNING_ENABLED` | Webhook payload signing and secret helpers | `webhooks` |
| `SONIQ_DASHBOARD_ENABLED` | Web UI for inspecting queues and jobs | `dashboard` |
| `SONIQ_DASHBOARD_WRITE_ENABLED` | Retry/delete/cancel buttons in the dashboard | `dashboard` |

All flags accept `true`/`false` (case-insensitive). If the required extra isn't installed, Soniq will raise an import error at startup with a clear message about which package to install.

## Verifying the install

```bash
# Check the version
soniq --version

# Create tables (run against your database)
SONIQ_DATABASE_URL="postgresql://localhost/myapp" soniq setup

# Start a worker
SONIQ_DATABASE_URL="postgresql://localhost/myapp" \
SONIQ_JOBS_MODULES="myapp.jobs" \
soniq start
```

See [quickstart.md](quickstart.md) to run your first job end-to-end.
