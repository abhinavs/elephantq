import pytest

import elephantq
from elephantq.db.connection import get_pool


@pytest.mark.asyncio
async def test_transactional_enqueue_rolls_back():
    @elephantq.job()
    async def txn_job():
        return "ok"

    pool = await get_pool()
    async with pool.acquire() as conn:
        job_id = None
        try:
            async with conn.transaction():
                job_id = await elephantq.enqueue(txn_job, connection=conn)
                raise RuntimeError("rollback")
        except RuntimeError:
            pass

        row = await conn.fetchrow(
            "SELECT id FROM elephantq_jobs WHERE id = $1", job_id
        )
        assert row is None


@pytest.mark.asyncio
async def test_transactional_enqueue_commits():
    @elephantq.job()
    async def txn_job_commit():
        return "ok"

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            job_id = await elephantq.enqueue(txn_job_commit, connection=conn)

        row = await conn.fetchrow(
            "SELECT id FROM elephantq_jobs WHERE id = $1", job_id
        )
        assert row is not None


@pytest.mark.asyncio
async def test_transactional_schedule_rolls_back():
    @elephantq.job()
    async def txn_scheduled_job():
        return "scheduled"

    pool = await get_pool()
    async with pool.acquire() as conn:
        job_id = None
        try:
            async with conn.transaction():
                job_id = await elephantq.schedule(
                    txn_scheduled_job, run_in=60, connection=conn
                )
                raise RuntimeError("rollback")
        except RuntimeError:
            pass

        row = await conn.fetchrow(
            "SELECT id FROM elephantq_jobs WHERE id = $1", job_id
        )
        assert row is None


@pytest.mark.asyncio
async def test_non_transactional_enqueue_commits_immediately():
    @elephantq.job()
    async def non_txn_job():
        return "ok"

    job_id = await elephantq.enqueue(non_txn_job)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM elephantq_jobs WHERE id = $1", job_id
        )
        assert row is not None


@pytest.mark.asyncio
async def test_unique_enqueue_rollback_does_not_block_next_enqueue():
    import uuid

    @elephantq.job(unique=True)
    async def unique_job(payload: str):
        return payload

    unique_payload = str(uuid.uuid4())

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                await elephantq.enqueue(
                    unique_job, payload=unique_payload, connection=conn
                )
                raise RuntimeError("rollback")
        except RuntimeError:
            pass

    job_id = await elephantq.enqueue(unique_job, payload=unique_payload)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM elephantq_jobs WHERE id = $1", job_id
        )
        assert row is not None
