"""
Soniq Application Instance

Instance-based architecture to replace global state patterns.
Enables multiple isolated Soniq instances with independent configurations.
"""

import functools
import logging
from pathlib import Path
from typing import Any, List, Optional

from ._active import _active_app
from .core.registry import JobRegistry
from .errors import SoniqError
from .settings import SoniqSettings

logger = logging.getLogger(__name__)


def _with_active_app(method):
    """Decorator that attaches `self` to the active-app contextvar for the
    duration of an async instance method. Feature helpers read this to honor
    the caller's `Soniq` instead of silently using the global app.

    Resets on exit so the var does not leak across tasks: because
    `ContextVar` is task-local, restoration via `reset(token)` is safe even
    when multiple calls happen concurrently on different instances.
    """

    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        token = _active_app.set(self)
        try:
            return await method(self, *args, **kwargs)
        finally:
            _active_app.reset(token)

    return wrapper


def _pool_sizing_error(
    *, concurrency: int, pool_max_size: int, pool_headroom: int
) -> Optional["SoniqError"]:
    """Return an error describing an undersized pool, or None if adequate.

    Pure helper so the arithmetic can be unit-tested without spinning up a
    real backend. `pool_max_size=0` disables the check (some operators set
    it explicitly to opt out). The check is equality-inclusive: a pool
    exactly equal to `concurrency + headroom` is considered enough.
    """
    if pool_max_size <= 0:
        return None
    required = concurrency + pool_headroom
    if required <= pool_max_size:
        return None
    return SoniqError(
        f"Connection pool too small: worker concurrency ({concurrency}) "
        f"plus reserved headroom ({pool_headroom}) requires {required} "
        f"connections, but pool_max_size is {pool_max_size}. "
        f"Raise SONIQ_POOL_MAX_SIZE, lower SONIQ_CONCURRENCY, "
        f"or reduce SONIQ_POOL_HEADROOM.",
        "SONIQ_POOL_TOO_SMALL",
        context={
            "concurrency": concurrency,
            "pool_headroom": pool_headroom,
            "pool_max_size": pool_max_size,
            "required_connections": required,
        },
    )


