"""
Tests for soniq._reset() — global reset function for test fixtures.
"""

import pytest


def test_soniq_has_reset_function():
    """soniq module should expose a _reset() function."""
    import soniq

    assert hasattr(soniq, "_reset")
    assert callable(soniq._reset)


def test_soniq_client_has_reset_method():
    """Soniq class should have a _reset() method."""
    from soniq.app import Soniq

    assert hasattr(Soniq, "_reset")


@pytest.mark.asyncio
async def test_reset_clears_jobs_via_memory_backend():
    """reset() should clear all jobs when using MemoryBackend."""
    import uuid

    from soniq.app import Soniq

    app = Soniq(backend="memory")
    await app._ensure_initialized()

    @app.job(name="dummy")
    async def dummy():
        pass

    job_name = f"{dummy.__module__}.{dummy.__name__}"
    await app._backend.create_job(
        job_id=str(uuid.uuid4()),
        job_name=job_name,
        args={},
        args_hash=None,
        max_attempts=3,
        priority=100,
        queue="default",
        unique=False,
        dedup_key=None,
        scheduled_at=None,
    )

    jobs_before = await app._backend.list_jobs()
    assert len(jobs_before) == 1

    await app._reset()

    jobs_after = await app._backend.list_jobs()
    assert len(jobs_after) == 0
