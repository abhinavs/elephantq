# Production Checklist

A pragmatic checklist for running Soniq in production. No fluff -- just what matters for reliability, observability, and operational safety.

## Required environment variables

These must be set before any worker starts.

| Variable | Example | Notes |
|----------|---------|-------|
| `SONIQ_DATABASE_URL` | `postgresql://user:pass@host/db` | PostgreSQL connection string. No SQLite in production. |
| `SONIQ_JOBS_MODULES` | `myapp.jobs,myapp.billing` | Comma-separated list of modules to import on worker startup. Workers can't process jobs they can't import. |

## Recommended environment variables

```bash
export SONIQ_LOG_LEVEL=INFO
export SONIQ_LOG_FORMAT=structured
export SONIQ_JOB_TIMEOUT=300
```

The dead-letter queue and per-job timeouts are always on. Metrics are emitted through whatever `metrics_sink` you wire onto the `Soniq(...)` constructor (default is a no-op).

## Worker configuration

Run workers as separate OS processes managed by systemd, Supervisor, or Kubernetes. Each worker process runs its own asyncio event loop. Do not share `Soniq` instances across threads.

Key settings:

| Variable | Default | Guidance |
|----------|---------|----------|
| `SONIQ_CONCURRENCY` | `4` | Number of concurrent jobs per worker process. Tune per workload and CPU -- IO-bound work tolerates higher values, CPU-bound work needs lower. |
| `--queues` (CLI flag) | all queues | Comma-separated list passed to `soniq start --queues=...`. No env-var equivalent on the worker entrypoint; if unset, the worker pulls from every queue. |
| `SONIQ_HEARTBEAT_INTERVAL` | `5` | How often workers send heartbeats (seconds). Lower values detect crashes faster but add minor DB load. |
| `SONIQ_HEARTBEAT_TIMEOUT` | `300` | Seconds before a silent worker is considered dead. Its in-flight jobs get reset to `queued`. |
| `SONIQ_CLEANUP_INTERVAL` | `300` | How often workers scan for stale peers (seconds). |

## Database

- **Dedicated user with least-privilege access.** Workers need SELECT, INSERT, UPDATE, DELETE on Soniq tables. They do not need CREATE TABLE after initial setup.
- **Run `soniq setup` during deploys.** This is idempotent and handles schema migrations.
- **Backups and PITR.** Your job data lives in PostgreSQL. Treat it like any other critical table.
- **Monitor connection pool utilization.** See the [PostgreSQL tuning guide](postgres.md) for pool sizing.

## Retries, timeouts, and idempotency

- Set retries per job, especially for external API calls. Use backoff for flaky integrations.
- Tune timeouts per job with `@app.job(timeout=...)`; the global default is `SONIQ_JOB_TIMEOUT=300` seconds.
- **Design all jobs to be idempotent.** Soniq provides at-least-once delivery - a job may execute more than once if a worker crashes after execution but before the status update. Use database upserts, dedup checks, or idempotency keys for side effects like emails or payments.

## Queue design

- Split queues by workload: `emails`, `media`, `billing`. Run dedicated worker groups per queue so you can scale them independently.
- Keep job payloads small. Pass database IDs or S3 keys, not the actual data. Large payloads bloat the jobs table and slow down queries.
- For latency-sensitive queues, run dedicated worker pools with higher concurrency and a smaller queue set.

## Observability

Enable structured logging and metrics collection:

```bash
export SONIQ_LOG_FORMAT=structured    # JSON output, easy to ship
```

`prometheus_client` ships with the default `pip install soniq` - no
extra needed. Wire it via `Soniq(metrics_sink=PrometheusMetricsSink())`
or leave the default `NoopMetricsSink` in place if you do not scrape.

### What gets tracked

- Job counts by status (queued, processing, done, cancelled) plus dead-letter rows from `soniq_dead_letter_jobs`
- Processing time (average, p95, p99)
- Throughput (jobs per minute)
- Success rate
- Per-queue stats (depth, processing time, throughput)

### CLI access

```bash
soniq status --verbose
```

### Prometheus scraping

