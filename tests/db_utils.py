import os
import subprocess

import asyncpg
from asyncpg.pool import Pool

from elephantq.db.migrations import run_migrations

TEST_DB_NAME = "elephantq_test"


async def create_test_database():
    db_url = f"postgresql://postgres@localhost/{TEST_DB_NAME}"
    os.environ["ELEPHANTQ_DATABASE_URL"] = db_url

    # Only create if it doesn't exist
    try:
        subprocess.run(
            ["createdb", TEST_DB_NAME], check=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        # Database already exists, that's fine
        pass

    # Drop and re-run migrations to ensure clean schema
    temp_pool = await asyncpg.create_pool(db_url)
    async with temp_pool.acquire() as conn:
        # Drop migration tracking so all migrations re-apply cleanly
        await conn.execute("DROP TABLE IF EXISTS elephantq_migrations CASCADE")
        # Drop all elephantq tables to start fresh
        await conn.execute("DROP TABLE IF EXISTS elephantq_job_dependencies CASCADE")
        await conn.execute("DROP TABLE IF EXISTS elephantq_job_timeouts CASCADE")
        await conn.execute("DROP TABLE IF EXISTS elephantq_config CASCADE")
        await conn.execute("DROP TABLE IF EXISTS elephantq_webhook_deliveries CASCADE")
        await conn.execute("DROP TABLE IF EXISTS elephantq_webhook_endpoints CASCADE")
        await conn.execute("DROP TABLE IF EXISTS elephantq_dead_letter_jobs CASCADE")
        await conn.execute("DROP TABLE IF EXISTS elephantq_logs CASCADE")
        await conn.execute("DROP TABLE IF EXISTS elephantq_recurring_jobs CASCADE")
        await conn.execute("DROP TABLE IF EXISTS elephantq_jobs CASCADE")
        await conn.execute("DROP TABLE IF EXISTS elephantq_workers CASCADE")
        await run_migrations(conn)
    await temp_pool.close()


async def drop_test_database():
    # Make dropping optional to avoid issues with concurrent tests
    try:
        subprocess.run(
            ["dropdb", "--if-exists", TEST_DB_NAME],
            check=False,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


async def clear_table(pool: Pool):
    async with pool.acquire() as conn:
        # Clear both tables with CASCADE to handle foreign key constraints
        try:
            await conn.execute(
                "TRUNCATE TABLE elephantq_jobs, elephantq_workers RESTART IDENTITY CASCADE"
            )
        except Exception:
            # Fallback to individual table clearing if the above fails
            try:
                await conn.execute("TRUNCATE TABLE elephantq_jobs RESTART IDENTITY")
            except Exception:
                pass
            try:
                await conn.execute(
                    "TRUNCATE TABLE elephantq_workers RESTART IDENTITY CASCADE"
                )
            except Exception:
                pass
