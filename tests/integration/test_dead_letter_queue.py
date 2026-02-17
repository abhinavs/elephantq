import pytest

import elephantq
from elephantq.features import dead_letter
from elephantq.features.dead_letter import DeadLetterReason
from elephantq.db.context import get_context_pool


@pytest.mark.asyncio
async def test_dead_letter_move_creates_record():
    elephantq.configure(dead_letter_queue_enabled=True)
    await dead_letter.setup_dead_letter_queue()

    @elephantq.job(retries=0)
    async def always_fail():
        raise RuntimeError("boom")

    job_id = await elephantq.enqueue(always_fail)

    moved = await dead_letter.move_job_to_dead_letter(
        job_id,
        DeadLetterReason.MANUAL_MOVE,
        tags={"source": "test"},
    )
    assert moved is True

    pool = await get_context_pool()
    async with pool.acquire() as conn:
        job_row = await conn.fetchrow(
            "SELECT status FROM elephantq_jobs WHERE id = $1", job_id
        )
        assert job_row is not None
        assert job_row["status"] == "dead_letter"

        dead_row = await conn.fetchrow(
            "SELECT dead_letter_reason, tags FROM elephantq_dead_letter_jobs WHERE id = $1",
            job_id,
        )
        assert dead_row is not None
        assert dead_row["dead_letter_reason"] == DeadLetterReason.MANUAL_MOVE.value
        tags = dead_row["tags"]
        if isinstance(tags, str):
            import json

            tags = json.loads(tags)
        assert tags["source"] == "test"
