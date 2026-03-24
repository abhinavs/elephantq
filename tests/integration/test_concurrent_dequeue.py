"""
Concurrent dequeue tests.

Proves FOR UPDATE SKIP LOCKED prevents duplicate job processing
under actual contention from multiple async tasks.
"""

import asyncio

import pytest

import elephantq
from elephantq.core.processor import _fetch_and_lock_job


@elephantq.job(queue="race-test")
async def race_job(n: int):
    pass


@elephantq.job(queue="race-test", unique=True)
async def unique_race_job(key: str):
    pass


@pytest.mark.asyncio
async def test_concurrent_dequeue_no_duplicates():
    """
    Multiple async tasks racing to dequeue a single job:
    exactly one should succeed, the rest should get None.
    """
    app = elephantq._get_global_app()
    pool = await app.get_pool()

    # Enqueue exactly 1 job
    await app.enqueue(race_job, n=1)

    # Launch 5 concurrent dequeue attempts
    async def try_dequeue():
        async with pool.acquire() as conn:
            return await _fetch_and_lock_job(conn, "race-test")

    results = await asyncio.gather(*[try_dequeue() for _ in range(5)])

    # Exactly 1 should have gotten the job
    got_job = [r for r in results if r is not None]
    got_none = [r for r in results if r is None]

    assert len(got_job) == 1, f"Expected exactly 1 winner, got {len(got_job)}"
    assert len(got_none) == 4, f"Expected 4 losers, got {len(got_none)}"


@pytest.mark.asyncio
async def test_concurrent_dequeue_distributes_jobs():
    """
    10 jobs, 5 concurrent workers: all 10 should be claimed with zero duplicates.
    """
    app = elephantq._get_global_app()
    pool = await app.get_pool()

    # Enqueue 10 jobs
    for i in range(10):
        await app.enqueue(race_job, n=i)

    # 5 concurrent workers, each dequeuing until None
    claimed_ids = []
    lock = asyncio.Lock()

    async def worker_loop():
        while True:
            async with pool.acquire() as conn:
                job = await _fetch_and_lock_job(conn, "race-test")
            if job is None:
                break
            async with lock:
                claimed_ids.append(job["id"])

    await asyncio.gather(*[worker_loop() for _ in range(5)])

    assert len(claimed_ids) == 10, f"Expected 10 jobs claimed, got {len(claimed_ids)}"
    assert len(set(claimed_ids)) == 10, "Duplicate job IDs found — race condition!"


@pytest.mark.asyncio
async def test_unique_job_concurrent_enqueue():
    """
    10 concurrent enqueue calls with unique=True and same args:
    only 1 job should exist in the database.
    """
    app = elephantq._get_global_app()
    pool = await app.get_pool()

    # Launch 10 concurrent enqueues with same args
    async def try_enqueue():
        return await app.enqueue(unique_race_job, key="same-key")

    results = await asyncio.gather(*[try_enqueue() for _ in range(10)])

    # All should return the same job ID
    unique_ids = set(results)
    assert (
        len(unique_ids) == 1
    ), f"Expected all enqueues to return the same ID, got {len(unique_ids)} distinct IDs"

    # Verify only 1 job row exists
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM elephantq_jobs
            WHERE job_name LIKE '%unique_race_job%' AND status = 'queued'
            """
        )
    assert count == 1, f"Expected 1 unique job row, found {count}"
