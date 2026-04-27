"""
Conftest for Instance API tests

These tests use the instance-based Soniq API (app = Soniq(), app.job, etc.)
and create their own isolated Soniq instances.
"""

import os

import pytest

from tests.db_utils import TEST_DATABASE_URL, clear_table, create_test_database

# Ensure test database URL is set
os.environ["SONIQ_DATABASE_URL"] = TEST_DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
async def setup_instance_test_database():
    """Set up test database once per test session."""
    await create_test_database()
    yield


@pytest.fixture(autouse=True)
async def clean_instance_api_state():
    """Close the global app between instance-API tests so a stale pool from a
    previous test does not leak."""
    import soniq

    global_app = soniq._global_app
    if (
        global_app is not None
        and global_app.is_initialized
        and not global_app.is_closed
    ):
        await global_app.close()

    yield

    global_app = soniq._global_app
    if (
        global_app is not None
        and global_app.is_initialized
        and not global_app.is_closed
    ):
        await global_app.close()


@pytest.fixture
async def clean_db():
    """Additional fixture for tests that need explicit clean database state - FAST VERSION."""
    # Just clear tables instead of recreating database
    from soniq.app import Soniq

    app = Soniq(database_url=TEST_DATABASE_URL)
    pool = await app._get_pool()
    await clear_table(pool)
    await app.close()
    return None
