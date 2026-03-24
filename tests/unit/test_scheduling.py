"""
Tests for elephantq.features.scheduling — the scheduling subsystem.

Covers the JobScheduleBuilder (metadata, conditions, transactions),
batch scheduling, schedule() helper variants, and the depends_on()
experimental warning.
"""

import asyncio
import importlib
import os
import uuid
import warnings
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

    class DummyTx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def transaction(self):
            return DummyPool.DummyTx()

    def acquire(self):
        return DummyPool.DummyConn()


# ---------------------------------------------------------------------------
# JobScheduleBuilder core tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_schedule_builder_records_metadata(monkeypatch):
    captured = []

    async def fake_enqueue(job_func, **kwargs):
        captured.append(kwargs)
        return "job-id"

    stored_dependencies = []
    stored_timeouts = []

    async def fake_store_job_dependencies(job_id, dependencies, timeout, conn=None):
        stored_dependencies.append((job_id, dependencies, timeout))
        return True

    async def fake_store_job_timeout(job_id, timeout, conn):
        stored_timeouts.append((job_id, timeout))

    async def fake_get_context_pool():
        return DummyPool()

    monkeypatch.setattr(scheduling, "enqueue", fake_enqueue)
    monkeypatch.setattr(
        "elephantq.features.dependencies.store_job_dependencies",
        fake_store_job_dependencies,
    )
    monkeypatch.setattr(
        "elephantq.features.timeout_processor.store_job_timeout", fake_store_job_timeout
    )
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


# ---------------------------------------------------------------------------
# Batch scheduler tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# schedule() helper variants
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Transaction safety: enqueue with deps/timeout in a single transaction
# ---------------------------------------------------------------------------


class OperationTracker:
    """Tracks the order of DB operations to verify they happen in one transaction."""

    def __init__(self):
        self.operations = []
        self.enqueue_connection = None
        self.deps_connection = None
        self.timeout_connection = None


@pytest.mark.asyncio
async def test_enqueue_with_deps_uses_single_transaction(monkeypatch):
    """When dependencies are set, enqueue should pass the connection through
    so deps are stored in the same transaction as the job row."""
    tracker = OperationTracker()

    async def fake_enqueue(job_func, **kwargs):
        tracker.operations.append("enqueue")
        tracker.enqueue_connection = kwargs.get("connection")
        return "job-123"

    async def fake_store_deps(job_id, dependencies, timeout, conn=None):
        tracker.operations.append("store_deps")
        tracker.deps_connection = conn
        return True

    async def fake_store_timeout(job_id, timeout, conn):
        tracker.operations.append("store_timeout")
        tracker.timeout_connection = conn
        return True

    class FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def transaction(self):
            return self

    class FakePool:
        def acquire(self):
            return FakeConn()

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr(scheduling, "enqueue", fake_enqueue)
    monkeypatch.setattr(
        "elephantq.features.dependencies.store_job_dependencies",
        fake_store_deps,
    )
    monkeypatch.setattr(
        "elephantq.features.timeout_processor.store_job_timeout",
        fake_store_timeout,
    )
    monkeypatch.setattr("elephantq.db.context.get_context_pool", fake_get_pool)

    dep_id = str(uuid.uuid4())

    async def dummy():
        pass

    builder = scheduling.schedule_job(dummy)
    await builder.depends_on(dep_id).with_timeout(30).enqueue()

    # Both store_deps and store_timeout should have received a connection
    # (not None), proving they participate in the same transaction scope.
    assert (
        tracker.deps_connection is not None
    ), "store_job_dependencies must receive a connection for transactional safety"
    assert (
        tracker.timeout_connection is not None
    ), "store_job_timeout must receive a connection for transactional safety"


@pytest.mark.asyncio
async def test_enqueue_without_deps_keeps_simple_path(monkeypatch):
    """When no dependencies or timeout, the simple enqueue path should be used
    (no extra overhead)."""
    calls = []

    async def fake_enqueue(job_func, **kwargs):
        calls.append(kwargs)
        return "job-456"

    monkeypatch.setattr(scheduling, "enqueue", fake_enqueue)

    async def dummy():
        pass

    builder = scheduling.schedule_job(dummy)
    job_id = await builder.in_minutes(5).enqueue()

    assert job_id == "job-456"
    # No connection kwarg should be passed in the simple case
    assert "connection" not in calls[0] or calls[0].get("connection") is None


# ---------------------------------------------------------------------------
# depends_on() experimental warning
# ---------------------------------------------------------------------------


class TestDependsOnWarning:
    """Verify depends_on() emits an experimental warning."""

    def test_depends_on_emits_warning(self):
        from elephantq.features.scheduling import schedule_job

        async def dummy_job():
            pass

        dummy_job._elephantq_name = "test.dummy_job"

        builder = schedule_job(dummy_job)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            builder.depends_on("some-job-id")

            assert len(w) == 1
            assert "experimental" in str(w[0].message).lower()
            assert (
                "not yet enforce" in str(w[0].message).lower()
                or "not enforced" in str(w[0].message).lower()
            )

    def test_depends_on_still_stores_ids(self):
        from elephantq.features.scheduling import schedule_job

        async def dummy_job():
            pass

        dummy_job._elephantq_name = "test.dummy_job"

        builder = schedule_job(dummy_job)

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            builder.depends_on("id-1", "id-2")

        assert "id-1" in builder._dependencies
        assert "id-2" in builder._dependencies
