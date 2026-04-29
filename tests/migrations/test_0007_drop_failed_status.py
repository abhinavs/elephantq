"""Migration fixture test for ``0007_drop_failed_status.sql``.

Pins the row reconciliation + schema-tightening behavior described in
``docs/contracts/job_lifecycle.md``.

What this test guards:

1. The migration re-queues any pre-existing ``soniq_jobs.status='failed'``
   row instead of dropping it. Operators upgrading from 0.0.2 keep the
   work; ``worker_id`` and ``scheduled_at`` are reset so a worker can
   pick the row up cleanly.
2. After the migration runs, the ``soniq_jobs.status`` CHECK rejects
   both ``'failed'`` and ``'dead_letter'``; the redundant
   ``soniq_jobs_status_no_dead_letter`` guard from ``0002`` is gone in
   favour of a single tightened constraint.
3. The migration is idempotent. Re-running it on an already-migrated
   database is a no-op (no error, no constraint duplication).
"""

import uuid

import asyncpg
import pytest

from soniq.backends.postgres.migration_runner import MigrationRunner
from tests.db_utils import (
    make_test_db_url,
    run_createdb,
    run_dropdb,
)

_TEST_DB = "soniq_migration_drop_failed_test"


@pytest.fixture
async def fresh_db_url():
    run_dropdb(_TEST_DB)
    run_createdb(_TEST_DB, check=True)
    url = make_test_db_url(_TEST_DB)
    try:
        yield url
    finally:
        run_dropdb(_TEST_DB)


async def _apply_filter(conn: asyncpg.Connection, version_filter: str) -> None:
    runner = MigrationRunner()
    await runner._run_migrations_with_connection(conn, version_filter=version_filter)


@pytest.mark.asyncio
async def test_migration_requeues_legacy_failed_rows(fresh_db_url):
    """Legacy ``status='failed'`` rows are re-queued, not deleted."""
    pool = await asyncpg.create_pool(fresh_db_url)
    try:
        async with pool.acquire() as conn:
            # 0001 + 0002 give us a CHECK that still accepts 'failed'.
            await _apply_filter(conn, "0001")
            await _apply_filter(conn, "0002")

            failed_id = uuid.uuid4()
            keep_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO soniq_jobs (id, job_name, args, status, max_attempts)
                VALUES ($1, 'legacy.failed', '{}'::jsonb, 'failed', 3),
                       ($2, 'legacy.queued', '{}'::jsonb, 'queued', 3)
                """,
                failed_id,
                keep_id,
            )

            await _apply_filter(conn, "0007")

            row = await conn.fetchrow(
                "SELECT status, worker_id FROM soniq_jobs WHERE id = $1", failed_id
            )
            assert row is not None, "0007 must not delete legacy failed rows"
            assert row["status"] == "queued"
            assert row["worker_id"] is None

            keep = await conn.fetchrow(
                "SELECT status FROM soniq_jobs WHERE id = $1", keep_id
            )
            assert keep is not None and keep["status"] == "queued"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_migration_check_rejects_failed_and_dead_letter(fresh_db_url):
    """Post-migration the rebuilt CHECK rejects both ``failed`` and
    ``dead_letter``."""
    pool = await asyncpg.create_pool(fresh_db_url)
    try:
        async with pool.acquire() as conn:
            await _apply_filter(conn, "0001")
            await _apply_filter(conn, "0002")
            await _apply_filter(conn, "0007")

            for status in ("failed", "dead_letter"):
                with pytest.raises(asyncpg.CheckViolationError):
                    await conn.execute(
                        """
                        INSERT INTO soniq_jobs
                            (id, job_name, args, status, max_attempts)
                        VALUES ($1, 'rejected.row', '{}'::jsonb, $2, 3)
                        """,
                        uuid.uuid4(),
                        status,
                    )
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_migration_drops_redundant_no_dead_letter_guard(fresh_db_url):
    """0007 retires ``soniq_jobs_status_no_dead_letter`` in favour of the
    rebuilt main CHECK. Only ``soniq_jobs_status_check`` should survive."""
    pool = await asyncpg.create_pool(fresh_db_url)
    try:
        async with pool.acquire() as conn:
            await _apply_filter(conn, "0001")
            await _apply_filter(conn, "0002")
            await _apply_filter(conn, "0007")

            constraints = await conn.fetch(
                """
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'soniq_jobs'::regclass
                  AND conname IN (
                      'soniq_jobs_status_check',
                      'soniq_jobs_status_no_dead_letter'
                  )
                """
            )
            names = {row["conname"] for row in constraints}
            assert names == {"soniq_jobs_status_check"}
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_migration_is_idempotent(fresh_db_url):
    """Running 0007 twice is a no-op."""
    pool = await asyncpg.create_pool(fresh_db_url)
    try:
        async with pool.acquire() as conn:
            await _apply_filter(conn, "0001")
            await _apply_filter(conn, "0002")
            await _apply_filter(conn, "0007")
            # Second invocation must not raise. The runner records the
            # version in soniq_migrations and skips re-application; the
            # SQL itself is defensively idempotent (DROP CONSTRAINT IF
            # EXISTS) in case the version row is ever removed.
            await _apply_filter(conn, "0007")

            constraints = await conn.fetch(
                """
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'soniq_jobs'::regclass
                  AND conname = 'soniq_jobs_status_check'
                """
            )
            assert len(constraints) == 1
    finally:
        await pool.close()
