# ElephantQ

Async-native background job queue - built for developers who want solid queues without infrastructure bloat.

## What is ElephantQ

ElephantQ is a background job system for modern async Python. It uses PostgreSQL (`LISTEN/NOTIFY`` + row locks) as the single backend for enqueueing, scheduling, retries, and monitoring—so if you already run Postgres, you already have your queue.

## Why ElephantQ exists

- Celery/RQ stacks pull in Redis and heavy configuration even for small workloads.
- Many Python queues aren’t truly async-first, making FastAPI/Starlette apps jump through hoops.
- Local development often needs multiple services just to run a job; ElephantQ keeps it to Postgres and your code.

## Why teams choose ElephantQ

- No extra infrastructure: just Postgres.
- Async from the ground up: coroutine workers fit modern Python.
- Production ready: retries, scheduling, dead-letter, monitoring are built in.
- Fast to adopt: install, point at Postgres, start a worker.

## Quick start

```bash
pip install elephantq
export ELEPHANTQ_DATABASE_URL="postgresql://postgres@localhost/elephantq"
export ELEPHANTQ_JOBS_MODULES="app.tasks"
elephantq setup
elephantq start --concurrency 4 --queues default,emails
```

```python
# app/tasks.py
import elephantq

@elephantq.job(queue="emails", retries=3)
async def send_welcome(to: str):
    print("sending welcome to", to)

await elephantq.enqueue(send_welcome, to="team@example.com")
```

## How it compares

| Feature             | ElephantQ | Celery         | RQ     | Dramatiq       | Arq    |
| ------------------- | --------- | -------------- | ------ | -------------- | ------ |
| No Redis dependency | ✅        | ❌             | ❌     | ❌             | ❌     |
| Async native        | ✅        | ⚠️             | ❌     | ⚠️             | ✅     |
| Setup complexity    | Low       | High           | Medium | Medium         | Medium |
| Infra dependencies  | Postgres  | Redis/RabbitMQ | Redis  | Redis/RabbitMQ | Redis  |
| Learning curve      | Low       | High           | Medium | Medium         | Medium |

## Features

**Core strengths**

- Async-first API: `@job`, `await enqueue`, fluent scheduling.
- Postgres-only design: one dependable backend for storage and coordination.
- Simple developer experience: minimal flags, sensible defaults, runnable examples.

**Operational benefits**

- Easy local development: only Postgres required.
- Minimal infrastructure: no brokers or side services to maintain.
- Predictable reliability: retries, dead-letter queue, and scheduling are first-class.

**Developer experience**

- Clean API surface; fluent builders like `every(10).minutes().schedule(...)`.
- Low configuration: env vars + a few CLI commands.
- Fast onboarding: `examples/` and `tests/` mirror real scenarios.

## Use cases

- Background tasks in async web apps (FastAPI, Starlette).
- Teams that want job processing without adding Redis.
- Small to medium production workloads centered on Postgres.
- Internal tools and dashboards that benefit from a built-in queue UI.

## Fluent scheduling

```python
from elephantq.features.recurring import every

@elephantq.job()
async def nightly_report():
    ...

await every(10).minutes().schedule(nightly_report)
```

For more control, use `elephantq.features.scheduling.schedule_job(...)` and chain `.with_priority()`, `.depends_on(...)`, `.with_timeout(...)`, or batch multiple jobs.

## Built for Production

- Architecture: Postgres-backed jobs, `LISTEN/NOTIFY`` for wakeups, `SKIP LOCKED`` for safe concurrency.
- Reliability: retries with backoff, dead-letter queue, persistent scheduling, at-least-once processing semantics.
- Operational tooling: CLI for workers/scheduler/dashboard, health checks, connection pool safety warnings.

## Dashboard

Monitor queues, workers, retries, and system health.

![ElephantQ Dashboard](docs/assets/elephantq_dashboard.png)

## Optional extras

```bash
pip install elephantq[dashboard]    # dashboard
pip install elephantq[monitoring]   # metrics + webhook deps
pip install elephantq[all]          # everything above
```

## Documentation

- [docs/getting-started.md](docs/getting-started.md)
- [docs/scheduling.md](docs/scheduling.md)
- [docs/features.md](docs/features.md)
- [docs/production.md](docs/production.md)
- `examples/` and `tests/`

## License

MIT License
