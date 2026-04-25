"""
TEST-02: BatchScheduler.add() should return JobScheduleBuilder so users
can chain .with_priority(), .with_queue(), etc.

Must fail before FIX-02 and pass after.
"""

import importlib
import os
import uuid

import pytest

os.environ.setdefault("SONIQ_SCHEDULING_ENABLED", "true")
os.environ.setdefault("SONIQ_DEPENDENCIES_ENABLED", "true")
os.environ.setdefault("SONIQ_TIMEOUTS_ENABLED", "true")

import soniq.settings as settings_module  # noqa: E402
from soniq.features import scheduling  # noqa: E402
from soniq.features.scheduling import BatchScheduler  # noqa: E402


@pytest.fixture(autouse=True)
def enable_scheduling(monkeypatch):
    monkeypatch.setenv("SONIQ_SCHEDULING_ENABLED", "true")
    monkeypatch.setenv("SONIQ_DEPENDENCIES_ENABLED", "true")
    monkeypatch.setenv("SONIQ_TIMEOUTS_ENABLED", "true")
    settings_module._settings = None
    importlib.reload(settings_module)
    importlib.reload(scheduling)
    yield


async def dummy_job_a():
    pass


async def dummy_job_b():
    pass


def test_batch_add_returns_job_schedule_builder():
    """batch.add(job) must return a JobScheduleBuilder, not the BatchScheduler."""
    batch = BatchScheduler()
    result = batch.add(dummy_job_a)
    assert (
        type(result).__name__ == "JobScheduleBuilder"
    ), f"Expected JobScheduleBuilder, got {type(result).__name__}"


def test_batch_add_chaining_with_priority():
    """batch.add(job).with_priority(30) should work without error."""
    batch = BatchScheduler()
    builder = batch.add(dummy_job_a).with_priority(30)
    assert type(builder).__name__ == "JobScheduleBuilder"
    assert builder._priority == 30


def test_batch_add_chaining_with_queue():
    """batch.add(job).with_queue("reports") should work without error."""
    batch = BatchScheduler()
    builder = batch.add(dummy_job_b).in_queue("reports")
    assert type(builder).__name__ == "JobScheduleBuilder"
    assert builder._queue == "reports"


class _FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def transaction(self):
        return self


class _FakePool:
    def __init__(self):
        self.acquire_calls = 0

    def acquire(self):
        self.acquire_calls += 1
        return _FakeConn()


@pytest.fixture
def fake_pool(monkeypatch):
    pool = _FakePool()

    async def fake_get_context_pool():
        return pool

    import soniq.db.context as db_context

    monkeypatch.setattr(db_context, "get_context_pool", fake_get_context_pool)
    return pool


@pytest.mark.asyncio
async def test_batch_add_chaining_enqueue_all(monkeypatch, fake_pool):
    """After chaining via add(), enqueue_all() should still enqueue all jobs."""
    captured = []

    async def fake_enqueue(job_func, **kwargs):
        captured.append(kwargs)
        return str(uuid.uuid4())

    monkeypatch.setattr(scheduling, "enqueue", fake_enqueue)

    batch = BatchScheduler()
    batch.add(dummy_job_a).with_priority(30)
    batch.add(dummy_job_b).in_queue("reports")

    job_ids = await batch.enqueue_all()
    assert len(job_ids) == 2
    assert captured[0]["priority"] == 30
    assert captured[1]["queue"] == "reports"


@pytest.mark.asyncio
async def test_batch_enqueue_all_uses_single_connection(monkeypatch, fake_pool):
    """N batched jobs should acquire exactly one pooled connection."""
    seen_connections = []

    async def fake_enqueue(job_func, **kwargs):
        seen_connections.append(kwargs.get("connection"))
        return str(uuid.uuid4())

    monkeypatch.setattr(scheduling, "enqueue", fake_enqueue)

    batch = BatchScheduler()
    for _ in range(5):
        batch.add(dummy_job_a)

    job_ids = await batch.enqueue_all()

    assert len(job_ids) == 5
    assert fake_pool.acquire_calls == 1
    assert len(set(id(c) for c in seen_connections)) == 1
    assert seen_connections[0] is not None


@pytest.mark.asyncio
async def test_batch_enqueue_all_propagates_error(monkeypatch, fake_pool):
    """A mid-batch failure should propagate (transaction rollback responsibility
    is on the DB layer; here we just assert no silent swallow)."""
    counter = {"n": 0}

    async def fake_enqueue(job_func, **kwargs):
        counter["n"] += 1
        if counter["n"] == 3:
            raise RuntimeError("boom")
        return str(uuid.uuid4())

    monkeypatch.setattr(scheduling, "enqueue", fake_enqueue)

    batch = BatchScheduler()
    for _ in range(5):
        batch.add(dummy_job_a)

    with pytest.raises(RuntimeError, match="boom"):
        await batch.enqueue_all()

    assert fake_pool.acquire_calls == 1
