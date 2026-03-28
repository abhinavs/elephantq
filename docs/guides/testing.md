# Testing

Practical patterns for testing applications that use ElephantQ. All examples use pytest.

## Memory backend for unit tests

The fastest way to test. No external services, no cleanup scripts. State lives in Python dicts and disappears when the process exits:

```python
from elephantq import ElephantQ

app = ElephantQ(backend="memory")
```

## Pytest fixture

A reusable fixture that gives each test a clean, isolated ElephantQ instance:

```python
import pytest
from elephantq import ElephantQ

@pytest.fixture
async def eq():
    app = ElephantQ(backend="memory")
    yield app
    await app.reset()
    await app.close()
```

Every test that accepts `eq` gets its own queue with no leftover state from previous runs.

## Testing job logic directly

Job functions are regular async functions. Call them without enqueuing:

```python
@eq.job(queue="emails")
async def send_welcome(to: str):
    return f"sent to {to}"

# Call directly -- no queue involved
result = await send_welcome("alice@example.com")
assert result == "sent to alice@example.com"
```

This is the fastest way to test business logic. Save round-trip tests for integration coverage.

## Enqueue + process round-trips

Use `run_worker(run_once=True)` to drain the queue synchronously in your test:

```python
async def test_round_trip(eq):
    results = []

    @eq.job(queue="default")
    async def track_call(value: str):
        results.append(value)

    await eq.enqueue(track_call, value="hello")
    await eq.run_worker(run_once=True)

    assert results == ["hello"]
```

`run_once=True` processes all available jobs and returns immediately. No polling loop, no timeouts, no flaky sleeps.

## Checking job status

```python
async def test_job_status(eq):
    @eq.job()
    async def noop():
        pass

    job_id = await eq.enqueue(noop)
    status = await eq.get_job_status(job_id)
    assert status["status"] == "queued"
```

## Testing retries

Enqueue a job that raises, then call `run_worker(run_once=True)` multiple times:

```python
async def test_retry_behavior(eq):
    attempts = []

    @eq.job(max_retries=2, retry_delay=0)
    async def flaky_job():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("not yet")

    await eq.enqueue(flaky_job)
    await eq.run_worker(run_once=True)  # attempt 1: fails
    await eq.run_worker(run_once=True)  # attempt 2: fails
    await eq.run_worker(run_once=True)  # attempt 3: succeeds

    assert len(attempts) == 3
```

## Testing failed jobs

Use `list_jobs(status="failed")` to assert on failure counts:

```python
async def test_failure_tracking(eq):
    @eq.job(max_retries=0)
    async def always_fails():
        raise ValueError("boom")

    await eq.enqueue(always_fails)
    await eq.run_worker(run_once=True)

    failed = await eq.list_jobs(status="dead_letter")
    assert len(failed) == 1
```

## Resetting state between tests

If you share a single instance across tests (for example, a session-scoped fixture), call `reset()` to wipe all jobs and workers:

```python
@pytest.fixture(autouse=True)
async def clean_slate(eq):
    yield
    await eq.reset()
```

`reset()` truncates job and worker tables (or clears the in-memory dicts) without tearing down the connection.

## SQLite for integration tests

When you need to test against a real SQL database but don't want to run Postgres in CI:

```python
import pytest
from elephantq import ElephantQ

@pytest.fixture
async def eq(tmp_path):
    db_path = str(tmp_path / "test.db")
    app = ElephantQ(backend="sqlite", database_url=db_path)
    await app.setup()
    yield app
    await app.close()
```

SQLite gives you real SQL semantics (constraints, transactions) without external dependencies. Use `tmp_path` so each test gets a fresh database file that's automatically cleaned up.

## Tips

- Keep unit tests on the Memory backend. Reserve Postgres tests for CI or a dedicated integration suite.
- Use `run_once=True` liberally. It's deterministic and fast.
- `JobContext` is injected automatically. Add a `ctx: JobContext` parameter to your job function to inspect context during tests.
- For hooks testing, register `@eq.before_job` / `@eq.after_job` / `@eq.on_error` and assert they were called with the expected context.
