"""
Integration tests for PostgresBackend against a real PostgreSQL database.
"""

import uuid

import pytest

from soniq.backends.postgres import PostgresBackend
from tests.db_utils import TEST_DATABASE_URL


@pytest.fixture
async def backend():
    b = PostgresBackend(database_url=TEST_DATABASE_URL)
    await b.initialize()
    yield b
    await b.reset()
    await b.close()


@pytest.mark.asyncio
async def test_create_and_get_job(backend):
    job_id = str(uuid.uuid4())
    result = await backend.create_job(
        job_id=job_id,
        job_name="test.my_job",
        args={"x": 1},
        args_hash=None,
        max_attempts=3,
        priority=100,
        queue="default",
        unique=False,
        dedup_key=None,
        scheduled_at=None,
    )
    assert result == job_id

    job = await backend.get_job(job_id)
    assert job is not None
    assert job["id"] == job_id
    assert job["status"] == "queued"
    assert job["args"] == {"x": 1}


@pytest.mark.asyncio
async def test_fetch_and_lock_job(backend):
    job_id = str(uuid.uuid4())
    await backend.create_job(
        job_id=job_id,
        job_name="test.fetch_job",
        args={},
        args_hash=None,
        max_attempts=3,
        priority=100,
        queue="default",
        unique=False,
        dedup_key=None,
        scheduled_at=None,
    )

    locked = await backend.fetch_and_lock_job(queues=["default"], worker_id=None)
    assert locked is not None
    assert str(locked["id"]) == job_id

    # Job should now be processing
    job = await backend.get_job(job_id)
    assert job["status"] == "processing"

    # No more jobs to fetch
    empty = await backend.fetch_and_lock_job(queues=["default"], worker_id=None)
    assert empty is None


@pytest.mark.asyncio
async def test_mark_job_done(backend):
    job_id = str(uuid.uuid4())
    await backend.create_job(
        job_id=job_id,
        job_name="test.done_job",
        args={},
        args_hash=None,
        max_attempts=3,
        priority=100,
        queue="default",
        unique=False,
        dedup_key=None,
        scheduled_at=None,
    )
    await backend.fetch_and_lock_job(queues=["default"], worker_id=None)
    await backend.mark_job_done(job_id, result_ttl=3600)

    job = await backend.get_job(job_id)
    assert job["status"] == "done"


@pytest.mark.asyncio
async def test_mark_job_failed_and_retry(backend):
    job_id = str(uuid.uuid4())
    await backend.create_job(
        job_id=job_id,
        job_name="test.fail_job",
        args={},
        args_hash=None,
        max_attempts=3,
        priority=100,
        queue="default",
        unique=False,
        dedup_key=None,
        scheduled_at=None,
    )
    await backend.fetch_and_lock_job(queues=["default"], worker_id=None)
    await backend.mark_job_failed(job_id, attempts=1, error="boom")

    job = await backend.get_job(job_id)
    assert job["status"] == "queued"
    assert job["last_error"] == "boom"


@pytest.mark.asyncio
async def test_mark_job_dead_letter(backend):
    job_id = str(uuid.uuid4())
    await backend.create_job(
        job_id=job_id,
        job_name="test.dead_job",
        args={},
        args_hash=None,
        max_attempts=3,
        priority=100,
        queue="default",
        unique=False,
        dedup_key=None,
        scheduled_at=None,
    )
    await backend.fetch_and_lock_job(queues=["default"], worker_id=None)
    await backend.mark_job_dead_letter(
        job_id,
        attempts=3,
        error="gave up",
        reason="max_retries_exceeded",
    )

    # DLQ Option A: the row leaves soniq_jobs entirely.
    assert await backend.get_job(job_id) is None
    async with backend.acquire() as conn:
        dlq_row = await conn.fetchrow(
            "SELECT * FROM soniq_dead_letter_jobs WHERE id = $1",
            uuid.UUID(job_id),
        )
    assert dlq_row is not None
    assert dlq_row["dead_letter_reason"] == "max_retries_exceeded"
    assert dlq_row["last_error"] == "gave up"


@pytest.mark.asyncio
async def test_cancel_job(backend):
    job_id = str(uuid.uuid4())
    await backend.create_job(
        job_id=job_id,
        job_name="test.cancel_job",
        args={},
        args_hash=None,
        max_attempts=3,
        priority=100,
        queue="default",
        unique=False,
        dedup_key=None,
        scheduled_at=None,
    )

    result = await backend.cancel_job(job_id)
    assert result is True

    job = await backend.get_job(job_id)
    assert job["status"] == "cancelled"


@pytest.mark.asyncio
async def test_list_jobs_with_filters(backend):
    for i in range(3):
        await backend.create_job(
            job_id=str(uuid.uuid4()),
            job_name=f"test.list_job_{i}",
            args={},
            args_hash=None,
            max_attempts=3,
            priority=100,
            queue="q1" if i < 2 else "q2",
            unique=False,
            dedup_key=None,
            scheduled_at=None,
        )

    all_jobs = await backend.list_jobs()
    assert len(all_jobs) == 3

    q1_jobs = await backend.list_jobs(queue="q1")
    assert len(q1_jobs) == 2

    limited = await backend.list_jobs(limit=1)
    assert len(limited) == 1


@pytest.mark.asyncio
async def test_queue_stats(backend):
    await backend.create_job(
        job_id=str(uuid.uuid4()),
        job_name="test.stats_job",
        args={},
        args_hash=None,
        max_attempts=3,
        priority=100,
        queue="default",
        unique=False,
        dedup_key=None,
        scheduled_at=None,
    )

    stats = await backend.get_queue_stats()
    assert set(stats.keys()) == {
        "total",
        "queued",
        "processing",
        "done",
        "dead_letter",
        "cancelled",
    }
    assert stats["queued"] >= 1
    assert stats["total"] >= 1


@pytest.mark.asyncio
async def test_reset_clears_everything(backend):
    await backend.create_job(
        job_id=str(uuid.uuid4()),
        job_name="test.reset_job",
        args={},
        args_hash=None,
        max_attempts=3,
        priority=100,
        queue="default",
        unique=False,
        dedup_key=None,
        scheduled_at=None,
    )

    await backend.reset()

    jobs = await backend.list_jobs()
    assert len(jobs) == 0
