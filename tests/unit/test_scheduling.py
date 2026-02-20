import asyncio
import importlib
import os
import uuid
from datetime import datetime, timedelta

import pytest

# Ensure the required feature flags are enabled before importing scheduling helpers
os.environ.setdefault("ELEPHANTQ_SCHEDULING_ENABLED", "true")
os.environ.setdefault("ELEPHANTQ_DEPENDENCIES_ENABLED", "true")
os.environ.setdefault("ELEPHANTQ_TIMEOUTS_ENABLED", "true")

import elephantq.settings as settings_module  # noqa: E402
from elephantq.features import scheduling  # noqa: E402


@pytest.fixture(autouse=True)
def enable_scheduling_features(monkeypatch):
    """Enable feature flags for scheduling-related tests."""
    monkeypatch.setenv("ELEPHANTQ_SCHEDULING_ENABLED", "true")
    monkeypatch.setenv("ELEPHANTQ_DEPENDENCIES_ENABLED", "true")
    monkeypatch.setenv("ELEPHANTQ_TIMEOUTS_ENABLED", "true")
    # Reload settings and scheduling modules so require_feature picks up the flags
    settings_module._settings = None
    importlib.reload(settings_module)
    importlib.reload(scheduling)
    yield


class DummyPool:
    """Simple pool stub that satisfies async context manager usage."""

    class DummyConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def acquire(self):
        return DummyPool.DummyConn()


@pytest.mark.asyncio
async def test_job_schedule_builder_records_metadata(monkeypatch):
    captured = []

    async def fake_enqueue(job_func, **kwargs):
        captured.append(kwargs)
        return "job-id"

    stored_dependencies = []
    stored_timeouts = []

    async def fake_store_job_dependencies(job_id, dependencies, timeout):
        stored_dependencies.append((job_id, dependencies, timeout))
        return True

    async def fake_store_job_timeout(job_id, timeout, conn):
        stored_timeouts.append((job_id, timeout))

    async def fake_get_context_pool():
        return DummyPool()

    monkeypatch.setattr(scheduling, "enqueue", fake_enqueue)
    monkeypatch.setattr("elephantq.features.dependencies.store_job_dependencies", fake_store_job_dependencies)
    monkeypatch.setattr("elephantq.features.timeout_processor.store_job_timeout", fake_store_job_timeout)
    monkeypatch.setattr("elephantq.db.context.get_context_pool", fake_get_context_pool)

    async def dummy_job(message: str):
        return message

    builder = scheduling.schedule_job(dummy_job)
    dependency_id = str(uuid.uuid4())

    job_id = await (
        builder.in_minutes(5)
        .with_priority(7)
        .in_queue("critical")
        .with_tags("batch")
        .with_retries(2)
        .depends_on(dependency_id)
        .with_timeout(45)
        .enqueue(message="hello")
    )

    assert job_id == "job-id"
    assert captured[0]["priority"] == 7
    assert captured[0]["queue"] == "critical"
    assert "scheduled_at" in captured[0]
    assert stored_dependencies[0][1] == [dependency_id]
    assert stored_timeouts[0][1] == 45
    metadata = scheduling.get_job_metadata("job-id")
    assert metadata["timeout"] == 45
    assert metadata["tags"] == ["batch"]


@pytest.mark.asyncio
async def test_job_schedule_builder_respects_condition(monkeypatch):
    monkeypatch.setattr(scheduling, "enqueue", lambda *_: asyncio.Future())
    builder = scheduling.schedule_job(lambda: None).if_condition(lambda: False)
    with pytest.raises(RuntimeError):
        await builder.enqueue()


@pytest.mark.asyncio
async def test_batch_scheduler_applies_batch_metadata(monkeypatch):
    captured = []

    async def fake_enqueue(job_func, **kwargs):
        captured.append(kwargs)
        return str(uuid.uuid4())

    monkeypatch.setattr(scheduling, "enqueue", fake_enqueue)

    async def dummy_job():
        pass

    batch = scheduling.create_batch()
    batch.add_job(dummy_job).in_seconds(10)
    batch.add_job(dummy_job).in_seconds(20)
    job_ids = await batch.enqueue_all(batch_priority=15)

    assert len(job_ids) == 2
    metadata = scheduling.get_job_metadata(job_ids[0])
    assert metadata is not None
    assert any(tag.startswith("batch:") for tag in metadata["tags"])
    assert any(tag.startswith("batch_item:") for tag in metadata["tags"])
    assert captured[0]["priority"] == 15


@pytest.mark.asyncio
async def test_schedule_helper_variants(monkeypatch):
    scheduled = []

    async def fake_enqueue(job_func, **kwargs):
        scheduled.append(kwargs.get("scheduled_at"))
        return "generated-job"

    monkeypatch.setattr(scheduling, "enqueue", fake_enqueue)

    future_time = datetime.now() + timedelta(minutes=1)
    await scheduling.schedule(lambda: None, future_time)
    await scheduling.schedule(lambda: None, 10)
    await scheduling.schedule(lambda: None, timedelta(seconds=30))

    assert len(scheduled) == 3
    assert isinstance(scheduled[0], datetime)
