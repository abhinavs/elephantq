# Installation

## Requirements

Python 3.10 or later.

## Core install

```bash
pip install elephantq
```

This pulls in `asyncpg` (PostgreSQL driver), `click`, and `pydantic-settings`. Enough to run jobs on Postgres right away.

## Optional extras

Install only what you need:

```bash
pip install elephantq[sqlite]       # aiosqlite -- SQLite backend for local dev
pip install elephantq[scheduling]   # croniter -- recurring/cron jobs
pip install elephantq[webhooks]     # aiohttp + cryptography -- HTTP callbacks and payload signing
pip install elephantq[dashboard]    # fastapi + uvicorn -- web dashboard
pip install elephantq[monitoring]   # prometheus-client + psutil -- metrics and health checks
pip install elephantq[logging]      # structlog -- structured JSON logging
pip install elephantq[full]         # everything above
```

Combine extras freely: `pip install elephantq[sqlite,scheduling,dashboard]`.

## Backend auto-detection

ElephantQ picks the storage backend from your `database_url`:

| URL pattern | Backend | Driver |
|---|---|---|
| `postgresql://...` or `postgres://...` | PostgreSQL | asyncpg (included) |
| `*.db`, `*.sqlite`, `*.sqlite3` | SQLite | aiosqlite (extra) |
| `backend="memory"` | In-memory | none |

```python
from elephantq import ElephantQ

# PostgreSQL -- production
app = ElephantQ(database_url="postgresql://localhost/myapp")

# SQLite -- local dev, no server
app = ElephantQ(database_url="local.db")

# In-memory -- unit tests
app = ElephantQ(backend="memory")
```

**PostgreSQL** is the only production-grade backend. It supports multiple concurrent workers, instant job delivery via `LISTEN/NOTIFY`, and transactional enqueue (enqueue a job inside your application's database transaction so the job only exists if the transaction commits).

**SQLite** is single-worker, polling-only, and doesn't support transactional enqueue. Good for prototyping and simple single-process deployments.

**Memory** stores jobs in a Python dict. Useful for unit tests where you don't want any external dependencies.

## Feature flags

Every optional feature is **disabled by default**. Enable them with environment variables or a `.env` file:

```bash
# .env
ELEPHANTQ_DASHBOARD_ENABLED=true
ELEPHANTQ_SCHEDULING_ENABLED=true
ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED=true
```

Here are the available flags:

| Environment variable | What it enables | Extra needed |
|---|---|---|
| `ELEPHANTQ_SCHEDULING_ENABLED` | Recurring jobs and cron schedules | `scheduling` |
| `ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED` | Dead-letter queue for permanently failed jobs | -- |
| `ELEPHANTQ_TIMEOUTS_ENABLED` | Per-job timeout enforcement | -- |
| `ELEPHANTQ_METRICS_ENABLED` | Prometheus-style counters and health metrics | `monitoring` |
| `ELEPHANTQ_LOGGING_ENABLED` | Structured JSON logging | `logging` |
| `ELEPHANTQ_WEBHOOKS_ENABLED` | HTTP webhook notifications on job events | `webhooks` |
| `ELEPHANTQ_SIGNING_ENABLED` | Webhook payload signing and secret helpers | `webhooks` |
| `ELEPHANTQ_DASHBOARD_ENABLED` | Web UI for inspecting queues and jobs | `dashboard` |
| `ELEPHANTQ_DASHBOARD_WRITE_ENABLED` | Retry/delete/cancel buttons in the dashboard | `dashboard` |

All flags accept `true`/`false` (case-insensitive). If the required extra isn't installed, ElephantQ will raise an import error at startup with a clear message about which package to install.

## Verifying the install

```bash
# Check the version
elephantq --version

# Create tables (run against your database)
ELEPHANTQ_DATABASE_URL="postgresql://localhost/myapp" elephantq setup

# Start a worker
ELEPHANTQ_DATABASE_URL="postgresql://localhost/myapp" \
ELEPHANTQ_JOBS_MODULES="myapp.jobs" \
elephantq start
```

See [quickstart.md](quickstart.md) to run your first job end-to-end.
