import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_concurrent_get_pool_calls_create_pool_once():
    """
    Verify that 10 concurrent get_pool() calls result in create_pool being
    called exactly once, even when pool creation is slow.
    """
    import elephantq.db.connection as conn_mod

    # Reset global pool state so get_pool() needs to create a new one
    original_pool = conn_mod._pool
    conn_mod._pool = None
    conn_mod._pool_lock = asyncio.Lock()

    fake_pool = AsyncMock()
    call_count = 0

    async def slow_create_pool(url, init=None):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)  # simulate slow pool creation
        return fake_pool

    try:
        with patch.object(
            conn_mod.asyncpg, "create_pool", side_effect=slow_create_pool
        ):
            # Fire 10 concurrent get_pool() calls
            results = await asyncio.gather(*[conn_mod.get_pool() for _ in range(10)])

        # All calls should return the same pool
        assert all(r is fake_pool for r in results)
        # create_pool should have been called exactly once
        assert call_count == 1, f"Expected 1 call to create_pool, got {call_count}"
    finally:
        # Restore original state
        conn_mod._pool = original_pool
