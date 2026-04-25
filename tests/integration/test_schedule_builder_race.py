"""
Race test for JobScheduleBuilder.enqueue() with a shared dedup_key.

Concurrent callers racing on the same dedup_key must all observe a single
job row. The documented contract (see tests/integration/test_queueing_lock.py)
is that duplicate enqueues return the ID of the existing queued job rather
than raising. This test asserts that contract under asyncio concurrency and
also checks the non-deduped baseline so we cannot be falsely green.

Concurrency is deliberately kept well under the default `pool_max_size`
(20). CI Postgres `max_connections` can be lower than local, and earlier
tests in the suite may still hold connections; piling a big race on top
runs into "too many clients already" or pool-acquire stalls. Ten racers
are plenty to exercise the dedup path - the unique partial index enforces
the contract at the DB level, so scale is not what we're testing here.
A wait_for wrapper caps each test so a regression never hangs CI.
"""

import asyncio
import uuid

import pytest

import soniq
from soniq.features.scheduling import JobScheduleBuilder

CONCURRENCY = 10
TEST_TIMEOUT_SECONDS = 30


@soniq.job(retries=0, name="race_builder_job")
async def race_builder_job():
    return "ok"


async def _ready_app():
    """Use the global app already configured by the integration conftest.

    Calling `await soniq.configure()` here would orphan the conftest's pool
    and potentially exhaust Postgres max_connections.
    """
    global_app = soniq._get_global_app()
    await global_app._ensure_initialized()
    return global_app


@pytest.mark.asyncio
async def test_concurrent_enqueue_with_same_dedup_key_produces_one_row():
    app = await _ready_app()
    dedup = f"race:{uuid.uuid4()}"

    async def one_enqueue() -> str:
        builder = JobScheduleBuilder(race_builder_job)
        return await builder.enqueue(dedup_key=dedup)

    results = await asyncio.wait_for(
        asyncio.gather(*(one_enqueue() for _ in range(CONCURRENCY))),
        timeout=TEST_TIMEOUT_SECONDS,
    )

    assert len(results) == CONCURRENCY
    assert all(isinstance(jid, str) for jid in results)

    async with app.backend.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id FROM soniq_jobs WHERE dedup_key = $1",
            dedup,
        )
    assert len(rows) == 1, f"expected 1 row for dedup_key, got {len(rows)}"

    winner_id = str(rows[0]["id"])
    assert all(
        jid == winner_id for jid in results
    ), "all concurrent callers should receive the winning job id"


@pytest.mark.asyncio
async def test_concurrent_enqueue_with_unique_dedup_keys_produces_n_rows():
    """Baseline: N unique dedup keys should create N distinct rows."""
    app = await _ready_app()
    prefix = f"race-unique-{uuid.uuid4()}"

    async def one_enqueue(i: int) -> str:
        builder = JobScheduleBuilder(race_builder_job)
        return await builder.enqueue(dedup_key=f"{prefix}:{i}")

    results = await asyncio.wait_for(
        asyncio.gather(*(one_enqueue(i) for i in range(CONCURRENCY))),
        timeout=TEST_TIMEOUT_SECONDS,
    )

    assert len(set(results)) == CONCURRENCY

    async with app.backend.pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM soniq_jobs WHERE dedup_key LIKE $1",
            f"{prefix}:%",
        )
    assert count == CONCURRENCY
