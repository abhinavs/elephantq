# Testing with ElephantQ

This guide covers practical patterns for testing applications that use ElephantQ. All examples use pytest with the in-memory backend so your tests stay fast and need zero external services.

## Use MemoryBackend for unit tests

ElephantQ ships with a `MemoryBackend` that keeps everything in-process. Pass `backend="memory"` when creating an instance:

```python
from elephantq import ElephantQ

app = ElephantQ(backend="memory")
```

No Postgres, no SQLite files, no cleanup scripts. State lives in Python dicts and disappears when the process exits.

## Pytest fixture

A reusable fixture that gives each test a clean ElephantQ instance:

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

Every test that accepts `eq` gets its own isolated queue with no leftover jobs from previous runs.

## Testing job functions directly

Job functions are regular async functions. You can call them without enqueuing:

```python
@eq.job(queue="emails")
async def send_welcome(to: str):
    return f"sent to {to}"

# Call directly — no queue involved
result = await send_welcome("alice@example.com")
assert result == "sent to alice@example.com"
```

This is the fastest way to test business logic. Save round-trip tests for integration coverage.

## Testing enqueue + process round-trips

Use `run_worker(run_once=True)` to drain the queue in your test:

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

`run_once=True` processes all available jobs and returns immediately — no polling loop, no timeouts.

## Checking job status after enqueue

```python
async def test_job_status(eq):
    @eq.job()
    async def noop():
        pass

    job_id = await eq.enqueue(noop)
    status = await eq.get_job_status(job_id)
    assert status["status"] == "queued"
```

## Resetting state between tests

If you share a single `ElephantQ` instance across tests (for example, a session-scoped fixture), call `reset()` to wipe all jobs and workers:

```python
@pytest.fixture(autouse=True)
async def clean_slate(eq):
    yield
    await eq.reset()
```

`reset()` truncates the job and worker tables (or clears the in-memory dicts) without tearing down the connection.

## Tips

- Keep unit tests on `MemoryBackend`. Reserve Postgres tests for CI or an integration suite.
- Test retries by enqueuing a job that raises, then calling `run_worker(run_once=True)` multiple times.
- Use `await eq.list_jobs(status="failed")` to assert on failure counts.
- `JobContext` is injected automatically — add a `ctx: JobContext` parameter to your job function to inspect it during tests.