class Soniq:
    """
    Soniq Application

    Instance-based Soniq application that manages its own database connection,
    job registry, and configuration. Replaces global state patterns with clean
    instance-based architecture.

    Examples:
        # Basic usage
        app = Soniq(database_url="postgresql://localhost/myapp")

        # Custom configuration
        app = Soniq(
            database_url="postgresql://localhost/myapp",
            concurrency=8,
            result_ttl=600
        )

        # Multiple instances
        app1 = Soniq(database_url="postgresql://localhost/app1")
        app2 = Soniq(database_url="postgresql://localhost/app2")
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        config_file: Optional[Path] = None,
        backend: Optional[Any] = None,
        **settings_overrides,
    ):
        """
        Initialize Soniq application instance.

        Args:
            database_url: PostgreSQL connection URL
            config_file: Optional configuration file path
            backend: Optional StorageBackend instance. If not provided,
                creates a PostgresBackend from the database_url.
            **settings_overrides: Override any SoniqSettings field
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
            self._settings = SoniqSettings(
                _env_file=str(config_file), **settings_overrides  # type: ignore[call-arg]
            )
        else:
            self._settings = SoniqSettings(**settings_overrides)

        # Instance components (initialized lazily)
        self._pool: Optional[Any] = None
        self._job_registry = JobRegistry()
        self._hooks: dict[str, list] = {
            "before_job": [],
            "after_job": [],
            "on_error": [],
        }

        logger.debug("Created Soniq instance")

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

            path = database_url if database_url else "soniq.db"
            return SQLiteBackend(path)
        elif name == "postgres":
            # Will be created in _ensure_initialized with settings
            return None
        else:
            raise ValueError(
                f"Unknown backend: {name!r}. Use 'postgres', 'sqlite', or 'memory'."
            )

    @property
    def settings(self) -> SoniqSettings:
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
        Auto-initialize Soniq on first use.

        Creates a PostgresBackend if no backend was provided, then initializes it.
        """
        if self._initialized:
            return

        if self._closed:
            raise SoniqError("Cannot use closed Soniq instance", "SONIQ_APP_CLOSED")

        try:
            logger.debug("Auto-initializing Soniq application...")

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
            logger.debug("Soniq application initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Soniq application: {e}")
            await self._cleanup_on_error()
            raise SoniqError(
                f"Soniq initialization failed: {e}", "SONIQ_INIT_ERROR"
            ) from e

    def _check_pool_sizing(self, concurrency: int) -> None:
        """Refuse to start a worker that would deadlock on a too-small pool.

        Only applies to backends that use an asyncpg connection pool. Memory
        and SQLite backends have no pool and skip the check. A warning here
        was what we had before; operators missed it and workers stalled in
        production. Promoting to a hard error puts the misconfiguration in
        front of them at startup instead of at 3am.
        """
        if not hasattr(self._backend, "pool"):
            return
        err = _pool_sizing_error(
            concurrency=concurrency,
            pool_max_size=self._settings.pool_max_size,
            pool_headroom=self._settings.pool_headroom,
        )
        if err is not None:
            raise err

    async def __aenter__(self):
        await self._ensure_initialized()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    async def close(self):
        """
        Close the Soniq application and cleanup resources.

        Closes database connection pool and cleans up all resources.
        """
        if self._closed:
            logger.warning("Soniq already closed")
            return

        logger.info("Closing Soniq application...")

        try:
            # Close backend (which closes its pool)
            if self._backend:
                await self._backend.close()
                self._pool = None
                logger.debug("Closed backend")

            self._closed = True
            self._initialized = False
            logger.info("Soniq application closed successfully")

        except Exception as e:
            logger.error(f"Error during Soniq application cleanup: {e}")
            # Continue cleanup even if errors occur
            self._closed = True
            self._initialized = False

    @_with_active_app
    async def _reset(self) -> None:
        """
        Delete all jobs and workers. Used in test fixtures.

        Delegates to the backend's reset() method.
        """
        await self._ensure_initialized()
        await self._backend.reset()  # type: ignore[union-attr]

    def job(self, **kwargs):
        """
        Job decorator for this Soniq instance.

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

    @_with_active_app
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

        # Notify workers if backend supports push notifications. Workers
        # also poll on a timer, so a failed notify degrades latency but does
        # not drop the job. Log at debug so it's visible when investigating.
        if self._backend.supports_push_notify:
            try:
                await self._backend.notify_new_job(final_queue)
            except Exception:
                logger.debug(
                    "notify_new_job failed for queue %s; workers will pick up via poll",
                    final_queue,
                    exc_info=True,
                )

        return result_id or job_id

    @_with_active_app
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

    @_with_active_app
    async def run_worker(
        self,
        concurrency: int = 4,
        run_once: bool = False,
        queues: Optional[List[str]] = None,
    ):
        """
        Run a worker for this Soniq instance.

        Args:
            concurrency: Number of concurrent job processing tasks
            run_once: If True, process available jobs once and exit
            queues: List of queue names to process. None means all queues.

        Example:
            app = Soniq(database_url="postgresql://localhost/myapp")
            await app.run_worker(concurrency=2, queues=["high", "default"])
        """
        await self._ensure_initialized()

        self._check_pool_sizing(concurrency)

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
                    # Shutdown path: the scheduler will be reclaimed by the
                    # stale-worker sweep; log for investigation but don't
                    # mask the worker's own exit status.
                    logger.debug(
                        "stop_recurring_scheduler failed during shutdown",
                        exc_info=True,
                    )

    # Job Management API

    @_with_active_app
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

    @_with_active_app
    async def get_result(self, job_id: str):
        """Get the return value of a completed job, or None."""
        await self._ensure_initialized()
        job = await self._backend.get_job(job_id)  # type: ignore[union-attr]
        if job and job.get("status") == "done":
            return job.get("result")
        return None

    @_with_active_app
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

    @_with_active_app
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

    @_with_active_app
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

    @_with_active_app
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

    @_with_active_app
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

    @_with_active_app
    async def _setup(self) -> int:
        """
        Set up Soniq — create database (if needed) and run migrations.

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
        import re

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

        # CREATE DATABASE cannot use parameterized statements, so the name is
        # string-interpolated. The name is operator-controlled (comes from the
        # connection URL) so this is not a classic injection vector, but a
        # stray quote, space, or semicolon in the name still breaks quoting
        # and produces mystifying errors. Reject non-identifiers up front.
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", db_name):
            raise ValueError(
                f"Refusing to CREATE DATABASE for non-identifier name: "
                f"{db_name!r}. soniq auto-create only accepts database "
                f"names matching the SQL identifier pattern "
                f"[A-Za-z_][A-Za-z0-9_$]*; create the database manually if "
                f"you need an unusual name, then skip auto-create."
            )

        try:
            conn = await _asyncpg.connect(server_url)
            try:
                exists = await conn.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname = $1", db_name
                )
                if not exists:
                    # Identifier already validated above.
                    await conn.execute(f'CREATE DATABASE "{db_name}"')
                    logger.info(f"Created database: {db_name}")
            finally:
                await conn.close()
        except ValueError:
            # Don't swallow our own validation error.
            raise
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
