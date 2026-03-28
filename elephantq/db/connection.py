"""
Database connection utilities.

Pool access goes through the global ElephantQ app's backend.
These functions exist for feature modules that need a raw asyncpg pool.
"""

import contextvars
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import asyncpg

from elephantq.settings import get_settings

# Context variable for thread-local pool management (testing/CLI)
_context_pool: contextvars.ContextVar[Optional[asyncpg.Pool]] = contextvars.ContextVar(
    "elephantq_pool", default=None
)


async def _init_connection(conn):
    """Initialize connection with UTC timezone for consistent scheduled job handling."""
    await conn.execute("SET timezone = 'UTC'")


async def get_pool() -> asyncpg.Pool:
    """
    Get connection pool from the global app's backend.

    Kept for feature modules that import from db.connection directly.
    """
    context_pool = _context_pool.get(None)
    if context_pool is not None:
        return context_pool

    import elephantq

    app = elephantq._get_global_app()
    await app._ensure_initialized()

    backend = app._backend
    if hasattr(backend, "pool"):
        return backend.pool  # type: ignore[union-attr]

    raise RuntimeError(
        "No connection pool available. " "This function requires a PostgreSQL backend."
    )


async def close_pool():
    """Close the global app's backend pool."""
    import elephantq

    if elephantq._global_app is not None and elephantq._global_app._is_initialized:
        await elephantq._global_app.close()


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
