"""
Metrics analytics align to real lifecycle tables.

The DLQ contract (Option A) puts dead-lettered jobs in
``soniq_dead_letter_jobs``; ``soniq_jobs.status`` does not contain
``'dead_letter'``. ``MetricsAnalyzer._get_queue_stats`` must therefore
read DLQ counts from ``soniq_dead_letter_jobs``, not from a status
filter that can never match.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

from soniq import Soniq
from soniq.features.metrics import MetricsService
from tests.db_utils import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not os.environ.get("SONIQ_DATABASE_URL") and not TEST_DATABASE_URL,
    reason="Postgres test DB not configured",
)


@pytest.fixture
async def app():
    a = Soniq(database_url=TEST_DATABASE_URL)
    await a.ensure_initialized()
    pool = await a._get_pool()
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE soniq_jobs, soniq_dead_letter_jobs CASCADE")
    yield a
    await a.close()


async def _seed_dlq_row(app: Soniq, queue: str = "default") -> str:
    job_id = str(uuid.uuid4())
    pool = await app._get_pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO soniq_dead_letter_jobs
                (id, job_name, args, queue, priority, max_attempts, attempts,
                 last_error, dead_letter_reason, original_created_at,
                 moved_to_dead_letter_at)
            VALUES ($1, $2, $3::jsonb, $4, 100, 3, 3, 'boom', 'max_retries', $5, $5)
            """,
            uuid.UUID(job_id),
            "test.metric.dlq",
            "{}",
            queue,
            now,
        )
    return job_id


@pytest.mark.asyncio
async def test_metrics_queue_stats_dead_letter_count_reads_dlq_table(app):
    """MetricsAnalyzer's per-queue rollup must include DLQ counts from
    soniq_dead_letter_jobs."""
    await _seed_dlq_row(app, queue="default")
    await _seed_dlq_row(app, queue="default")

    metrics_service = MetricsService(app)
    pool = await app._get_pool()
    async with pool.acquire() as conn:
        queue_stats = await metrics_service.analyzer._get_queue_stats(conn, "1")

    default_stats = next(
        (q for q in queue_stats if q.queue_name == "default"),
        None,
    )
    assert default_stats is not None, (
        "Expected per-queue stats for 'default' but got none. The metrics "
        "queue rollup is not picking up DLQ-only queues."
    )
    assert default_stats.dead_letter_count == 2, (
        f"Expected dead_letter_count=2 from DLQ table seeding, got "
        f"{default_stats.dead_letter_count}. Metrics is querying the wrong table."
    )
