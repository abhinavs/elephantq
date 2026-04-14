"""
ElephantQ Application Instance

Instance-based architecture to replace global state patterns.
Enables multiple isolated ElephantQ instances with independent configurations.
"""

import logging
from pathlib import Path
from typing import Any, List, Optional

from .core.registry import JobRegistry
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
            concurrency=8,
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
        self._pool: Optional[Any] = None
        self._job_registry = JobRegistry()
        self._hooks: dict[str, list] = {
            "before_job": [],
            "after_job": [],
            "on_error": [],
        }

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
    def _is_initialized(self) -> bool:
        """Check if app is initialized."""
        return self._initialized

    @property
    def _is_closed(self) -> bool:
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
                    pool_min_size=self._settings.pool_min_size,
                    pool_max_size=self._settings.pool_max_size,
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
        if not self._pool or self._settings.pool_max_size <= 0:
            return

        required_connections = concurrency + self._settings.pool_headroom
        if required_connections > self._settings.pool_max_size:
            logger.warning(
                "Worker concurrency (%s) + pool headroom (%s) exceeds configured pool max (%s). "
                "Increase ELEPHANTQ_POOL_MAX_SIZE or reduce concurrency to prevent connection exhaustion.",
                concurrency,
                self._settings.pool_headroom,
                self._settings.pool_max_size,
            )

    async def __aenter__(self):
        await self._ensure_initialized()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

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

    async def _reset(self) -> None:
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

    def before_job(self, fn):
        """Register a hook called before each job executes."""
        self._hooks["before_job"].append(fn)
        return fn

    def after_job(self, fn):
        """Register a hook called after each job completes successfully."""
        self._hooks["after_job"].append(fn)
        return fn

    def on_error(self, fn):
        """Register a hook called when a job fails."""
        self._hooks["on_error"].append(fn)
        return fn

    async def enqueue(self, job_func, connection=None, **kwargs):
        """
        Enqueue a job for processing.

        Args:
            job_func: Job function to enqueue
            connection: Optional existing asyncpg connection for transactional enqueue
            **kwargs: Job arguments and options (priority, queue, scheduled_at, unique, dedup_key)

        Returns:
            Job UUID
        """
        await self._ensure_initialized()

        import json
        import uuid

        from .core.queue import _normalize_scheduled_time, _validate_job_arguments
        from .utils.hashing import compute_args_hash

        # Extract enqueue options from kwargs
        priority = kwargs.pop("priority", None)
        queue = kwargs.pop("queue", None)
        scheduled_at = kwargs.pop("scheduled_at", None)
        unique = kwargs.pop("unique", None)
        dedup_key = kwargs.pop("dedup_key", None)

        # Resolve job metadata from registry
        job_name = f"{job_func.__module__}.{job_func.__name__}"
        job_meta = self._job_registry.get_job(job_name)

        if not job_meta:
            raise ValueError(
                f"Job '{job_name}' is not registered. "
                "Did you forget @app.job() on the function?"
            )

        _validate_job_arguments(job_name, job_meta, kwargs)

        final_priority = priority if priority is not None else job_meta["priority"]
        final_queue = queue if queue is not None else job_meta["queue"]
        final_unique = unique if unique is not None else job_meta["unique"]
        scheduled_at = _normalize_scheduled_time(scheduled_at)

        args_hash = compute_args_hash(kwargs) if final_unique else None
        job_id = str(uuid.uuid4())
        args_json = json.dumps(kwargs, default=str)

        # Transactional enqueue via caller-provided connection (Postgres only)
        if connection is not None:
            if hasattr(self._backend, "create_job_transactional"):
                return await self._backend.create_job_transactional(
                    connection=connection,
                    job_id=job_id,
                    job_name=job_name,
                    args=args_json,
                    args_hash=args_hash,
                    max_attempts=job_meta["max_retries"] + 1,
                    priority=final_priority,
                    queue=final_queue,
                    unique=final_unique,
                    dedup_key=dedup_key,
                    scheduled_at=scheduled_at,
                )
            raise ValueError(
                f"Transactional enqueue (connection=) is not supported by "
                f"{type(self._backend).__name__}. Use PostgresBackend for this feature."
            )

        result_id = await self._backend.create_job(
            job_id=job_id,
            job_name=job_name,
            args=args_json,
            args_hash=args_hash,
            max_attempts=job_meta["max_retries"] + 1,
            priority=final_priority,
            queue=final_queue,
            unique=final_unique,
            dedup_key=dedup_key,
            scheduled_at=scheduled_at,
        )

        # Notify workers if backend supports push notifications
        if self._backend.supports_push_notify:
            try:
                await self._backend.notify_new_job(final_queue)
            except Exception:
                pass  # Non-critical — workers will poll

        return result_id or job_id

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

    async def get_pool(self) -> Any:
        """Get database connection pool."""
        await self._ensure_initialized()
        return self._pool  # type: ignore[return-value]

    def _get_job_registry(self) -> JobRegistry:
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
            hooks=self._hooks,
        )

        scheduler_started = False
        if not run_once:
            try:
                from .features.recurring import (
                    _ensure_scheduler_running,
                    stop_recurring_scheduler,
                )

                await _ensure_scheduler_running()
                scheduler_started = True
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(
                    "Recurring scheduler not started: %s", e
                )

        try:
            return await worker.run(
                concurrency=concurrency,
                run_once=run_once,
                queues=queues,
            )
        finally:
            if scheduler_started:
                try:
                    await stop_recurring_scheduler()
                except Exception:
                    pass

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
        return await self._backend.get_job(job_id)  # type: ignore[union-attr]

    async def get_result(self, job_id: str):
        """Get the return value of a completed job, or None."""
        await self._ensure_initialized()
        job = await self._backend.get_job(job_id)  # type: ignore[union-attr]
        if job and job.get("status") == "done":
            return job.get("result")
        return None

    async def cancel_job(self, job_id: str):
        """
        Cancel a queued job.

        Args:
            job_id: UUID of the job to cancel

        Returns:
            True if job was cancelled, False if job wasn't found or already processed
        """
        await self._ensure_initialized()
        return await self._backend.cancel_job(job_id)  # type: ignore[union-attr]

    async def retry_job(self, job_id: str):
        """
        Retry a failed job.

        Args:
            job_id: UUID of the job to retry

        Returns:
            True if job was queued for retry, False if job wasn't found or can't be retried
        """
        await self._ensure_initialized()
        return await self._backend.retry_job(job_id)  # type: ignore[union-attr]

    async def delete_job(self, job_id: str):
        """
        Delete a job from the queue.

        Args:
            job_id: UUID of the job to delete

        Returns:
            True if job was deleted, False if job wasn't found
        """
        await self._ensure_initialized()
        return await self._backend.delete_job(job_id)  # type: ignore[union-attr]

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
        return await self._backend.list_jobs(  # type: ignore[union-attr]
            queue=queue, status=status, limit=limit, offset=offset
        )

    async def get_queue_stats(self):
        """
        Get statistics for all queues.

        Returns:
            List of dictionaries with queue statistics
        """
        await self._ensure_initialized()
        return await self._backend.get_queue_stats()

    async def _get_migration_status(self) -> dict:
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

    async def _run_migrations(self) -> int:
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

    async def _setup(self) -> int:
        """
        Set up ElephantQ — create database (if needed) and run migrations.

        - PostgreSQL: creates the database if it doesn't exist, then runs migrations
        - SQLite: tables created automatically by SQLiteBackend.initialize()
        - Memory: no-op

        Returns:
            Number of migrations applied (0 for SQLite/Memory)
        """
        await self._ensure_initialized()

        # SQLite and Memory backends create tables on initialize() — nothing to migrate
        if not hasattr(self._backend, "pool"):
            return 0

        # PostgreSQL: attempt to create the database, then run migrations
        await self._ensure_postgres_database_exists()
        return await self._run_migrations()

    async def _ensure_postgres_database_exists(self) -> None:
        """Create the PostgreSQL database if it doesn't exist."""
        import asyncpg as _asyncpg

        url = self._settings.database_url
        # Parse database name from URL
        # postgresql://user:pass@host:port/dbname
        if "/" not in url.split("@")[-1]:
            return  # No database name in URL

        parts = url.rsplit("/", 1)
        if len(parts) != 2:
            return

        server_url = parts[0] + "/postgres"  # Connect to default 'postgres' db
        db_name = parts[1].split("?")[0]  # Strip query params

        try:
            conn = await _asyncpg.connect(server_url)
            try:
                exists = await conn.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname = $1", db_name
                )
                if not exists:
                    # Can't use parameterized query for CREATE DATABASE
                    await conn.execute(f'CREATE DATABASE "{db_name}"')
                    logger.info(f"Created database: {db_name}")
            finally:
                await conn.close()
        except Exception as e:
            # Database might already exist, or we might not have permissions
            # Either way, we'll find out when migrations run
            logger.debug(f"Could not auto-create database: {e}")

    async def _cleanup_on_error(self):
        """Cleanup resources after initialization error."""
        try:
            if self._pool:
                await self._pool.close()
                self._pool = None
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
