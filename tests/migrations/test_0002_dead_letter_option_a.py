"""Migration fixture test for ``0002_dead_letter_option_a.sql``.

Pins the destructive cleanup + schema-tightening behavior described in
``docs/contracts/dead_letter.md`` and ``docs/design/dlq_option_a.md``.

What this test guards:

1. The migration deletes any pre-existing ``soniq_jobs`` row with
   ``status='dead_letter'``. Operators upgrading from 0.0.2 lose those
   rows by design.
2. After the migration runs, the ``soniq_jobs.status`` CHECK no longer
   accepts ``'dead_letter'`` - both the rebuilt main constraint and the
   defensive ``soniq_jobs_status_no_dead_letter`` constraint reject the
   value.
3. The migration is idempotent. Re-running it on an already-migrated
   database is a no-op (no error, no extra constraint duplication).

These tests run against a dedicated test DB so they can apply ``0001``
in isolation, plant legacy rows, then apply ``0002`` and observe the
state transitions directly.
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

_TEST_DB = "soniq_migration_dlq_option_a_test"


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
async def test_migration_drops_legacy_dead_letter_rows(fresh_db_url):
    """Legacy soniq_jobs.status='dead_letter' rows are deleted on upgrade."""
    pool = await asyncpg.create_pool(fresh_db_url)
    try:
        async with pool.acquire() as conn:
            # Apply only 0001 so the original CHECK (which includes
            # 'dead_letter') is in force.
            await _apply_filter(conn, "0001")

            legacy_id = uuid.uuid4()
            keep_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO soniq_jobs (id, job_name, args, status, max_attempts)
                VALUES ($1, 'legacy.dlq', '{}'::jsonb, 'dead_letter', 3),
                       ($2, 'legacy.queued', '{}'::jsonb, 'queued', 3)
                """,
                legacy_id,
                keep_id,
            )

            # Apply 0002 - the migration under test.
            await _apply_filter(conn, "0002")

            remaining = await conn.fetch("SELECT id, status FROM soniq_jobs")
            ids = {row["id"] for row in remaining}
            assert legacy_id not in ids, "0002 must delete legacy dead_letter rows"
            assert keep_id in ids, "0002 must not touch non-dead_letter rows"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_migration_check_rejects_dead_letter(fresh_db_url):
    """Post-migration, INSERTing status='dead_letter' is rejected."""
    pool = await asyncpg.create_pool(fresh_db_url)
    try:
        async with pool.acquire() as conn:
            await _apply_filter(conn, "0001")
            await _apply_filter(conn, "0002")

            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO soniq_jobs (id, job_name, args, status, max_attempts)
                    VALUES ($1, 'rejected.dlq', '{}'::jsonb, 'dead_letter', 3)
                    """,
                    uuid.uuid4(),
                )
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_migration_is_idempotent(fresh_db_url):
    """Running 0002 twice is a no-op."""
    pool = await asyncpg.create_pool(fresh_db_url)
    try:
        async with pool.acquire() as conn:
            await _apply_filter(conn, "0001")
            await _apply_filter(conn, "0002")
            # Second invocation must not raise. The runner records the
            # version in soniq_migrations and skips re-application; the
            # SQL itself is also defensively idempotent (DROP CONSTRAINT
            # IF EXISTS) in case the version row is ever removed.
            await _apply_filter(conn, "0002")

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
            assert "soniq_jobs_status_check" in names
            assert "soniq_jobs_status_no_dead_letter" in names
    finally:
        await pool.close()
