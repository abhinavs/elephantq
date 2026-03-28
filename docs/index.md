# ElephantQ

Background jobs for Python. Powered by the Postgres you already have.

ElephantQ is an async-first job queue that uses your existing PostgreSQL database as the backend. No Redis. No RabbitMQ. One dependency, one place your data lives.

## Get started

- [Quickstart](getting-started/quickstart.md) — working job in under 5 minutes
- [Installation](getting-started/installation.md) — extras, backends, Python versions

## Learn

- [Jobs](concepts/jobs.md) — defining, enqueuing, and configuring jobs
- [Queues](concepts/queues.md) — named queues, priorities, routing
- [Workers](concepts/workers.md) — concurrency, heartbeat, crash recovery
- [Retries](concepts/retries.md) — backoff strategies, delay configuration
- [Scheduling](concepts/scheduling.md) — delayed jobs, recurring cron tasks
- [Dead-letter queue](concepts/dead-letter.md) — inspecting and retrying failed jobs

## Integrate

- [FastAPI](guides/fastapi.md) — lifespan management, route handlers, worker setup
- [Transactional enqueue](guides/transactional-enqueue.md) — atomic job + data commits
- [Common patterns](guides/common-patterns.md) — hooks, dedup, validation, results
- [Testing](guides/testing.md) — memory backend, fixtures, isolation

## Reference

- [API](api/elephantq.md) — ElephantQ class, enqueue, schedule, hooks
- [CLI](cli/commands.md) — setup, start, status, dead-letter, dashboard
- [Dashboard](dashboard/overview.md) — web UI for monitoring

## Ship

- [Production checklist](production/checklist.md) — env vars, workers, observability
- [PostgreSQL tuning](production/postgres.md) — connection pooling, PgBouncer
- [Deployment](production/deployment.md) — systemd, Docker, Kubernetes
- [Reliability](production/reliability.md) — guarantees, idempotency, failure modes

## Recipes

- [Email jobs](recipes/email-jobs.md)
- [File processing](recipes/file-processing.md)
- [Scheduled reports](recipes/scheduled-reports.md)
- [Webhook delivery](recipes/webhook-delivery.md)

## Migrate

- [From Celery](migration/from-celery.md)
- [From RQ](migration/from-rq.md)
