import asyncio
import os

import pytest

from tests.db_utils import TEST_DATABASE_URL, clear_table, create_test_database

# Ensure test database URL is set — use setdefault so CI's SONIQ_DATABASE_URL
# (which includes a password) is not overwritten.
os.environ.setdefault("SONIQ_DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("SONIQ_JOBS_MODULES", "tests.fixtures.cli_jobs")

# Cache the URL at import time so it survives any configure(database_url=None) calls
_TEST_DATABASE_URL = os.environ["SONIQ_DATABASE_URL"]


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_test_database():
    """Set up test database once for the entire test session."""
    await create_test_database()
    yield
    # Don't drop database here to avoid issues with concurrent tests


@pytest.fixture(autouse=True)
async def clean_test_state():
    """Clean test state before each test to ensure isolation."""
    import soniq

    global_app = soniq._global_app
    if (
        global_app is not None
        and global_app._is_initialized
        and not global_app._is_closed
    ):
        await global_app.close()

    await soniq.configure(database_url=_TEST_DATABASE_URL)

    global_app = soniq._get_global_app()
    app_pool = await global_app.get_pool()
    await clear_table(app_pool)

    yield

    if global_app._is_initialized:
        await global_app.close()
