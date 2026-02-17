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
