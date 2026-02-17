# Production Checklist

This is a pragmatic checklist for running ElephantQ in production. It focuses on reliability, observability, and operational safety.

## 1. Database

- Use a dedicated PostgreSQL user with least‑privilege access.
- Run migrations during deployment: `elephantq setup`.
- Ensure backups and PITR are configured.
- Monitor connection pool utilization.

## 2. Workers

- Run workers as separate processes (systemd/supervisor/k8s).
- Use multiple workers per queue for throughput.
- Set `ELEPHANTQ_JOBS_MODULES` so workers can import job code.
- Tune concurrency per workload.

## 3. Queue Design

- Split queues by workload: `emails`, `media`, `billing`.
- Run dedicated worker groups per queue.
- Keep job payloads small; pass IDs instead of large blobs.

## 4. Retries & Timeouts

- Set retries per job, especially for external APIs.
- Use backoff for flaky integrations.
- Enable timeouts for long‑running tasks.

Recommended flags:

```bash
export ELEPHANTQ_TIMEOUTS_ENABLED=true
```

## 5. Observability

- Enable structured logs and ship to your log system.
- Enable metrics for dashboards/alerts.

Recommended flags:

```bash
export ELEPHANTQ_LOGGING_ENABLED=true
export ELEPHANTQ_METRICS_ENABLED=true
```

## 6. Dead‑Letter Queue

- Enable dead‑letter queue in production.
- Create a routine to inspect and retry failed jobs.

Recommended flags:

```bash
export ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED=true
```

## 7. Dashboard

- Use the dashboard in read‑only mode by default.
- Enable write actions only in trusted environments.

Recommended flags:

```bash
export ELEPHANTQ_DASHBOARD_ENABLED=true
# Optional: allow write actions
# export ELEPHANTQ_DASHBOARD_WRITE_ENABLED=true
```

## 8. Deployment Templates

Reference configurations:

- `deployment/README.md`
- `deployment/elephantq-worker.service`
- `deployment/elephantq-dashboard.service`
- `deployment/kubernetes.yaml`
- `deployment/docker-compose.yml`

## 9. Production Defaults (Suggested)

These are conservative defaults that work well for most deployments:

```bash
# Worker behavior
export ELEPHANTQ_DEFAULT_CONCURRENCY=4
export ELEPHANTQ_DEFAULT_QUEUES=default

# Health and cleanup
export ELEPHANTQ_WORKER_HEARTBEAT_INTERVAL=5
export ELEPHANTQ_CLEANUP_INTERVAL=300
export ELEPHANTQ_STALE_WORKER_THRESHOLD=300

# Retries and timeouts
export ELEPHANTQ_DEFAULT_MAX_RETRIES=3
export ELEPHANTQ_TIMEOUTS_ENABLED=true
```

Tune `ELEPHANTQ_DEFAULT_CONCURRENCY` per workload and CPU. For latency‑sensitive queues, run dedicated worker pools with higher concurrency and a smaller queue set.

## 10. Deployment Recipes

Common paths to production:

- **Systemd**: `deployment/elephantq-worker.service` and `deployment/elephantq-dashboard.service`\n  Best for simple Linux hosts with direct process control.
- **Kubernetes**: `deployment/kubernetes.yaml`\n  Best for containerized environments with autoscaling.\n- **Docker Compose**: `deployment/docker-compose.yml`\n  Best for staging or small production deployments.

## 9. Recommended Environment Variables

```bash
# Required
export ELEPHANTQ_DATABASE_URL="postgresql://user:pass@host/db"
export ELEPHANTQ_JOBS_MODULES="your_app.jobs"

# Suggested
export ELEPHANTQ_LOG_LEVEL=INFO
export ELEPHANTQ_SCHEDULING_ENABLED=true
```
