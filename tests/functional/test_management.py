"""
Test that Soniq management methods work with MemoryBackend.

These methods currently use raw asyncpg SQL and crash on non-Postgres backends.
After routing through the backend, they should work on all backends.
"""

import pytest

from soniq import Soniq


@pytest.fixture
async def app():
    app = Soniq(backend="memory")
    await app._ensure_initialized()
    yield app
    await app.close()


async def test_get_job(app):
    """get_job should work on MemoryBackend."""

    @app.job(name="noop")
    async def noop():
        pass

    job_id = await app.enqueue("noop")
    status = await app.get_job(job_id)
    assert status is not None
    assert status["status"] == "queued"
    assert status["id"] == job_id


async def test_get_job_not_found(app):
    """get_job returns None for nonexistent job."""
    status = await app.get_job("nonexistent-id")
    assert status is None


async def test_cancel_job(app):
    """cancel_job should work on MemoryBackend."""

    @app.job(name="noop")
    async def noop():
        pass

    job_id = await app.enqueue("noop")
    result = await app.cancel_job(job_id)
    assert result is True

    status = await app.get_job(job_id)
    assert status["status"] == "cancelled"


async def test_cancel_nonexistent_returns_false(app):
    """cancel_job returns False for nonexistent job."""
    result = await app.cancel_job("nonexistent-id")
    assert result is False


async def test_delete_job(app):
    """delete_job should work on MemoryBackend."""

    @app.job(name="noop")
    async def noop():
        pass

    job_id = await app.enqueue("noop")
    result = await app.delete_job(job_id)
    assert result is True

    status = await app.get_job(job_id)
    assert status is None


async def test_list_jobs(app):
    """list_jobs should work on MemoryBackend."""

    @app.job(name="noop")
    async def noop():
        pass

    await app.enqueue("noop")
    await app.enqueue("noop")

    jobs = await app.list_jobs()
    assert len(jobs) == 2


async def test_list_jobs_filtered_by_status(app):
    """list_jobs with status filter should work on MemoryBackend."""

    @app.job(name="noop")
    async def noop():
        pass

    job_id = await app.enqueue("noop")
    await app.enqueue("noop")
    await app.cancel_job(job_id)

    queued = await app.list_jobs(status="queued")
    assert len(queued) == 1

    cancelled = await app.list_jobs(status="cancelled")
    assert len(cancelled) == 1


async def test_get_queue_stats(app):
    """get_queue_stats should work on MemoryBackend."""

    @app.job(name="noop")
    async def noop():
        pass

    await app.enqueue("noop")
    await app.enqueue("noop")

    stats = await app.get_queue_stats()
    assert len(stats) >= 1
    assert stats[0]["queued"] == 2


async def test_retry_job(app):
    """retry_job should work on MemoryBackend."""

    @app.job(name="failing_job", retries=1)
    async def failing_job():
        raise RuntimeError("boom")

    job_id = await app.enqueue("failing_job")

    # Process until dead_letter
    await app.run_worker(run_once=True)
    await app.run_worker(run_once=True)

    status = await app.get_job(job_id)
    assert status["status"] == "dead_letter"

    result = await app.retry_job(job_id)
    assert result is True

    status = await app.get_job(job_id)
    assert status["status"] == "queued"
