"""
Database connection utilities.

Pool access goes through the global Soniq app's backend.
These functions exist for feature modules that need a raw asyncpg pool.
"""

import contextvars
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import asyncpg

from soniq.settings import get_settings

# Context variable for thread-local pool management (testing/CLI)
_context_pool: contextvars.ContextVar[Optional[asyncpg.Pool]] = contextvars.ContextVar(
    "soniq_pool", default=None
)


async def _init_connection(conn):
    """Initialize connection: UTC timezone, and a JSONB <-> Python codec so
    every layer above this one can treat `args`, `result`, `tags`, etc. as
    native Python values without manual `json.dumps` / `json.loads` dances.

    The encoder uses `default=str` to match the project's long-standing
    tolerance for non-JSON-native types (datetimes, Decimal, UUID) in job
    payloads and results.
    """
    import json

    await conn.execute("SET timezone = 'UTC'")
    await conn.set_type_codec(
        "jsonb",
        encoder=lambda v: json.dumps(v, default=str),
        decoder=json.loads,
        schema="pg_catalog",
    )


async def get_pool() -> asyncpg.Pool:
    """
    Get connection pool from the global app's backend.

    Kept for feature modules that import from db.connection directly.
    """
    context_pool = _context_pool.get(None)
    if context_pool is not None:
        return context_pool

    import soniq

    app = soniq._get_global_app()
    await app._ensure_initialized()

    backend = app._backend
    assert backend is not None  # app._ensure_initialized() above guarantees this
    if backend.supports_connection_pool:
        return backend.pool

    raise RuntimeError(
        "No connection pool available. " "This function requires a PostgreSQL backend."
    )


async def close_pool():
    """Close the global app's backend pool."""
    import soniq

    if soniq._global_app is not None and soniq._global_app._is_initialized:
        await soniq._global_app.close()


@asynccontextmanager
async def connection_context(
    database_url: Optional[str] = None,
) -> AsyncIterator[asyncpg.Pool]:
    """
    Context manager that creates a temporary connection pool.

    Args:
        database_url: Optional database URL. Uses settings if not provided.
    """
    db_url = database_url or get_settings().database_url
    pool = await asyncpg.create_pool(db_url, init=_init_connection)

    token = _context_pool.set(pool)
    try:
        yield pool
    finally:
        _context_pool.reset(token)
        await pool.close()


async def create_pool(database_url: Optional[str] = None) -> asyncpg.Pool:
    """Create a new connection pool without affecting global state."""
    db_url = database_url or get_settings().database_url
    return await asyncpg.create_pool(db_url, init=_init_connection)
