"""
Tests for elephantq.reset() — global reset function for test fixtures.
"""

import pytest


def test_elephantq_has_reset_function():
    """elephantq module should expose a reset() function."""
    import elephantq

    assert hasattr(elephantq, "reset")
    assert callable(elephantq.reset)


def test_elephantq_client_has_reset_method():
    """ElephantQ class should have a reset() method."""
    from elephantq.client import ElephantQ

    assert hasattr(ElephantQ, "reset")


@pytest.mark.asyncio
async def test_reset_clears_jobs_via_memory_backend():
    """reset() should clear all jobs when using MemoryBackend."""
    import uuid

    from elephantq.client import ElephantQ

    app = ElephantQ(backend="memory")
    await app._ensure_initialized()

    @app.job()
    async def dummy():
        pass

    job_name = f"{dummy.__module__}.{dummy.__name__}"
    await app.backend.create_job(
        job_id=str(uuid.uuid4()),
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

    jobs_before = await app.backend.list_jobs()
    assert len(jobs_before) == 1

    await app.reset()

    jobs_after = await app.backend.list_jobs()
    assert len(jobs_after) == 0
