"""
A user who creates `app = Soniq(database_url=...)` and then calls the
feature APIs (`every(...).schedule(...)`, `schedule_job(...)`, global
`soniq.enqueue` from within `app.enqueue`, and so on) must have those
features target *their* database, not the global app's. Prior to this PR
the features always reached for `get_global_app()`, silently crossing the
database boundary. We assert that isolation holds for the `enqueue` path on
real Postgres against two databases.
"""

import os
import subprocess
import uuid
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest

import soniq
from soniq import Soniq
from soniq.backends.postgres.migration_runner import run_migrations
from tests.db_utils import TEST_DATABASE_URL

DB_A = "soniq_pr4_db_a"
DB_B = "soniq_pr4_db_b"


def _make_url(db_name: str) -> str:
    parsed = urlparse(TEST_DATABASE_URL)
    return urlunparse(parsed._replace(path=f"/{db_name}"))


async def _create_db(name: str) -> str:
    parsed = urlparse(TEST_DATABASE_URL)
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    args = ["createdb"]
    if parsed.username:
        args += ["-U", parsed.username]
    if parsed.hostname:
        args += ["-h", parsed.hostname]
    if parsed.port:
        args += ["-p", str(parsed.port)]
    args += [name]
    subprocess.run(args, env=env, check=False, stderr=subprocess.DEVNULL)

    url = _make_url(name)
    pool = await asyncpg.create_pool(url)
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS soniq_jobs CASCADE")
        await conn.execute("DROP TABLE IF EXISTS soniq_workers CASCADE")
        await conn.execute("DROP TABLE IF EXISTS soniq_migrations CASCADE")
        await run_migrations(conn)
    await pool.close()
    return url


@pytest.fixture
async def two_dbs():
    url_a = await _create_db(DB_A)
    url_b = await _create_db(DB_B)
    yield url_a, url_b


@pytest.mark.asyncio
async def test_instance_enqueue_targets_instance_db_not_global(two_dbs):
    """app_a.enqueue writes to DB_A even when a different global app points elsewhere."""
    url_a, url_b = two_dbs

    # Arrange: configure the global app to point at DB_B.
    await soniq.configure(database_url=url_b)

    app_a = Soniq(database_url=url_a)

    async def payload_job():
        return None

    # Register on app_a; also register on the global (independent registry).
    app_a.job()(payload_job)

    # Act: enqueue via the instance. This should land in DB_A.
    job_id = await app_a.enqueue(payload_job)

    # Assert: row present in DB_A, absent in DB_B.
    pool_a = await asyncpg.create_pool(url_a)
    pool_b = await asyncpg.create_pool(url_b)
    try:
        async with pool_a.acquire() as conn_a:
            row_a = await conn_a.fetchrow(
                "SELECT id FROM soniq_jobs WHERE id = $1", uuid.UUID(job_id)
            )
        async with pool_b.acquire() as conn_b:
            row_b = await conn_b.fetchrow(
                "SELECT id FROM soniq_jobs WHERE id = $1", uuid.UUID(job_id)
            )
    finally:
        await pool_a.close()
        await pool_b.close()
        await app_a.close()

    assert row_a is not None, "instance enqueue should write to the instance's DB"
    assert row_b is None, "instance enqueue must not leak to the global DB"


@pytest.mark.asyncio
async def test_global_enqueue_still_targets_global_db(two_dbs):
    """With no active instance, soniq.enqueue continues to use the global app."""
    url_a, url_b = two_dbs

    await soniq.configure(database_url=url_b)

    async def global_job():
        return None

    soniq.job()(global_job)

    # Enqueue by callable so the derived `module.qualname` name matches the
    # registration. Enqueueing the bare string `"global_job"` would not
    # match the registered name (which includes the module prefix and the
    # `<locals>` qualname) and trips strict validation.
    job_id = await soniq.enqueue(global_job)

    pool_a = await asyncpg.create_pool(url_a)
    pool_b = await asyncpg.create_pool(url_b)
    try:
        async with pool_a.acquire() as conn_a:
            row_a = await conn_a.fetchrow(
                "SELECT id FROM soniq_jobs WHERE id = $1", uuid.UUID(job_id)
            )
        async with pool_b.acquire() as conn_b:
            row_b = await conn_b.fetchrow(
                "SELECT id FROM soniq_jobs WHERE id = $1", uuid.UUID(job_id)
            )
    finally:
        await pool_a.close()
        await pool_b.close()

    assert row_b is not None, "global enqueue should write to the global DB"
    assert row_a is None, "global enqueue must not leak into the unused DB"
