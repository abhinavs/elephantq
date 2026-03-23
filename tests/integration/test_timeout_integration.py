"""
Integration tests for job timeout enforcement through the full processing pipeline.
"""

import asyncio

import pytest

import elephantq
from elephantq.core.processor import process_jobs_with_registry


@elephantq.job(retries=1, timeout=0.1)
async def slow_timeout_job():
    """Job that always exceeds its per-job timeout."""
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_timed_out_job_retried_then_dead_lettered():
    """
    A job that always times out should be retried up to max_attempts
    and then moved to dead_letter.
    """
    app = elephantq._get_global_app()
    pool = await app.get_pool()
    registry = app.get_job_registry()

    job_id = await app.enqueue(slow_timeout_job)

    # First processing: job times out → failure (attempt 1)
    async with pool.acquire() as conn:
        processed = await process_jobs_with_registry(
            conn=conn,
            job_registry=registry,
            queue=None,
            heartbeat=None,
        )
    assert processed is True

    # Check: job should be back in 'queued' (retries=1 means max_attempts=2)
    status = await app.get_job_status(job_id)
    assert status["status"] == "queued"
    assert status["attempts"] == 1
    assert "timed out" in status["last_error"].lower()

    # Second processing: job times out again → dead_letter (attempt 2 of 2)
    async with pool.acquire() as conn:
        processed = await process_jobs_with_registry(
            conn=conn,
            job_registry=registry,
            queue=None,
            heartbeat=None,
        )
    assert processed is True

    # Check: job should now be in dead_letter
    status = await app.get_job_status(job_id)
    assert status["status"] == "dead_letter"
    assert status["attempts"] == 2
