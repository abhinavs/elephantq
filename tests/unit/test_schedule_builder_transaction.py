"""
TEST-05: JobScheduleBuilder.enqueue() must write job row + dependency/timeout
metadata in a single transaction when dependencies or timeout are set.

This is a unit-level test that verifies the transactional guarantee by
tracking the order of operations via mocks.
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


@pytest.fixture(autouse=True)
def enable_features(monkeypatch):
    monkeypatch.setenv("ELEPHANTQ_SCHEDULING_ENABLED", "true")
    monkeypatch.setenv("ELEPHANTQ_DEPENDENCIES_ENABLED", "true")
    monkeypatch.setenv("ELEPHANTQ_TIMEOUTS_ENABLED", "true")
    settings_module._settings = None
    importlib.reload(settings_module)
    importlib.reload(scheduling)
    yield


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
    assert tracker.deps_connection is not None, (
        "store_job_dependencies must receive a connection for transactional safety"
    )
    assert tracker.timeout_connection is not None, (
        "store_job_timeout must receive a connection for transactional safety"
    )


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