When metrics are enabled, counters are registered with `prometheus-client` (a default runtime dependency in 0.0.3+, no extra to install). Mount the endpoint in your FastAPI app:

```python
from prometheus_client import make_asgi_app

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

Prometheus config:

```yaml
- job_name: soniq
  static_configs:
    - targets: ["localhost:8000"]
  metrics_path: /metrics
```

If you run `soniq dashboard`, the `/api/metrics` endpoint serves the same data. Point Grafana at it for richer visualizations.

### Health check thresholds

Soniq raises health warnings when metrics cross these thresholds:

| Threshold | Default | Variable |
|-----------|---------|----------|
| Stuck jobs | 100 | `SONIQ_STUCK_JOBS_THRESHOLD` |
| Failure rate | 50% | `SONIQ_JOB_FAILURE_RATE_THRESHOLD` |
| Memory usage | 90% | `SONIQ_MEMORY_USAGE_THRESHOLD` |
| Disk usage | 90% | `SONIQ_DISK_USAGE_THRESHOLD` |
| CPU usage | 95% | `SONIQ_CPU_USAGE_THRESHOLD` |

## Operational pieces to wire up

| What | How |
|------|-----|
| Per-job timeouts | Always on. Default `SONIQ_JOB_TIMEOUT=300`. Override per-job with `@app.job(timeout=...)`. |
| Dead-letter queue | Always on. Inspect and replay with `soniq dead-letter list` / `soniq dead-letter replay <id>`. |
| Metrics | Pass `metrics_sink=PrometheusMetricsSink()` to `Soniq(...)` and scrape `/metrics`. |
| Logging | Set `SONIQ_LOG_FORMAT=structured` for JSON logs your aggregator can parse. |
| Recurring jobs | Run `soniq scheduler` alongside your worker. |
| Dashboard | `pip install soniq[dashboard]` and run `soniq dashboard`. Set `SONIQ_DASHBOARD_WRITE_ENABLED=true` only in trusted environments. |

## Production defaults

Conservative values that work well for most deployments:

| Variable | Value | Notes |
|----------|-------|-------|
| `SONIQ_CONCURRENCY` | `4` | Safe starting point. Increase for IO-bound workloads. |
| `--queues` (CLI flag) | all queues | Pass `--queues=urgent,default` to scope a worker group to specific queues. |
| `SONIQ_MAX_RETRIES` | `3` | Per-job override with `@app.job(max_retries=5)`. |
| `SONIQ_JOB_TIMEOUT` | `300` | 5 minutes. Override per-job with `@app.job(timeout=600)`. Set to `0` to disable. |
| `SONIQ_HEARTBEAT_INTERVAL` | `5` | Seconds between heartbeats. |
| `SONIQ_CLEANUP_INTERVAL` | `300` | 5 minutes between stale worker scans. |
| `SONIQ_HEARTBEAT_TIMEOUT` | `300` | 5 minutes of silence before a worker is marked dead. |
| `SONIQ_POOL_MIN_SIZE` | `5` | Minimum DB connections in the pool. |
| `SONIQ_POOL_MAX_SIZE` | `20` | Maximum DB connections. Must be >= concurrency + headroom. |
| `SONIQ_POOL_HEADROOM` | `2` | Extra connections for listener/heartbeat. |
| `SONIQ_RESULT_TTL` | `300` | Completed jobs are cleaned up after 5 minutes. |
| `SONIQ_LOG_LEVEL` | `INFO` | Use `DEBUG` only during troubleshooting. |

## Known limitations

- **No named concurrency limits.** `unique=True` and `dedup_key` gate queueing, not execution. If you need "at most N jobs for logical key X at a time", impose that upstream.
- **Recurring scheduler requires session-pooled Postgres.** The advisory-lock leader guard needs the lock to persist across statements on the same session. PgBouncer in transaction-pooling mode breaks this; switch to session-pooling or a direct Postgres connection.
- **SQLite backend is single-writer.** Use PostgreSQL for anything with more than one worker process.
- **Workers are Python-only.** For cross-language consumers, use a broker (RabbitMQ, Kafka) instead.

Also summarised in the README's Known limitations section.
