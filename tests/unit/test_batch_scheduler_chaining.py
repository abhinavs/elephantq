"""
TEST-02: BatchScheduler.add() should return JobScheduleBuilder so users
can chain .with_priority(), .with_queue(), etc.

Must fail before FIX-02 and pass after.
"""

import importlib
import os
import uuid

import pytest

os.environ.setdefault("ELEPHANTQ_SCHEDULING_ENABLED", "true")
os.environ.setdefault("ELEPHANTQ_DEPENDENCIES_ENABLED", "true")
os.environ.setdefault("ELEPHANTQ_TIMEOUTS_ENABLED", "true")

import elephantq.settings as settings_module  # noqa: E402
from elephantq.features import scheduling  # noqa: E402
from elephantq.features.scheduling import BatchScheduler  # noqa: E402


@pytest.fixture(autouse=True)
def enable_scheduling(monkeypatch):
    monkeypatch.setenv("ELEPHANTQ_SCHEDULING_ENABLED", "true")
    monkeypatch.setenv("ELEPHANTQ_DEPENDENCIES_ENABLED", "true")
    monkeypatch.setenv("ELEPHANTQ_TIMEOUTS_ENABLED", "true")
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


@pytest.mark.asyncio
async def test_batch_add_chaining_enqueue_all(monkeypatch):
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
