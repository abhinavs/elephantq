# Migrating to Soniq

Most teams considering Soniq are already running Celery + Redis or RQ + Redis. Both are solid tools. The reason to migrate is usually one of these:

- **Operating two services is one too many.** Postgres is already in your stack. Why run Redis just to track jobs?
- **Transactional enqueue.** Soniq can insert the job inside the same transaction as your business write. No "row exists but the job never fired" bugs. Celery and RQ cannot do this -- the broker is a separate service.
- **Async-native workers.** Soniq workers run on `asyncio` from the ground up. If your app is FastAPI / Starlette / async SQLAlchemy, this matches the rest of your stack.
- **Built-in dashboard and dead-letter queue.** No Flower or RQ Dashboard to deploy and authenticate separately.

The cost is real, though, and we want to be honest about it:

- **Throughput ceiling.** Postgres row locking has limits. If you need sustained 10k+ jobs/sec, Redis-backed queues remain a better fit.
- **Python-only.** Soniq has no story for cross-language consumers. Use a broker (RabbitMQ, Kafka) if your workers are in Go, Node, or Rust.
- **No DAG orchestration.** Soniq runs individual jobs. If you need dependency graphs and complex workflows, Prefect or Airflow handle that better.

If those tradeoffs are acceptable, the next two guides walk through the actual migration:

- [Migrate from Celery](from-celery.md) -- the most common path. Includes a concept map, a compatibility-mode pattern that lets you cut over gradually, and the step-by-step sequence we recommend.
- [Migrate from RQ](from-rq.md) -- shorter. RQ's API surface is smaller, so the mapping is more direct.

## A note on compatibility mode

The Celery guide shows a `from soniq.celery import Soniq` pattern that aliases `@app.task` to `@app.job`. **It is not a permanent feature.** It exists to let you move job-by-job during a migration without a flag day. The import path itself (`soniq.celery`) is the visible reminder that the file is mid-migration. Once a file is fully on Soniq idioms, switch back to `from soniq import Soniq` and `@app.job`.

We deliberately do *not* alias Celery's `.delay(arg)` and `.apply_async(...)` -- those would hide the `await` that Soniq's enqueue requires, which creates async bugs that are hard to diagnose. Replacing call sites from `task.delay(arg)` to `await app.enqueue(task, arg=arg)` is the migration surfacing exactly what changed.

There is no equivalent compatibility class for RQ. RQ's `Queue.enqueue(func, *args, **kwargs)` and Soniq's keyword-only API are structurally different enough that a shim would obscure more than it would help.
