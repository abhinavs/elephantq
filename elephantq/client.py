"""
ElephantQ Application Instance

Instance-based architecture to replace global state patterns.
Enables multiple isolated ElephantQ instances with independent configurations.
"""

import logging
from pathlib import Path
from typing import Any, List, Optional

import asyncpg

from .core.registry import JobRegistry
from .db.helpers import rows_affected as _rows_affected
from .errors import ElephantQError
from .settings import ElephantQSettings

logger = logging.getLogger(__name__)


class ElephantQ:
    """
    ElephantQ Application

    Instance-based ElephantQ application that manages its own database connection,
    job registry, and configuration. Replaces global state patterns with clean
    instance-based architecture.

    Examples:
        # Basic usage
        app = ElephantQ(database_url="postgresql://localhost/myapp")

        # Custom configuration
        app = ElephantQ(
            database_url="postgresql://localhost/myapp",
            default_concurrency=8,
            result_ttl=600
        )

        # Multiple instances
        app1 = ElephantQ(database_url="postgresql://localhost/app1")
        app2 = ElephantQ(database_url="postgresql://localhost/app2")
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        config_file: Optional[Path] = None,
        backend: Optional[Any] = None,
        **settings_overrides,
    ):
        """
        Initialize ElephantQ application instance.

        Args:
            database_url: PostgreSQL connection URL
            config_file: Optional configuration file path
            backend: Optional StorageBackend instance. If not provided,
                creates a PostgresBackend from the database_url.
            **settings_overrides: Override any ElephantQSettings field
        """
        # Core instance state
        self._initialized = False
        self._closed = False

        # Resolve backend: explicit string name, auto-detect from URL, or None (lazy Postgres)
        if isinstance(backend, str):
            backend = self._resolve_backend_name(backend, database_url)
        elif backend is None and database_url:
            backend = self._auto_detect_backend(database_url)
        self._backend = backend

        # Settings with overrides
        # Only pass database_url to settings for postgres backend
        # (SQLite and Memory backends use database_url as a file path, not a Postgres URL)
        if database_url and self._backend is None:
            settings_overrides["database_url"] = database_url

        if config_file:
            self._settings = ElephantQSettings(
                _env_file=str(config_file), **settings_overrides  # type: ignore[call-arg]
            )
        else:
            self._settings = ElephantQSettings(**settings_overrides)

        # Instance components (initialized lazily)
        self._pool: Optional[asyncpg.Pool] = None
        self._job_registry = JobRegistry()

        logger.debug("Created ElephantQ instance")

    @staticmethod
    def _auto_detect_backend(database_url: str) -> Any:
        """Auto-detect backend from database URL format.

        - postgresql:// or postgres:// → None (PostgresBackend created lazily)
        - *.db or *.sqlite → SQLiteBackend
        - anything else → None (assume Postgres, will fail at connect if wrong)
        """
        if database_url.startswith(("postgresql://", "postgres://")):
            return None  # PostgresBackend created in _ensure_initialized

        if database_url.endswith((".db", ".sqlite", ".sqlite3")):
            from .backends.sqlite import SQLiteBackend

            return SQLiteBackend(database_url)

        return None  # Default to Postgres

    @staticmethod
    def _resolve_backend_name(name: str, database_url: Optional[str] = None) -> Any:
        """Resolve a string backend name to a backend instance."""
        if name == "memory":
            from .backends.memory import MemoryBackend

            return MemoryBackend()
        elif name == "sqlite":
            from .backends.sqlite import SQLiteBackend

            path = database_url if database_url else "elephantq.db"
            return SQLiteBackend(path)
        elif name == "postgres":
            # Will be created in _ensure_initialized with settings
            return None
        else:
            raise ValueError(
                f"Unknown backend: {name!r}. Use 'postgres', 'sqlite', or 'memory'."
            )

    @property
    def settings(self) -> ElephantQSettings:
        """Get application settings."""
        return self._settings

    @property
    def backend(self):
        """Access the storage backend."""
        return self._backend

    @property
    def is_initialized(self) -> bool:
        """Check if app is initialized."""
        return self._initialized

    @property
    def is_closed(self) -> bool:
        """Check if app is closed."""
        return self._closed

    async def _ensure_initialized(self):
        """
        Auto-initialize ElephantQ on first use.

        Creates a PostgresBackend if no backend was provided, then initializes it.
        """
        if self._initialized:
            return

        if self._closed:
            raise ElephantQError(
                "Cannot use closed ElephantQ instance", "ELEPHANTQ_APP_CLOSED"
            )

        try:
            logger.debug("Auto-initializing ElephantQ application...")

            # Create backend if not provided
            if self._backend is None:
                from .backends.postgres import PostgresBackend

                self._backend = PostgresBackend(
                    database_url=self._settings.database_url,
                    pool_min_size=self._settings.db_pool_min_size,
                    pool_max_size=self._settings.db_pool_max_size,
                )

            await self._backend.initialize()

            # Keep _pool reference for backward compat with code that uses it directly
            if hasattr(self._backend, "pool"):
                self._pool = self._backend.pool

            self._initialized = True
            logger.debug("ElephantQ application initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize ElephantQ application: {e}")
            await self._cleanup_on_error()
            raise ElephantQError(
                f"ElephantQ initialization failed: {e}", "ELEPHANTQ_INIT_ERROR"
            ) from e

    def _warn_if_pool_too_small(self, concurrency: int) -> None:
        """Warn when worker concurrency + headroom exceeds the configured pool max size."""
        if not self._pool or self._settings.db_pool_max_size <= 0:
            return

        required_connections = concurrency + self._settings.db_pool_safety_margin
        if required_connections > self._settings.db_pool_max_size:
            logger.warning(
                "Worker concurrency (%s) + pool safety margin (%s) exceeds configured pool max (%s). "
                "Increase ELEPHANTQ_DB_POOL_MAX_SIZE or reduce concurrency to prevent connection exhaustion.",
                concurrency,
                self._settings.db_pool_safety_margin,
                self._settings.db_pool_max_size,
            )

    async def close(self):
        """
        Close the ElephantQ application and cleanup resources.

        Closes database connection pool and cleans up all resources.
        """
        if self._closed:
            logger.warning("ElephantQ already closed")
            return

        logger.info("Closing ElephantQ application...")

        try:
            # Close backend (which closes its pool)
            if self._backend:
                await self._backend.close()
                self._pool = None
                logger.debug("Closed backend")

            self._closed = True
            self._initialized = False
            logger.info("ElephantQ application closed successfully")

        except Exception as e:
            logger.error(f"Error during ElephantQ application cleanup: {e}")
            # Continue cleanup even if errors occur
            self._closed = True
            self._initialized = False

    async def reset(self) -> None:
        """
        Delete all jobs and workers. Used in test fixtures.

        Delegates to the backend's reset() method.
        """
        await self._ensure_initialized()
        await self._backend.reset()  # type: ignore[union-attr]

    def job(self, **kwargs):
        """
        Job decorator for this ElephantQ instance.

        Args:
            **kwargs: Job configuration options

        Returns:
            Job decorator function
        """

        def decorator(func):
            return self._job_registry.register_job(func, **kwargs)

        return decorator

    async def enqueue(self, job_func, connection=None, **kwargs):
        """
        Enqueue a job for processing.

        Args:
            job_func: Job function to enqueue
            connection: Optional existing asyncpg connection for transactional enqueue
            **kwargs: Job arguments and options

        Returns:
            Job UUID
        """
        await self._ensure_initialized()

        # Import here to avoid circular dependencies
        from .core.queue import enqueue_job

        return await enqueue_job(
            self._pool, self._job_registry, job_func, connection=connection, **kwargs  # type: ignore[arg-type]
        )

    async def schedule(self, job_func, run_at, **kwargs):
        """
        Schedule a job for future execution.

        Args:
            job_func: Job function to schedule
            run_at: When to run the job (datetime)
            **kwargs: Job arguments and options

        Returns:
            Job UUID
        """
        return await self.enqueue(job_func, scheduled_at=run_at, **kwargs)

    async def get_pool(self) -> asyncpg.Pool:
        """Get database connection pool."""
        await self._ensure_initialized()
        return self._pool  # type: ignore[return-value]

    def get_job_registry(self) -> JobRegistry:
        """Get job registry."""
        return self._job_registry

    async def run_worker(
        self,
        concurrency: int = 4,
        run_once: bool = False,
        queues: Optional[List[str]] = None,
    ):
        """
        Run a worker for this ElephantQ instance.

        Args:
            concurrency: Number of concurrent job processing tasks
            run_once: If True, process available jobs once and exit
            queues: List of queue names to process. None means all queues.

        Example:
            app = ElephantQ(database_url="postgresql://localhost/myapp")
            await app.run_worker(concurrency=2, queues=["high", "default"])
        """
        await self._ensure_initialized()

        self._warn_if_pool_too_small(concurrency)

        from .worker import Worker

        worker = Worker(
            backend=self._backend,
            registry=self._job_registry,
            settings=self._settings,
        )
        return await worker.run(
            concurrency=concurrency,
            run_once=run_once,
            queues=queues,
        )

    # Job Management API

    async def get_job_status(self, job_id: str):
        """
        Get status information for a specific job.

        Args:
            job_id: UUID of the job to check

        Returns:
            Dict with job information or None if job not found
        """
        await self._ensure_initialized()

        import json
        import uuid

        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            row = await conn.fetchrow(
                """
                SELECT id, job_name, args, status, attempts, max_attempts,
                       queue, priority, scheduled_at, last_error,
                       created_at, updated_at
                FROM elephantq_jobs
                WHERE id = $1
            """,
                uuid.UUID(job_id),
            )

            if not row:
                return None

            return {
                "id": str(row["id"]),
                "job_name": row["job_name"],
                "args": json.loads(row["args"]),
                "status": row["status"],
                "attempts": row["attempts"],
                "max_attempts": row["max_attempts"],
                "queue": row["queue"],
                "priority": row["priority"],
                "scheduled_at": (
                    row["scheduled_at"].isoformat() if row["scheduled_at"] else None
                ),
                "last_error": row["last_error"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
            }

    async def cancel_job(self, job_id: str):
        """
        Cancel a queued job.

        Args:
            job_id: UUID of the job to cancel

        Returns:
            True if job was cancelled, False if job wasn't found or already processed
        """
        await self._ensure_initialized()

        import uuid

        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            result = await conn.execute(
                """
                UPDATE elephantq_jobs
                SET status = 'cancelled', updated_at = NOW()
                WHERE id = $1 AND status = 'queued'
            """,
                uuid.UUID(job_id),
            )

            # Check if any rows were affected
            return _rows_affected(result) == 1

    async def retry_job(self, job_id: str):
        """
        Retry a failed job.

        Args:
            job_id: UUID of the job to retry

        Returns:
            True if job was queued for retry, False if job wasn't found or can't be retried
        """
        await self._ensure_initialized()

        import uuid

        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            result = await conn.execute(
                """
                UPDATE elephantq_jobs
                SET status = 'queued', attempts = 0, last_error = NULL, updated_at = NOW()
                WHERE id = $1 AND status IN ('dead_letter', 'failed')
            """,
                uuid.UUID(job_id),
            )

            # Check if any rows were affected
            return _rows_affected(result) == 1

    async def delete_job(self, job_id: str):
        """
        Delete a job from the queue.

        Args:
            job_id: UUID of the job to delete

        Returns:
            True if job was deleted, False if job wasn't found
        """
        await self._ensure_initialized()

        import uuid

        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            result = await conn.execute(
                "DELETE FROM elephantq_jobs WHERE id = $1",
                uuid.UUID(job_id),
            )

            # Check if any rows were affected
            return _rows_affected(result) == 1

    async def list_jobs(
        self,
        queue: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ):
        """
        List jobs with optional filtering.

        Args:
            queue: Filter by queue name
            status: Filter by job status
            limit: Maximum number of jobs to return
            offset: Number of jobs to skip

        Returns:
            List of job dictionaries
        """
        await self._ensure_initialized()

        import json

        # Build the query dynamically based on filters
        conditions: list[str] = []
        params: list[Any] = []
        param_count = 0

        if queue is not None:
            param_count += 1
            conditions.append(f"queue = ${param_count}")
            params.append(queue)

        if status is not None:
            param_count += 1
            conditions.append(f"status = ${param_count}")
            params.append(status)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        param_count += 1
        limit_param = f"${param_count}"
        params.append(limit)

        param_count += 1
        offset_param = f"${param_count}"
        params.append(offset)

        query = f"""
            SELECT id, job_name, args, status, attempts, max_attempts,
                   queue, priority, scheduled_at, last_error,
                   created_at, updated_at
            FROM elephantq_jobs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT {limit_param} OFFSET {offset_param}
        """

        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            rows = await conn.fetch(query, *params)

            return [
                {
                    "id": str(row["id"]),
                    "job_name": row["job_name"],
                    "args": json.loads(row["args"]),
                    "status": row["status"],
                    "attempts": row["attempts"],
                    "max_attempts": row["max_attempts"],
                    "queue": row["queue"],
                    "priority": row["priority"],
                    "scheduled_at": (
                        row["scheduled_at"].isoformat() if row["scheduled_at"] else None
                    ),
                    "last_error": row["last_error"],
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat(),
                }
                for row in rows
            ]

    async def get_queue_stats(self):
        """
        Get statistics for all queues.

        Returns:
            List of dictionaries with queue statistics
        """
        await self._ensure_initialized()

        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            rows = await conn.fetch(
                """
                SELECT
                    queue,
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status = 'queued') as queued,
                    COUNT(*) FILTER (WHERE status = 'processing') as processing,
                    COUNT(*) FILTER (WHERE status = 'done') as done,
                    COUNT(*) FILTER (WHERE status = 'dead_letter') as dead_letter,
                    COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled
                FROM elephantq_jobs
                GROUP BY queue
                ORDER BY queue
            """
            )

            return [
                {
                    "queue": row["queue"],
                    "total": row["total"],
                    "queued": row["queued"],
                    "processing": row["processing"],
                    "done": row["done"],
                    "dead_letter": row["dead_letter"],
                    "cancelled": row["cancelled"],
                }
                for row in rows
            ]

    async def get_migration_status(self) -> dict:
        """
        Get current database migration status for this instance.

        Returns:
            Dictionary with migration status information
        """
        await self._ensure_initialized()

        # Use the migration runner with our instance's connection pool
        from .db.migrations import MigrationRunner

        migration_runner = MigrationRunner()
        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            return await migration_runner._get_migration_status_with_connection(conn)

    async def run_migrations(self) -> int:
        """
        Run all pending database migrations for this instance.

        Returns:
            Number of migrations applied

        Raises:
            MigrationError: If any migration fails
        """
        await self._ensure_initialized()

        # Use the migration runner with our instance's connection pool
        from .db.migrations import MigrationRunner

        migration_runner = MigrationRunner()
        async with self._pool.acquire() as conn:  # type: ignore[union-attr]
            return await migration_runner._run_migrations_with_connection(conn)

    async def setup(self) -> int:
        """Create/upgrade ElephantQ tables via migrations (instance API)."""
        return await self.run_migrations()

    async def _cleanup_on_error(self):
        """Cleanup resources after initialization error."""
        try:
            if self._pool:
                await self._pool.close()
                self._pool = None
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
