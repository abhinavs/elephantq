"""
Regression test for the dead_letter._rows_affected infinite-recursion bug.

The original bug: `_rows_affected` in `features/dead_letter.py` called itself
instead of parsing the asyncpg status string, causing stack overflow when any
DELETE/UPDATE path in DeadLetterManager ran. The fix replaced the local
implementation with an import from `db.helpers`. Unit tests in
`tests/unit/test_rows_affected.py` pin the parser shape, but we also want an
end-to-end assertion that a full DLQ delete path completes in bounded time and
produces the expected row counts, so a future reintroduction of the recursion
would fail loudly at the feature level.
"""

import asyncio

import pytest

import soniq
from soniq.features import dead_letter
from soniq.features.dead_letter import (
    DeadLetterFilter,
    DeadLetterReason,
)
from tests.db_utils import TEST_DATABASE_URL

TIME_BOUND_SECONDS = 5.0


async def _move_sample_job_to_dlq(tag: str) -> str:
    """Enqueue a job and move it to DLQ. Returns the job id (also the DLQ id)."""

    @soniq.job(retries=0, name=f"always_fail_{tag}")
    async def always_fail():
        raise RuntimeError("boom")

    job_id = await soniq.enqueue("always_fail")
    moved = await dead_letter.move_job_to_dead_letter(
        job_id,
        DeadLetterReason.MANUAL_MOVE,
        tags={"source": tag},
    )
    assert moved is True
    return job_id


@pytest.mark.asyncio
async def test_delete_dead_letter_job_returns_in_bounded_time():
    """delete_dead_letter_job exercises _rows_affected; must complete in <5s."""
    await soniq.configure(
        database_url=TEST_DATABASE_URL, dead_letter_queue_enabled=True
    )
    global_app = soniq._get_global_app()
    await global_app._ensure_initialized()
    await dead_letter.setup_dead_letter_queue()

    job_id = await _move_sample_job_to_dlq("delete_bound")

    deleted = await asyncio.wait_for(
        dead_letter.delete_dead_letter_job(job_id),
        timeout=TIME_BOUND_SECONDS,
    )
    assert deleted is True

    pool = global_app.backend.pool
    async with pool.acquire() as conn:
        remaining = await conn.fetchval(
            "SELECT COUNT(*) FROM soniq_dead_letter_jobs WHERE id = $1",
            job_id,
        )
    assert remaining == 0


@pytest.mark.asyncio
async def test_bulk_delete_returns_exact_count_in_bounded_time():
    """bulk_delete exercises _rows_affected; must return accurate count in <5s."""
    await soniq.configure(
        database_url=TEST_DATABASE_URL, dead_letter_queue_enabled=True
    )
    global_app = soniq._get_global_app()
    await global_app._ensure_initialized()
    await dead_letter.setup_dead_letter_queue()

    ids = []
    for i in range(3):
        ids.append(await _move_sample_job_to_dlq(f"bulk_{i}"))

    criteria = DeadLetterFilter()
    criteria.tags = {"source": "bulk_0"}

    count = await asyncio.wait_for(
        dead_letter.bulk_delete_dead_letter_jobs(criteria),
        timeout=TIME_BOUND_SECONDS,
    )
    assert count == 1

    pool = global_app.backend.pool
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM soniq_dead_letter_jobs WHERE id = ANY($1)",
            ids,
        )
    assert total == 2


@pytest.mark.asyncio
async def test_move_then_single_dlq_row_exists():
    """Guard that move_to_dead_letter produces exactly one DLQ row, no more."""
    await soniq.configure(
        database_url=TEST_DATABASE_URL, dead_letter_queue_enabled=True
    )
    global_app = soniq._get_global_app()
    await global_app._ensure_initialized()
    await dead_letter.setup_dead_letter_queue()

    job_id = await asyncio.wait_for(
        _move_sample_job_to_dlq("single_row"),
        timeout=TIME_BOUND_SECONDS,
    )

    pool = global_app.backend.pool
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM soniq_dead_letter_jobs WHERE id = $1",
            job_id,
        )
        status = await conn.fetchval(
            "SELECT status FROM soniq_jobs WHERE id = $1",
            job_id,
        )
    assert count == 1
    assert status == "dead_letter"
