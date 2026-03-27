# Monitoring

ElephantQ tracks job metrics in-memory and exposes them through the CLI and the dashboard API. For Prometheus-style scraping, install the monitoring extra.

## Enable

```bash
export ELEPHANTQ_METRICS_ENABLED=true
pip install elephantq[monitoring]  # adds prometheus-client and psutil
```

## What gets tracked

- **Job counts** by status (queued, processing, done, failed, dead_letter)
- **Processing time** (average, p95, p99)
- **Throughput** (jobs per minute)
- **Success rate** (percentage)
- **Per-queue stats** (depth, processing time, throughput)
- **System resources** (CPU, memory, disk usage via `psutil`)

## CLI

```bash
# Table output (default)
elephantq metrics --hours 1

# JSON output for scripting
elephantq metrics --format json --hours 24

# Export to file
elephantq metrics --format json --export metrics.json
```

## Python API

```python
from elephantq.metrics import get_system_metrics

metrics = await get_system_metrics(timeframe_hours=1)

print(metrics["total_jobs"])
print(metrics["success_rate"])
print(metrics["avg_processing_time_ms"])
print(metrics["throughput_per_minute"])

for queue in metrics["queue_stats"]:
    print(f"{queue['queue_name']}: {queue['queued_count']} queued")
```

## Prometheus scraping

When `ELEPHANTQ_METRICS_ENABLED=true` and the monitoring extra is installed, counters are registered with `prometheus-client`. Expose them by mounting the default metrics endpoint in your FastAPI app:

```python
from prometheus_client import make_asgi_app

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

Then configure your Prometheus `scrape_configs`:

```yaml
- job_name: elephantq
  static_configs:
    - targets: ["localhost:8000"]
  metrics_path: /metrics
```

## Dashboard metrics

When the dashboard is enabled (`ELEPHANTQ_DASHBOARD_ENABLED=true`), the `/api/metrics` endpoint serves the same data. You can point Grafana at this endpoint for richer visualizations.

## Health check thresholds

ElephantQ raises health warnings when system metrics cross configurable thresholds:

| Threshold | Default | Variable |
| --- | --- | --- |
| Stuck jobs | 100 | `ELEPHANTQ_STUCK_JOBS_THRESHOLD` |
| Failure rate | 50% | `ELEPHANTQ_JOB_FAILURE_RATE_THRESHOLD` |
| Memory usage | 90% | `ELEPHANTQ_MEMORY_USAGE_THRESHOLD` |
| Disk usage | 90% | `ELEPHANTQ_DISK_USAGE_THRESHOLD` |
| CPU usage | 95% | `ELEPHANTQ_CPU_USAGE_THRESHOLD` |

See [docs/feature-flags.md](feature-flags.md) for the full list of configuration variables.
