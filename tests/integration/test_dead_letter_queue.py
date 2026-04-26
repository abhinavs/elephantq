import pytest

import soniq
from soniq.features import dead_letter
from soniq.features.dead_letter import DeadLetterReason
from tests.db_utils import TEST_DATABASE_URL


@pytest.mark.asyncio
async def test_dead_letter_move_creates_record():
    await soniq.configure(database_url=TEST_DATABASE_URL)

    global_app = soniq._get_global_app()
    await global_app._ensure_initialized()

    await dead_letter.setup_dead_letter_queue()

    @soniq.job(name="always_fail", retries=0)
    async def always_fail():
        raise RuntimeError("boom")

    job_id = await soniq.enqueue("always_fail")

    moved = await dead_letter.move_job_to_dead_letter(
        job_id,
        DeadLetterReason.MANUAL_MOVE,
        tags={"source": "test"},
    )
    assert moved is True

    async with global_app.backend._pool.acquire() as conn:
        job_row = await conn.fetchrow(
            "SELECT status FROM soniq_jobs WHERE id = $1", job_id
        )
        assert job_row is not None
        assert job_row["status"] == "dead_letter"

        dead_row = await conn.fetchrow(
            "SELECT dead_letter_reason, tags FROM soniq_dead_letter_jobs WHERE id = $1",
            job_id,
        )
        assert dead_row is not None
        assert dead_row["dead_letter_reason"] == DeadLetterReason.MANUAL_MOVE.value
        tags = dead_row["tags"]
        if isinstance(tags, str):
            import json

            tags = json.loads(tags)
        assert tags["source"] == "test"
