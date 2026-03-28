"""
Tests for heartbeat.py.

Since heartbeat functions require asyncpg.Pool (PostgreSQL-specific),
we test with mocks that simulate the async context manager pattern.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest


def _make_pool_mock(conn_mock):
    """Create a mock pool whose acquire() works as an async context manager."""

    @asynccontextmanager
    async def acquire():
        yield conn_mock

    pool = AsyncMock()
    pool.acquire = acquire
    return pool


@pytest.mark.asyncio
async def test_cleanup_stale_workers_with_no_stale():
    from elephantq.core.heartbeat import cleanup_stale_workers

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool_mock(conn)

    result = await cleanup_stale_workers(pool, stale_threshold_seconds=300)
    assert result == 0


@pytest.mark.asyncio
async def test_cleanup_stale_workers_with_stale():
    from elephantq.core.heartbeat import cleanup_stale_workers

    stale_rows = [{"id": "worker-1"}, {"id": "worker-2"}]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=stale_rows)
    conn.execute = AsyncMock()
    pool = _make_pool_mock(conn)

    result = await cleanup_stale_workers(pool, stale_threshold_seconds=300)
    assert result == 2
    conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_uses_settings_default_threshold():
    from elephantq.core.heartbeat import cleanup_stale_workers

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_pool_mock(conn)

    with patch("elephantq.settings.get_settings") as mock_settings:
        mock_settings.return_value.heartbeat_timeout = 600
        result = await cleanup_stale_workers(pool, stale_threshold_seconds=None)

    assert result == 0
    call_args = conn.fetch.call_args
    assert "600" in str(call_args)


@pytest.mark.asyncio
async def test_cleanup_handles_interface_error_pool_closing():
    import asyncpg

    from elephantq.core.heartbeat import cleanup_stale_workers

    @asynccontextmanager
    async def failing_acquire():
        raise asyncpg.exceptions.InterfaceError("pool is closing")
        yield  # pragma: no cover

    pool = AsyncMock()
    pool.acquire = failing_acquire

    result = await cleanup_stale_workers(pool, stale_threshold_seconds=300)
    assert result == 0


@pytest.mark.asyncio
async def test_cleanup_handles_generic_exception():
    from elephantq.core.heartbeat import cleanup_stale_workers

    @asynccontextmanager
    async def failing_acquire():
        raise RuntimeError("db gone")
        yield  # pragma: no cover

    pool = AsyncMock()
    pool.acquire = failing_acquire

    result = await cleanup_stale_workers(pool, stale_threshold_seconds=300)
    assert result == 0


@pytest.mark.asyncio
async def test_get_worker_status_returns_structure():
    from elephantq.core.heartbeat import get_worker_status

    now = datetime.now(timezone.utc)
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [{"status": "active", "count": 1}],
            [
                {
                    "id": "worker-1",
                    "hostname": "host1",
                    "pid": 1234,
                    "queues": ["default"],
                    "concurrency": 4,
                    "last_heartbeat": now,
                    "started_at": now,
                    "metadata": {},
                }
            ],
            [],
        ]
    )
    pool = _make_pool_mock(conn)

    result = await get_worker_status(pool)
    assert result["health"] == "healthy"
    assert result["status_counts"]["active"] == 1
    assert len(result["active_workers"]) == 1
    assert result["active_workers"][0]["hostname"] == "host1"
    assert result["total_concurrency"] == 4


@pytest.mark.asyncio
async def test_get_worker_status_degraded_with_stale():
    from elephantq.core.heartbeat import get_worker_status

    now = datetime.now(timezone.utc)
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [{"status": "active", "count": 1}],
            [
                {
                    "id": "w1",
                    "hostname": "h1",
                    "pid": 1,
                    "queues": [],
                    "concurrency": 2,
                    "last_heartbeat": now,
                    "started_at": now,
                    "metadata": None,
                }
            ],
            [{"id": "w2", "hostname": "h2", "pid": 2, "last_heartbeat": now}],
        ]
    )
    pool = _make_pool_mock(conn)

    result = await get_worker_status(pool)
    assert result["health"] == "degraded"
    assert len(result["stale_workers"]) == 1


@pytest.mark.asyncio
async def test_get_worker_status_handles_error():
    from elephantq.core.heartbeat import get_worker_status

    @asynccontextmanager
    async def failing_acquire():
        raise RuntimeError("connection refused")
        yield  # pragma: no cover

    pool = AsyncMock()
    pool.acquire = failing_acquire

    result = await get_worker_status(pool)
    assert result["health"] == "unknown"
    assert "error" in result
