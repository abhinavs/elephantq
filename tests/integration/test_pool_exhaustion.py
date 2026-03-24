"""
Tests for connection pool exhaustion behavior.
"""

import asyncio

import pytest

from elephantq.client import ElephantQ
from tests.db_utils import TEST_DATABASE_URL


@pytest.mark.asyncio
async def test_pool_exhaustion_blocks_then_succeeds():
    """
    When all pool connections are in use, operations should wait for a
    connection to become available rather than crashing.
    """
    # Create an instance with a very small pool
    app = ElephantQ(
        database_url=TEST_DATABASE_URL,
        db_pool_min_size=1,
        db_pool_max_size=2,
    )
    await app._ensure_initialized()

    try:
        pool = app._pool

        # Hold both connections
        conn1 = await pool.acquire()
        conn2 = await pool.acquire()

        # Third acquire should block/timeout
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(pool.acquire(), timeout=0.5)

        # Release one connection
        await pool.release(conn2)

        # Now acquire should succeed
        conn3 = await asyncio.wait_for(pool.acquire(), timeout=2.0)
        assert conn3 is not None
        await pool.release(conn3)
        await pool.release(conn1)
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_pool_size_warning(caplog):
    """
    _warn_if_pool_too_small should log a warning when concurrency
    exceeds pool capacity.
    """
    import logging

    app = ElephantQ(
        database_url=TEST_DATABASE_URL,
        db_pool_min_size=1,
        db_pool_max_size=3,
        db_pool_safety_margin=2,
    )
    await app._ensure_initialized()

    try:
        with caplog.at_level(logging.WARNING):
            # concurrency=5 + safety_margin=2 = 7 > max_size=3
            app._warn_if_pool_too_small(concurrency=5)

        assert any(
            "pool" in r.message.lower() and "concurrency" in r.message.lower()
            for r in caplog.records
        ), "Expected warning about pool size vs concurrency"
    finally:
        await app.close()
