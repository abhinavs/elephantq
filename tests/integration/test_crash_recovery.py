"""
End-to-end crash recovery tests.

Proves the full cycle:
  worker marks job as 'processing' → worker goes stale →
  cleanup_stale_workers resets job to 'queued' → new worker picks up and completes it.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import soniq
from soniq.core.worker import Worker


@soniq.job(name="recoverable_job")
async def recoverable_job(marker: str):
    """A job that always succeeds."""
    pass


@pytest.mark.asyncio
async def test_stale_worker_resets_processing_jobs():
    """
    A job stuck in 'processing' with a stale worker should be reset to 'queued'.
    """
    app = soniq._get_global_app()
    pool = await app._get_pool()

    async with pool.acquire() as conn:
        # Create a stale worker (heartbeat 10 minutes ago)
        stale_worker_id = uuid.uuid4()
        stale_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=10)
        await conn.execute(
            """
            INSERT INTO soniq_workers (id, hostname, pid, concurrency, status, last_heartbeat, started_at)
            VALUES ($1, 'test-host', 99999, 1, 'active', $2, $2)
            ON CONFLICT (hostname, pid) DO UPDATE SET
                id = EXCLUDED.id, status = 'active', last_heartbeat = EXCLUDED.last_heartbeat
            """,
            stale_worker_id,
            stale_heartbeat,
        )

        # Create a job stuck in 'processing' assigned to the stale worker
        stuck_job_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO soniq_jobs (id, job_name, args, status, worker_id, max_attempts)
            VALUES ($1, 'test.stuck_job', '{}', 'processing', $2, 3)
            """,
            stuck_job_id,
            stale_worker_id,
        )

    # Run stale worker cleanup (threshold = 60 seconds, worker is 10 min old)
    cleaned = await app._backend.cleanup_stale_workers(60)
    assert cleaned >= 1

    # Verify the stuck job was reset to 'queued'
    async with pool.acquire() as conn:
        job_row = await conn.fetchrow(
            "SELECT status, worker_id FROM soniq_jobs WHERE id = $1",
            stuck_job_id,
        )
        assert job_row["status"] == "queued"
        assert job_row["worker_id"] is None

        # Verify the worker was marked as stopped
        worker_row = await conn.fetchrow(
            "SELECT status FROM soniq_workers WHERE id = $1",
            stale_worker_id,
        )
        assert worker_row["status"] == "stopped"

        # Cleanup
        await conn.execute("DELETE FROM soniq_jobs WHERE id = $1", stuck_job_id)
        await conn.execute("DELETE FROM soniq_workers WHERE id = $1", stale_worker_id)


@pytest.mark.asyncio
async def test_recovered_job_is_processed_by_new_worker():
    """
    After crash recovery resets a job to 'queued', a new worker
    should pick it up and complete it.
    """
    app = soniq._get_global_app()
    pool = await app._get_pool()
    registry = app._get_job_registry()
    backend = app._backend
    worker = Worker(backend, registry)

    # Enqueue a job, then manually set it to 'processing' with a stale worker
    job_id = await app.enqueue(
        "recoverable_job", args={"marker": "crash-recovery-test"}
    )

    async with pool.acquire() as conn:
        stale_worker_id = uuid.uuid4()
        stale_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=10)
        await conn.execute(
            """
            INSERT INTO soniq_workers (id, hostname, pid, concurrency, status, last_heartbeat, started_at)
            VALUES ($1, 'crash-test-host', 99998, 1, 'active', $2, $2)
            ON CONFLICT (hostname, pid) DO UPDATE SET
                id = EXCLUDED.id, status = 'active', last_heartbeat = EXCLUDED.last_heartbeat
            """,
            stale_worker_id,
            stale_heartbeat,
        )

        # Mark the job as stuck processing by the stale worker
        await conn.execute(
            """
            UPDATE soniq_jobs
            SET status = 'processing', worker_id = $1
            WHERE id = $2
            """,
            stale_worker_id,
            uuid.UUID(job_id),
        )

    # Run crash recovery
    await app._backend.cleanup_stale_workers(60)

    # Now a new worker should pick up and process the job
    processed = await worker.run_once(queues=None, max_jobs=1)

    assert processed is True

    # Verify job completed (either 'done' or deleted depending on result_ttl)
    async with pool.acquire() as conn:
        job_row = await conn.fetchrow(
            "SELECT status FROM soniq_jobs WHERE id = $1",
            uuid.UUID(job_id),
        )
        # Job should be done or deleted (depending on result_ttl setting)
        if job_row is not None:
            assert job_row["status"] == "done"

        # Cleanup stale worker
        await conn.execute("DELETE FROM soniq_workers WHERE id = $1", stale_worker_id)


@pytest.mark.asyncio
async def test_active_worker_jobs_not_reset():
    """
    Jobs processing by an active (recent heartbeat) worker must NOT be reset.
    """
    app = soniq._get_global_app()
    pool = await app._get_pool()

    async with pool.acquire() as conn:
        # Create an active worker (heartbeat is recent)
        active_worker_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO soniq_workers (id, hostname, pid, concurrency, status, last_heartbeat, started_at)
            VALUES ($1, 'active-test-host', 99997, 1, 'active', NOW(), NOW())
            ON CONFLICT (hostname, pid) DO UPDATE SET
                id = EXCLUDED.id, status = 'active', last_heartbeat = NOW()
            """,
            active_worker_id,
        )

        # Create a job being processed by the active worker
        active_job_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO soniq_jobs (id, job_name, args, status, worker_id, max_attempts)
            VALUES ($1, 'test.active_job', '{}', 'processing', $2, 3)
            """,
            active_job_id,
            active_worker_id,
        )

    # Run cleanup — threshold 60s, but worker heartbeat is NOW()
    await app._backend.cleanup_stale_workers(60)

    # Job should STILL be processing
    async with pool.acquire() as conn:
        job_row = await conn.fetchrow(
            "SELECT status, worker_id FROM soniq_jobs WHERE id = $1",
            active_job_id,
        )
        assert job_row["status"] == "processing"
        assert job_row["worker_id"] == active_worker_id

        # Cleanup
        await conn.execute("DELETE FROM soniq_jobs WHERE id = $1", active_job_id)
        await conn.execute("DELETE FROM soniq_workers WHERE id = $1", active_worker_id)
