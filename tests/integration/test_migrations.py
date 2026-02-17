import subprocess
import asyncpg
import pytest

from elephantq.db.migration_runner import MigrationRunner


MIGRATIONS_DB = "elephantq_migrations_test"


@pytest.mark.asyncio
async def test_migrations_apply_and_idempotent():
    subprocess.run(["dropdb", "--if-exists", MIGRATIONS_DB], check=False, stderr=subprocess.DEVNULL)
    subprocess.run(["createdb", MIGRATIONS_DB], check=True)

    db_url = f"postgresql://postgres@localhost/{MIGRATIONS_DB}"

    try:
        pool = await asyncpg.create_pool(db_url)
        async with pool.acquire() as conn:
            runner = MigrationRunner()
            applied = await runner.run_migrations(conn)
            assert applied > 0

            applied_again = await runner.run_migrations(conn)
            assert applied_again == 0

            tables = await conn.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
            table_names = {row["table_name"] for row in tables}
            assert "elephantq_jobs" in table_names
            assert "elephantq_migrations" in table_names
        await pool.close()
    finally:
        subprocess.run(["dropdb", "--if-exists", MIGRATIONS_DB], check=False, stderr=subprocess.DEVNULL)
