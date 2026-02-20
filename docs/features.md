# Optional features

ElephantQ bundles a number of higher-level capabilities in the same package. They are all opt-in: flip the corresponding `ELEPHANTQ_*_ENABLED` flag and install the listed extra to turn them on.

## Metrics

- **Flag:** `ELEPHANTQ_METRICS_ENABLED=true`
- **Extra:** `pip install elephantq[monitoring]`
- **What it does:** Tracks job counts, queue depth, retry totals, and scheduler health. Metrics are exposed via Prometheus-friendly counters so you can scrape them alongside the rest of your stack.

```python
from elephantq.features.metrics import get_system_metrics
metrics = await get_system_metrics(timeframe_hours=1)
print("Jobs processed in the last hour:", metrics["jobs_processed"])
```

## Structured logging

- **Flag:** `ELEPHANTQ_LOGGING_ENABLED=true`
- **Extra:** no add-ons needed (depends on `structlog`).
- **What it does:** Captures per-job context (job id, queue, retries, errors) and emits structured events that you can route to your logging backend.

```python
from elephantq.features.logging import setup, get_job_logger

setup(format="structured", level="INFO")
logger = get_job_logger("my-job-id")
logger.info("Job started")
```

Use the logger inside job handlers to keep traceability aligned with ElephantQ metadata. The middleware understands job/timeouts, so you get consistent context across retries.

## Dead-letter queue

- **Flag:** `ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED=true`
- **Extra:** `pip install elephantq[monitoring]`
- **What it does:** Failed jobs beyond their retry budget land in `elephantq_dead_letter_jobs`. You can inspect, retry, delete, or export them.

```bash
elephantq dead-letter list
elephantq dead-letter resurrect --job-ids <id>
elephantq dead-letter export --output failed.json
```

Webhooks and custom metrics can react to dead-letter activity to keep your operations team informed.

## Webhooks

- **Flag:** `ELEPHANTQ_WEBHOOKS_ENABLED=true`
- **Extra:** `pip install elephantq[monitoring]` (adds `httpx`)
- **What it does:** Register webhook endpoints that receive job lifecycle events such as `job.succeeded`, `job.failed`, or `job.dead_letter`.

```python
await elephantq.features.webhooks.register_endpoint(
    url="https://hooks.example.com/elephantq",
    events=["job.failed", "job.dead_letter"],
    secret="supersecret",
)
```

The feature keeps delivery retries, headers, and metadata inside ElephantQ, so you can rely on Postgres transactions to keep the webhook state consistent.

## Job dependencies & timeouts

- **Flags:** `ELEPHANTQ_DEPENDENCIES_ENABLED=true`, `ELEPHANTQ_TIMEOUTS_ENABLED=true`
- **Extra:** no extras (depends on Postgres features).
- **What it does:** Enforces job ordering, timeout-based cancellations, and scheduler-aware timeouts.

```python
from elephantq.features.scheduling import schedule_job

builder = schedule_job(generate_report)
await (
    builder.depends_on(seed_job_id)
    .with_timeout(60)
    .enqueue(run_type="daily")
)
```

Dependencies store their own table (`elephantq_job_dependencies`), so the scheduler or worker can skip the job until its prerequisites finish. Timeouts go into `elephantq_job_timeouts`, and the timeout processor wakes any stuck jobs.

## Feature flags & extras

| Flag | Purpose |
| --- | --- |
| `ELEPHANTQ_DASHBOARD_ENABLED` | Enables the FastAPI dashboard (needs `fastapi`, `uvicorn`). |
| `ELEPHANTQ_DASHBOARD_WRITE_ENABLED` | Adds retry/delete/cancel buttons in the UI (use in trusted environments). |
| `ELEPHANTQ_METRICS_ENABLED` | Switches on metrics counters and Prometheus blanks. |
| `ELEPHANTQ_LOGGING_ENABLED` | Wires `structlog` to job-aware logging. |
| `ELEPHANTQ_SCHEDULING_ENABLED` | Unlocks `elephantq.features.scheduling` and `elephantq.features.recurring`. |
| `ELEPHANTQ_DEPENDENCIES_ENABLED`, `ELEPHANTQ_TIMEOUTS_ENABLED` | Hooks into scheduling metadata and per-job guards. |

Each of these features is documented in `docs/<feature>.md` (see the `/docs` directory). The CLI gracefully refuses to run commands when the corresponding flag is disabled, so enabling a feature means turning on the flag and (if needed) installing the optional dependency.
