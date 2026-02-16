"""
Conftest for Global API tests

These tests use the global elephantq API (elephantq.job, elephantq.enqueue, etc.)
and require proper global state management.
"""

import os

import pytest

from tests.db_utils import clear_table, create_test_database

# Ensure test database URL is set
os.environ["ELEPHANTQ_DATABASE_URL"] = "postgresql://postgres@localhost/elephantq_test"


@pytest.fixture(scope="session", autouse=True)
async def setup_test_database():
    """Set up test database once per test session."""
    # Create database once at session start
    await create_test_database()
    yield
    # Database cleanup can happen at session end if needed


@pytest.fixture(autouse=True)
async def clean_global_api_state():
    """Clean global API state before each test - FAST VERSION."""
    # Configure global ElephantQ app ONCE per session - much faster
    import elephantq

    # Clear only the job table - much faster than recreating pools
    try:
        global_app = elephantq._get_global_app()
        if global_app.is_initialized:
            app_pool = await global_app.get_pool()
            await clear_table(app_pool)
        else:
            # Initialize once if needed
            elephantq.configure(
                database_url="postgresql://postgres@localhost/elephantq_test"
            )
            global_app = elephantq._get_global_app()
            app_pool = await global_app.get_pool()
            await clear_table(app_pool)
    except Exception:
        # Fallback - just configure without clearing
        elephantq.configure(database_url="postgresql://postgres@localhost/elephantq_test")

    yield

    # Minimal cleanup - just clear table, no connection cleanup
    try:
        if "app_pool" in locals():
            await clear_table(app_pool)
    except:
        pass


@pytest.fixture
async def clean_db():
    """Additional fixture for tests that need explicit clean database state."""
    import elephantq

    global_app = elephantq._get_global_app()
    app_pool = await global_app.get_pool()
    await clear_table(app_pool)
    return None
