"""
Real-Postgres test that reconfiguring closes the prior asyncpg pool instead
of orphaning it. Repeated reconfigure used to leak a pool per call; over
time the process would run out of connections to Postgres.
"""

import pytest

import soniq
from tests.db_utils import TEST_DATABASE_URL


@pytest.mark.asyncio
async def test_configure_closes_prior_pool():
    # Configure once, trigger pool creation.
    await soniq.configure(database_url=TEST_DATABASE_URL)
    first_app = soniq._get_global_app()
    await first_app._ensure_initialized()
    first_pool = first_app._pool
    assert first_pool is not None

    # Reconfigure. The prior pool must be closed, not orphaned.
    await soniq.configure(database_url=TEST_DATABASE_URL)
    assert first_pool._closed is True, "prior pool was not awaited closed"

    # The replacement app is a fresh instance.
    second_app = soniq._get_global_app()
    assert second_app is not first_app


@pytest.mark.asyncio
async def test_repeated_configure_does_not_accumulate_pools():
    """Repeatedly reconfigure. Each call closes the prior pool before replacing."""
    seen_pools = []
    for _ in range(5):
        await soniq.configure(database_url=TEST_DATABASE_URL)
        app = soniq._get_global_app()
        await app._ensure_initialized()
        seen_pools.append(app._pool)

    # All but the last pool should be closed.
    for pool in seen_pools[:-1]:
        assert pool._closed is True
    assert seen_pools[-1]._closed is False
