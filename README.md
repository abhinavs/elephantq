# ElephantQ

**PostgreSQL-native background jobs for modern Python apps.**

ElephantQ keeps things simple: async `@job` functions, a Postgres table for work, an optional dashboard, and builders when you want more than a simple `enqueue`. Everything is opt-in via feature flags so the core stays lean while advanced features remain in the same install.

## Why ElephantQ

- **One stack:** Jobs live in PostgreSQL, no Redis or message broker to manage.
- **Async-first:** Define `async def` jobs, `await` `enqueue`, and keep the stack compatible with FastAPI, Starlette, or Django ASGI.
- **Explicit worker & scheduler processes:** Workers focus on processing; the scheduler handles recurring/cron work; the dashboard sits behind its own flag.
- **Feature flags, not forks:** Dashboard, metrics, dependencies, dead-letter, signing, and webhooks all share the same codebase but stay dormant unless you flip a flag.
- **Developer-friendly surface:** Clean CLI output, `ELEPHANTQ_JOBS_MODULES` discovery, fluent builders, and a helpful `run_tests.py` keep the experience predictable.

## Quick Start (30 seconds)

```bash
# 1. Install
pip install elephantq

# 2. Point to Postgres
export ELEPHANTQ_DATABASE_URL="postgresql://user:pass@localhost/mydb"
export ELEPHANTQ_JOBS_MODULES="app.jobs"

# 3. Create tables
elephantq setup

# 4. Start a worker (runs jobs forever)
elephantq start --concurrency 4 --queues=default,emails
```

### Define a job

```python
import elephantq

@elephantq.job(queue="emails", retries=5)
async def send_welcome(to: str):
    print("Sending welcome to", to)
```

Then enqueue it from any async context:

```python
await elephantq.enqueue(send_welcome, to="team@apiclabs.com")
```

## Workers, Scheduler, Dashboard

- **Workers** run with `elephantq start`. They require `ELEPHANTQ_JOBS_MODULES` so the functions you register are importable. The CLI prints queue stats, worker heartbeats, and error hints.
- **Scheduler** runs with `ELEPHANTQ_SCHEDULING_ENABLED=true elephantq scheduler`. It keeps recurring work separate so workers stay focused on real-time jobs.
- **Dashboard** is launched via `ELEPHANTQ_DASHBOARD_ENABLED=true elephantq dashboard`. Add `ELEPHANTQ_DASHBOARD_WRITE_ENABLED=true` only in trusted environments (retry/delete actions are gated behind that flag).
- **Dev mode** (`elephantq dev`) spins up worker + scheduler + dashboard together. It boots with the same config and respects the feature flags you already set.

## Feature overview

| Feature | Why it matters | How to enable |
| --- | --- | --- |
| Fluent scheduling builders | Compose delayed, cron, or batch jobs with readable code | `elephantq.features.scheduling.schedule_job(...)`, `elephantq.features.recurring.every(...)`; requires `ELEPHANTQ_SCHEDULING_ENABLED=true` |
| Retries & backoff | Jobs retry with jitter/backoff before hitting dead-letter | Use `@elephantq.job(retries=5, retry_backoff=True)` |
| Dashboard | Real-time view of queues, workers, and job timeline | `ELEPHANTQ_DASHBOARD_ENABLED=true` + optional `ELEPHANTQ_DASHBOARD_WRITE_ENABLED=true` |
| Metrics/logging | Structured metrics and logs for production visibility | `ELEPHANTQ_METRICS_ENABLED=true`, `ELEPHANTQ_LOGGING_ENABLED=true` |
| Dependencies/timeouts | Declare job ordering and per-job timeout policies | `elephantq.features.scheduling.schedule_job(...).depends_on(...).with_timeout(...)` with the appropriate feature flags |
| Dead-letter queue & webhooks | Inspect and respond to failed jobs | `ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED=true`; webhooks need `ELEPHANTQ_WEBHOOKS_ENABLED=true` |
| Connection safety | Keeps worker concurrency in sync with Postgres pool size | tune `ELEPHANTQ_DB_POOL_MAX/MIN_SIZE` + `ELEPHANTQ_DB_POOL_SAFETY_MARGIN` |

## Fluent scheduling in code

```python
from elephantq.features import scheduling

builder = scheduling.schedule_job(process_upload)
await (
    builder.with_queue("processing")
    .with_priority(10)
    .with_tags("batch:file")
    .depends_on(existing_job_id)
    .with_timeout(60)
    .in_minutes(5)
    .enqueue(file_path="/tmp/report.zip")
)
```

Builders record metadata via `elephantq.features.scheduling.get_job_metadata()` so dashboards, logs, or metrics clients can surface the full intent.

Recurring jobs use a similar fluent API:

```python
await scheduling.every(1).days().at("09:00").high_priority().schedule(report_job)
```

The scheduler reloads persisted definitions (`elephantq_recurring_jobs` table) on restart and respects `ELEPHANTQ_SCHEDULING_ENABLED=true`.

## Observability & operations

- Structured logs and metrics hook into the same event loop. Enable `ELEPHANTQ_METRICS_ENABLED` for Prometheus counters and `ELEPHANTQ_LOGGING_ENABLED` for Serilog-like payloads.
- Dead-letter queue (`ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED=true`) keeps failed jobs for inspection; you can resurrect, delete, or export them via the CLI or dashboard.
- Connection pooling respects `ELEPHANTQ_DEFAULT_CONCURRENCY` and warns when the worker tries to exceed `ELEPHANTQ_DB_POOL_MAX_SIZE`. The new `ELEPHANTQ_DB_POOL_SAFETY_MARGIN` reserves room for the scheduler/listener connections.
- Use `elephantq.features.webhooks.register_endpoint(...)` to notify other systems about job events, and `elephantq.features.logging.setup(...)` for per-job context logging.

## Resources

- 🧭 [Getting Started](docs/getting-started.md) — a guided setup with troubleshooting tips.
- 📜 [Feature reference](docs/features.md) — metrics, logging, webhooks, dead-letter, and more.
- ⏱️ [Scheduling guide](docs/scheduling.md) — fluent builders, batches, and repeated schedules.
- 🏗️ `deployment/` — sample systemd, supervisor, Docker, and Kubernetes templates.
- 🧪 `tests/` and `examples/` — runnable snapshots of common workflows.

## Extras

Optional dependencies unlock extra tools:

```bash
pip install elephantq[dashboard]    # dashboard UI
pip install elephantq[monitoring]   # metrics + webhooks dependencies
pip install elephantq[all]          # everything
```

The CLI stays helpful: `elephantq start`, `scheduler`, `dashboard`, `workers`, `metrics`, and a dedicated `run_tests.py` for automated validation.
