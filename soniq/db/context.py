"""
Database Context Management for Soniq

Provides a unified way to access database connections for both Global API
and Instance-based API usage patterns. This allows optional features to
work correctly with both --database-url CLI parameter and global configuration.
"""

import logging
from typing import Optional

import asyncpg

from ..app import Soniq
from .connection import _init_connection
from .connection import get_pool as get_global_pool

logger = logging.getLogger(__name__)


class DatabaseContext:
    """
    Database context that provides unified access to database connections.

    Supports both global API and instance-based API patterns, allowing
    Optional features to work with either approach transparently.
    """

    def __init__(
        self,
        soniq_instance: Optional[Soniq] = None,
        database_url: Optional[str] = None,
    ):
        """
        Initialize database context.

        Args:
            soniq_instance: Soniq instance for instance-based API
            database_url: Database URL for direct connection (fallback)
        """
        self._soniq_instance = soniq_instance
        self._database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None
        self._owns_pool = False

    @classmethod
    def from_global_api(cls) -> "DatabaseContext":
        """Create context using global Soniq API."""
        return cls()

    @classmethod
    def from_instance(cls, soniq_instance: Soniq) -> "DatabaseContext":
        """Create context from Soniq instance."""
        return cls(soniq_instance=soniq_instance)

    @classmethod
    def from_database_url(cls, database_url: str) -> "DatabaseContext":
        """Create context from database URL directly."""
        return cls(database_url=database_url)

    async def __aenter__(self):
        pool = await self.get_pool()
        return pool

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    async def get_pool(self) -> asyncpg.Pool:
        """
        Get database connection pool.

        Returns the appropriate pool based on the context:
        - Instance-based: uses Soniq instance's pool
        - Global API: uses global pool
        - Direct URL: creates dedicated pool
        """
        if self._soniq_instance:
            # Use Soniq instance's pool
            return await self._soniq_instance.get_pool()

        elif self._database_url:
            # Create dedicated pool for this URL
            if not self._pool:
                self._pool = await asyncpg.create_pool(
                    self._database_url, init=_init_connection
                )
                self._owns_pool = True
            return self._pool

        else:
            # Use global pool (fallback for global API)
            return await get_global_pool()

    async def execute_query(self, query: str, *args):
        """Execute a query using the context's database connection."""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def execute_many(self, query: str, *args):
        """Execute a query that returns multiple rows."""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def close(self):
        """Close the database context and clean up resources."""
        if self._owns_pool and self._pool:
            await self._pool.close()
            self._pool = None
            self._owns_pool = False

    @property
    def database_url(self) -> Optional[str]:
        """Get the database URL if available."""
        if self._soniq_instance:
            return self._soniq_instance.settings.database_url
        return self._database_url

    def __repr__(self) -> str:
        if self._soniq_instance:
            return f"DatabaseContext(instance={self._soniq_instance})"
        elif self._database_url:
            return f"DatabaseContext(url={self._database_url})"
        else:
            return "DatabaseContext(global)"


# Context management for CLI commands
_current_context: Optional[DatabaseContext] = None


def set_current_context(context: DatabaseContext):
    """Set the current database context for CLI commands."""
    global _current_context
    _current_context = context


def get_current_context() -> DatabaseContext:
    """
    Get the current database context.

    Falls back to global API context if none is set.
    """
    global _current_context
    if _current_context is None:
        _current_context = DatabaseContext.from_global_api()
    return _current_context


def clear_current_context():
    """Clear the current database context."""
    global _current_context
    if _current_context:
        # Note: We don't await close() here since this is sync
        # The context will be cleaned up when the CLI command completes
        _current_context = None


async def get_context_pool() -> asyncpg.Pool:
    """
    Get database pool from the global Soniq app's backend.

    This is the main function that feature modules use to get a
    database connection pool. It delegates to the global app's
    PostgresBackend, which manages the pool.
    """
    # Try context-local first (for CLI commands with explicit DB URL)
    if _current_context is not None:
        return await _current_context.get_pool()

    # Otherwise use the global app's backend
    import soniq

    app = soniq._get_global_app()
    await app._ensure_initialized()

    # Get pool from backend (PostgresBackend exposes .pool)
    backend = app._backend
    assert backend is not None  # app._ensure_initialized() above guarantees this
    if backend.supports_connection_pool:
        return backend.pool

    # Fallback for non-Postgres backends
    return await app.get_pool()


async def get_database_pool() -> asyncpg.Pool:
    """Alias for get_context_pool()."""
    return await get_context_pool()
