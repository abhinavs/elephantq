import pytest

import soniq


@pytest.mark.asyncio
async def test_transactional_enqueue_rolls_back():
    @soniq.job(name="txn_job")
    async def txn_job():
        return "ok"

    pool = await soniq._get_global_app().get_pool()
    async with pool.acquire() as conn:
        job_id = None
        try:
            async with conn.transaction():
                job_id = await soniq.enqueue("txn_job", connection=conn)
                raise RuntimeError("rollback")
        except RuntimeError:
            pass

        row = await conn.fetchrow("SELECT id FROM soniq_jobs WHERE id = $1", job_id)
        assert row is None


@pytest.mark.asyncio
async def test_transactional_enqueue_commits():
    @soniq.job(name="txn_job_commit")
    async def txn_job_commit():
        return "ok"

    pool = await soniq._get_global_app().get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            job_id = await soniq.enqueue("txn_job_commit", connection=conn)

        row = await conn.fetchrow("SELECT id FROM soniq_jobs WHERE id = $1", job_id)
        assert row is not None


@pytest.mark.asyncio
async def test_transactional_schedule_rolls_back():
    @soniq.job(name="txn_scheduled_job")
    async def txn_scheduled_job():
        return "scheduled"

    pool = await soniq._get_global_app().get_pool()
    async with pool.acquire() as conn:
        job_id = None
        try:
            async with conn.transaction():
                job_id = await soniq.schedule(
                    "txn_scheduled_job", run_in=60, connection=conn
                )
                raise RuntimeError("rollback")
        except RuntimeError:
            pass

        row = await conn.fetchrow("SELECT id FROM soniq_jobs WHERE id = $1", job_id)
        assert row is None


@pytest.mark.asyncio
async def test_non_transactional_enqueue_commits_immediately():
    @soniq.job(name="non_txn_job")
    async def non_txn_job():
        return "ok"

    job_id = await soniq.enqueue("non_txn_job")

    pool = await soniq._get_global_app().get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM soniq_jobs WHERE id = $1", job_id)
        assert row is not None


@pytest.mark.asyncio
async def test_unique_enqueue_rollback_does_not_block_next_enqueue():
    import uuid

    @soniq.job(name="unique_job", unique=True)
    async def unique_job(payload: str):
        return payload

    unique_payload = str(uuid.uuid4())

    pool = await soniq._get_global_app().get_pool()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                await soniq.enqueue(
                    "unique_job", args={"payload": unique_payload}, connection=conn
                )
                raise RuntimeError("rollback")
        except RuntimeError:
            pass

    job_id = await soniq.enqueue("unique_job", args={"payload": unique_payload})
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM soniq_jobs WHERE id = $1", job_id)
        assert row is not None
