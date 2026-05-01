# Migrate from RQ

This guide is for teams running RQ (Redis Queue) who want to move to Soniq. RQ is intentionally minimal, so this migration is shorter than the Celery one. The mapping is mostly mechanical.

## Concept map

| RQ | Soniq |
|---|---|
| `q = Queue(connection=Redis())` | `app = Soniq(database_url="postgresql://...")` |
| `q.enqueue(func, arg)` | `await app.enqueue(func, arg=arg)` |
| `q.enqueue_in(timedelta(seconds=30), func, arg)` | `await app.enqueue(func, delay=30, arg=arg)` |
| `q.enqueue_at(datetime, func, arg)` | `await app.enqueue(func, scheduled_at=datetime, arg=arg)` |
| `rq worker` | `soniq start` |
| `rq worker queue1 queue2` | `soniq start --queues queue1,queue2` |
| `job.get_status()` | `(await app.get_job(job_id))["status"]` |
| `job.result` | `await app.get_result(job_id)` |
| RQ Dashboard | `soniq dashboard` |

## Connection vs URL

RQ takes a Redis connection object:

```python
from redis import Redis
from rq import Queue
q = Queue(connection=Redis(host="localhost", port=6379))
```

Soniq takes a `database_url` string:

```python
from soniq import Soniq
app = Soniq(database_url=os.environ["DATABASE_URL"])
```

The string form is a deliberate choice. It serialises cleanly into env vars and config files, matches what every other Python database library expects, and means most apps already have it sitting in `.env`. The migration usually looks like:

```bash
# before
REDIS_URL=redis://localhost:6379

# after
DATABASE_URL=postgresql://localhost/myapp   # already there for your ORM
```

## Argument style

RQ's `enqueue` is positional + arbitrary kwargs:

```python
q.enqueue(send_email, "dev@example.com", subject="Welcome")
```

Soniq's `enqueue` is keyword-only for job arguments. Pass the function as the first positional, then `arg=value`:

```python
await app.enqueue(send_email, to="dev@example.com", subject="Welcome")
```

The keyword-only style means there's never ambiguity between framework options (`queue`, `delay`, `priority`) and your job's own arguments.

## What you give up

RQ already runs without an extra service in some setups (if you happen to have Redis), and its API is famously small. Soniq doesn't try to be smaller -- it tries to remove Redis from your stack. If you don't already run Postgres, you're trading one service for another, which is not a win. The migration argument is strongest when:

- You already run Postgres for application data
- You want transactional enqueue (atomic with your DB writes)
- You want async-native workers
- You'd rather have one well-monitored Postgres than one Redis + one Postgres

If those don't apply, RQ is fine. Stay on it.

## Migration sequence

Because RQ's surface is small, the recommended path is direct rather than a long side-by-side period:

1. **Install Soniq** alongside RQ.
2. **Run `soniq setup`** against your Postgres database.
3. **Convert one job module.** Replace `q.enqueue(...)` calls with `await app.enqueue(...)`. If your handlers are sync, they'll keep working but Soniq runs them on a bounded thread pool -- consider porting to `async def` for the latency win.
4. **Run a Soniq worker:** `SONIQ_JOBS_MODULES=app.jobs soniq start`.
5. **Drain the RQ queue.** Stop enqueuing into Redis. Wait for the queue to empty. Stop RQ workers.
6. **Remove RQ** from `pyproject.toml` and the Redis dependency if nothing else uses it.

There is no compatibility-mode submodule for RQ (unlike `soniq.celery`). The API surface is different enough that a shim would hide more than it would help -- positional args, sync-only handlers, and the `Queue` object are all different shapes from Soniq's design.

## See also

- [Quickstart](../quickstart.md)
- [Transactional enqueue](../guides/transactional-enqueue.md)
- [Going to production](../production/going-to-production.md)
