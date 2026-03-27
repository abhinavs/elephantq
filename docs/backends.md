# Storage Backends

ElephantQ supports three storage backends. The backend is selected automatically from your `database_url`, or you can set it explicitly.

## Quick start

```python
# SQLite — zero setup, local development (default for new projects)
app = ElephantQ(database_url="myapp.db")

# PostgreSQL — production
app = ElephantQ(database_url="postgresql://localhost/myapp")

# In-memory — unit tests
app = ElephantQ(backend="memory")
```

## Auto-detection

ElephantQ detects the backend from your `database_url`:

| URL pattern | Backend | Example |
|-------------|---------|---------|
| `postgresql://...` or `postgres://...` | PostgreSQL | `postgresql://localhost/myapp` |
| `*.db`, `*.sqlite`, `*.sqlite3` | SQLite | `jobs.db`, `local.sqlite` |
| `backend="memory"` | In-memory | (explicit only) |

## Comparison

| Feature | SQLite | PostgreSQL | Memory |
|---------|--------|------------|--------|
| Setup required | None | Server | None |
| Persistent | Yes (file) | Yes (server) | No |
| Concurrent workers | 1 | Unlimited | 1 |
| Push notifications | No (polling) | Yes (`pg_notify`) | No |
| Transactional enqueue | No | Yes | No |
| Production ready | No | Yes | No |
| Use case | Local dev | Production | Tests |

## SQLite backend

Zero-setup local development. No database server needed.

```bash
pip install elephantq[sqlite]
```

```python
import elephantq

elephantq.configure(database_url="elephantq.db")

@elephantq.job()
async def send_email(to: str):
    print(f"Sending to {to}")

await elephantq.enqueue(send_email, to="user@example.com")
await elephantq.run_worker(run_once=True)
```

**Limitations:**
- Single worker process only — SQLite doesn't support concurrent writers
- No `pg_notify` — workers poll for new jobs (configurable interval)
- No transactional enqueue — `connection=` parameter is silently ignored
- Good for prototyping, local dev, and simple single-process deployments

## PostgreSQL backend

Production-grade backend with full concurrency support.

```python
elephantq.configure(database_url="postgresql://user:pass@host/dbname")
await elephantq.setup()  # Run migrations
```

**Capabilities:**
- `FOR UPDATE SKIP LOCKED` — multiple workers safely dequeue without conflicts
- `pg_notify` / `LISTEN` — instant worker wakeup when jobs are enqueued
- Transactional enqueue — enqueue inside your app's database transaction
- JSONB storage — indexed JSON queries
- Partial indexes — fast queue-scoped lookups

## Memory backend

For unit tests. No persistence, no external dependencies.

```python
# In conftest.py
import elephantq

elephantq.configure(backend="memory")

@pytest.fixture(autouse=True)
async def clean():
    yield
    await elephantq.reset()
```

```python
# In tests
async def test_my_job():
    await elephantq.enqueue(my_job, user_id=42)
    await elephantq.run_worker(run_once=True)
    jobs = await elephantq.list_jobs(status="done")
    assert len(jobs) == 1
```

## Transactional enqueue across backends

Your code doesn't need to change between backends:

```python
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("INSERT INTO orders ...")
        await elephantq.enqueue(send_invoice, connection=conn, order_id=order_id)
```

- **PostgreSQL:** Job is enqueued inside the transaction. Rolls back if the transaction fails.
- **SQLite / Memory:** The `connection=` parameter is silently ignored. The job is enqueued normally.

The transactional *guarantee* is PostgreSQL-only, but the *code pattern* works everywhere.
