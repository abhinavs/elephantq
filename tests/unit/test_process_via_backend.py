"""
Tests for the backend-based job processing path.

process_job_via_backend uses StorageBackend instead of raw asyncpg.Connection.
"""

import pytest

from elephantq.backends.memory import MemoryBackend
from elephantq.core.registry import JobRegistry


@pytest.mark.asyncio
async def test_process_via_backend_exists():
    from elephantq.core.processor import process_job_via_backend

    assert callable(process_job_via_backend)


@pytest.mark.asyncio
async def test_process_via_backend_runs_job():
    from elephantq.core.processor import process_job_via_backend

    backend = MemoryBackend()
    await backend.initialize()
    registry = JobRegistry()

    executed = []

    @registry.register_job
    async def my_task(msg: str):
        executed.append(msg)

    job_name = f"{my_task.__module__}.{my_task.__name__}"
    await backend.create_job(
        job_id="job-1",
        job_name=job_name,
        args='{"msg": "hello"}',
        args_hash=None,
        max_attempts=3,
        priority=100,
        queue="default",
        unique=False,
        queueing_lock=None,
        scheduled_at=None,
    )

    result = await process_job_via_backend(
        backend=backend,
        job_registry=registry,
        queues=["default"],
    )

    assert result is True
    assert executed == ["hello"]

    job = await backend.get_job("job-1")
    assert job["status"] == "done"


@pytest.mark.asyncio
async def test_process_via_backend_returns_false_when_empty():
    from elephantq.core.processor import process_job_via_backend

    backend = MemoryBackend()
    await backend.initialize()
    registry = JobRegistry()

    result = await process_job_via_backend(
        backend=backend,
        job_registry=registry,
        queues=["default"],
    )
    assert result is False


@pytest.mark.asyncio
async def test_process_via_backend_handles_failure_with_retry():
    from elephantq.core.processor import process_job_via_backend

    backend = MemoryBackend()
    await backend.initialize()
    registry = JobRegistry()

    @registry.register_job
    async def failing_task():
        raise RuntimeError("boom")

    job_name = f"{failing_task.__module__}.{failing_task.__name__}"
    await backend.create_job(
        job_id="job-fail",
        job_name=job_name,
        args="{}",
        args_hash=None,
        max_attempts=3,
        priority=100,
        queue="default",
        unique=False,
        queueing_lock=None,
        scheduled_at=None,
    )

    result = await process_job_via_backend(
        backend=backend,
        job_registry=registry,
        queues=["default"],
    )

    assert result is True
    job = await backend.get_job("job-fail")
    assert job["status"] == "queued"  # Retried, not dead-lettered (1 of 3 attempts)
    assert job["attempts"] == 1


@pytest.mark.asyncio
async def test_process_via_backend_dead_letters_after_max_attempts():
    from elephantq.core.processor import process_job_via_backend

    backend = MemoryBackend()
    await backend.initialize()
    registry = JobRegistry()

    @registry.register_job
    async def always_fails():
        raise RuntimeError("permanent")

    job_name = f"{always_fails.__module__}.{always_fails.__name__}"
    await backend.create_job(
        job_id="job-dead",
        job_name=job_name,
        args="{}",
        args_hash=None,
        max_attempts=2,  # Only 2 attempts total
        priority=100,
        queue="default",
        unique=False,
        queueing_lock=None,
        scheduled_at=None,
    )

    # First attempt
    await process_job_via_backend(
        backend=backend, job_registry=registry, queues=["default"]
    )
    job = await backend.get_job("job-dead")
    assert job["status"] == "queued"  # attempt 1, retried

    # Second attempt — should dead-letter
    await process_job_via_backend(
        backend=backend, job_registry=registry, queues=["default"]
    )
    job = await backend.get_job("job-dead")
    assert job["status"] == "dead_letter"
