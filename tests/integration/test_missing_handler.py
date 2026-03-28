"""
Test that jobs with unregistered handlers are dead-lettered correctly.
"""

import uuid

import pytest

import elephantq
from elephantq.core.registry import JobRegistry
from elephantq.worker import Worker


@pytest.mark.asyncio
async def test_unregistered_job_dead_lettered():
    """
    A job with a job_name that doesn't exist in the registry
    should be moved to dead_letter with a clear error message.
    """
    app = elephantq._get_global_app()
    pool = await app.get_pool()

    # Insert a job directly with a non-existent handler
    job_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO elephantq_jobs (id, job_name, args, status, max_attempts, queue)
            VALUES ($1, 'nonexistent.module.fake_function', '{}', 'queued', 3, 'default')
            """,
            job_id,
        )

    # Process with a clean registry (no jobs registered)
    empty_registry = JobRegistry()
    backend = app._backend
    worker = Worker(backend, empty_registry)
    processed = await worker.run_once(queues=None, max_jobs=1)

    assert processed is True

    # Verify job is in dead_letter
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, last_error FROM elephantq_jobs WHERE id = $1",
            job_id,
        )

    assert row["status"] == "dead_letter"
    assert "not registered" in row["last_error"].lower()
