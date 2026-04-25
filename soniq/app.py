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
        retry_policy: Optional[Any] = None,
        serializer: Optional[Any] = None,
        log_sink: Optional[Any] = None,
        metrics_sink: Optional[Any] = None,
        **settings_overrides,
    ):
        """
        Initialize Soniq application instance.

        Args:
            database_url: PostgreSQL connection URL
            config_file: Optional configuration file path
            backend: Optional StorageBackend instance. If not provided,
                creates a PostgresBackend from the database_url.
            retry_policy: Optional `soniq.core.retry.RetryPolicy` instance.
                Defaults to `ExponentialBackoff()` which honors per-job
                `retry_delay` / `retry_backoff` / `retry_max_delay` /
                `retry_jitter` set via the `@app.job(...)` decorator.
            serializer: Optional `soniq.utils.serialization.Serializer`
                instance. Defaults to `JSONSerializer`. Custom serializers
                are advisory only at present: backends store via JSONB /
                JSON-text and read via the same path, so non-JSON formats
                require a serializer-aware backend.
            log_sink: Optional `soniq.features.logging.LogSink` instance.
                When provided and `logging_enabled = true`, log records
                flow into this sink instead of (or in addition to) the
                built-in `DatabaseLogHandler`.
            metrics_sink: Optional `soniq.observability.MetricsSink`
                instance. Defaults to `NoopMetricsSink`. Pass
                `PrometheusMetricsSink()` to expose per-job metrics
                via `prometheus_client`. The sink is invoked by the
                worker around each job's execution.
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

        # Pluggable extension points. Defaults are wired so callers that
        # never touch these fields keep the existing behavior verbatim.
        from .core.retry import DEFAULT_RETRY_POLICY
        from .observability.metrics import DEFAULT_METRICS_SINK
        from .utils.serialization import DEFAULT_SERIALIZER

        self._retry_policy = retry_policy or DEFAULT_RETRY_POLICY
        self._serializer = serializer or DEFAULT_SERIALIZER
        self._log_sink = log_sink  # None means "use the built-in handler"
        self._metrics_sink = metrics_sink or DEFAULT_METRICS_SINK

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
            from .testing.memory_backend import MemoryBackend

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

            # Expose the backend's pool for code paths that need raw access
            # (migration runner, dashboard data layer, listener cleanup).
            if self._backend.supports_connection_pool:
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
        if not self._backend.supports_connection_pool:  # type: ignore[union-attr]
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

        Requires an explicit ``name=`` keyword argument: a stable, dotted
        protocol identifier (e.g. ``billing.invoices.send.v2``) validated
        against ``SONIQ_TASK_NAME_PATTERN``. Module-derived names were
        removed because the name is the wire protocol once queues cross
        repo boundaries.

        Example::

            @app.job(name="billing.invoices.send.v2", validate=InvoiceArgs)
            async def send_v2(order_id: str, customer: str): ...

        Args:
            **kwargs: Job configuration options. ``name`` is required;
                see ``JobRegistry.register_job`` for the full list.

        Returns:
            Job decorator function. The decorated callable preserves its
            original signature via ParamSpec on the inner type annotation.

        Raises:
            SoniqError(SONIQ_INVALID_TASK_NAME): ``name`` missing or
                violating the configured task name pattern.
        """
        from typing import Callable, ParamSpec, TypeVar

        _P = ParamSpec("_P")
        _R = TypeVar("_R")

        def decorator(func: Callable[_P, _R]) -> Callable[_P, _R]:
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
    async def enqueue(
        self,
        name_or_ref,
        *,
        args: Optional[dict] = None,
        queue: Optional[str] = None,
        priority: Optional[int] = None,
        scheduled_at=None,
        unique: Optional[bool] = None,
        dedup_key: Optional[str] = None,
        connection=None,
    ) -> str:
        """
        Enqueue a task for processing.

        The cross-service producer primitive. Takes a string task name (or,
        from phase 2, a ``TaskRef``) and an explicit ``args`` dict. The old
        callable form ``enqueue(my_func, x=1, y=2)`` was removed; see the
        migration guide and the ``soniq migrate-enqueue`` codemod.

        When ``name_or_ref`` is a string:

        - The name is validated against ``SONIQ_TASK_NAME_PATTERN``.
        - Behaviour for an unregistered name is governed by
          ``SONIQ_ENQUEUE_VALIDATION``: ``"strict"`` (default) raises
          ``SONIQ_UNKNOWN_TASK_NAME`` and writes nothing; ``"warn"`` logs
          and proceeds; ``"none"`` is silent. Producer services that have
          no local registry by design should set ``=warn`` or ``=none``
          explicitly in their environment.

        Args:
            name_or_ref: Dotted task name string. (``TaskRef`` support
                lands in phase 2.)
            args: Task arguments as a dict. Defaults to ``{}``.
            queue: Optional queue override. Advisory; the consumer owns
                routing. Falls back to the registered queue, then
                ``"default"``.
            priority: Optional priority override. Falls back to the
                registered priority, then ``100``.
            scheduled_at: datetime / timedelta / seconds-from-now for
                future scheduling.
            unique: Whether this task should be deduplicated.
            dedup_key: Explicit dedup key (overrides args-hash dedup).
            connection: Asyncpg connection for transactional enqueue
                (Postgres only).

        Returns:
            Job UUID (non-empty string).

        Raises:
            SoniqError(SONIQ_INVALID_TASK_NAME): name violates the
                configured pattern, or `name_or_ref` is the wrong type.
            SoniqError(SONIQ_UNKNOWN_TASK_NAME):
                ``SONIQ_ENQUEUE_VALIDATION="strict"`` and the name is not
                registered locally.
            SoniqError(SONIQ_TASK_ARGS_INVALID): args fail the
                registered ``args_model`` validation.
        """
        from .core.naming import validate_task_name
        from .core.queue import _normalize_scheduled_time
        from .errors import (
            SONIQ_TASK_ARGS_INVALID,
            SONIQ_UNKNOWN_TASK_NAME,
            SoniqError,
        )

        await self._ensure_initialized()
        assert self._backend is not None  # narrow type after init

        import uuid

        from pydantic import ValidationError

        from .utils.hashing import compute_args_hash

        # Phase 1: only string names. TaskRef arm is added in phase 2 / PR 13.
        # Other types fall through to validate_task_name which raises
        # SONIQ_INVALID_TASK_NAME with received_type in context.
        job_name = validate_task_name(name_or_ref)

        if args is None:
            args = {}
        elif not isinstance(args, dict):
            raise TypeError(f"enqueue() args must be a dict, got {type(args).__name__}")

        job_meta = self._job_registry.get_job(job_name)

        # Registry-based validation. Per plan section 15.6 strict-mode
        # boundary: this consults *only* the in-process registry, never the
        # soniq_task_registry DB table that phase 3 introduces. Do not add
        # a fallback path that reads from the DB - that would turn the
        # registry table into distributed coordination.
        if job_meta is None:
            mode = self._settings.enqueue_validation
            if mode == "strict":
                raise SoniqError(
                    f"Task '{job_name}' is not registered locally and "
                    f"SONIQ_ENQUEUE_VALIDATION is 'strict'.",
                    SONIQ_UNKNOWN_TASK_NAME,
                    context={"task_name": job_name, "mode": mode},
                    suggestions=[
                        "Register the task with @app.job(name=...) before enqueueing.",
                        "Or set SONIQ_ENQUEUE_VALIDATION=warn / =none if this "
                        "service is a pure producer with no local registry.",
                    ],
                )
            if mode == "warn":
                # Phase 1 emits a plain warning; PR 7 wires the rate limiter.
                logger.warning(
                    "enqueue: task %r is not registered locally "
                    "(SONIQ_ENQUEUE_VALIDATION=warn); enqueueing anyway",
                    job_name,
                )
            # mode == "none" -> silent

        # When the task is registered, validate args against the model and
        # use registered defaults for unset enqueue options.
        if job_meta is not None:
            args_model = job_meta.get("args_model")
            if args_model is not None:
                try:
                    args_model(**args)
                except ValidationError as e:
                    raise SoniqError(
                        f"Invalid arguments for task {job_name!r}: {e}",
                        SONIQ_TASK_ARGS_INVALID,
                        context={"task_name": job_name},
                    ) from e
            final_priority = priority if priority is not None else job_meta["priority"]
            final_queue = queue if queue is not None else job_meta["queue"]
            final_unique = unique if unique is not None else job_meta["unique"]
            max_attempts = job_meta["max_retries"] + 1
        else:
            # Pure-producer path. Pin defaults here so a future refactor
            # cannot silently change the on-the-wire shape for unregistered
            # names.
            final_priority = priority if priority is not None else 100
            final_queue = queue if queue is not None else "default"
            final_unique = unique if unique is not None else False
            max_attempts = self._settings.max_retries + 1

        scheduled_at = _normalize_scheduled_time(scheduled_at)
        args_hash = compute_args_hash(args) if final_unique else None
        job_id = str(uuid.uuid4())

        if connection is not None:
            if self._backend.supports_transactional_enqueue:
                txn_id: str = await self._backend.create_job_transactional(
                    connection=connection,
                    job_id=job_id,
                    job_name=job_name,
                    args=args,
                    args_hash=args_hash,
                    max_attempts=max_attempts,
                    priority=final_priority,
                    queue=final_queue,
                    unique=final_unique,
                    dedup_key=dedup_key,
                    scheduled_at=scheduled_at,
                )
                return txn_id
            raise ValueError(
                f"Transactional enqueue (connection=) is not supported by "
                f"{type(self._backend).__name__}. Use PostgresBackend for this feature."
            )

        result_id = await self._backend.create_job(
            job_id=job_id,
            job_name=job_name,
            args=args,
            args_hash=args_hash,
            max_attempts=max_attempts,
            priority=final_priority,
            queue=final_queue,
            unique=final_unique,
            dedup_key=dedup_key,
            scheduled_at=scheduled_at,
        )

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
    async def schedule(self, name_or_ref, run_at, *, args=None, **kwargs):
        """Schedule a task for future execution.

        Thin wrapper over ``enqueue`` that sets ``scheduled_at=run_at``.
        ``name_or_ref`` and ``args`` follow the same shape as ``enqueue``.
        """
        return await self.enqueue(name_or_ref, args=args, scheduled_at=run_at, **kwargs)

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

        from .core.worker import Worker

        worker = Worker(
            backend=self._backend,
            registry=self._job_registry,
            settings=self._settings,
            hooks=self._hooks,
            retry_policy=self._retry_policy,
            metrics_sink=self._metrics_sink,
        )

        # `soniq start` only runs the worker. Recurring jobs require a
        # separate `soniq scheduler` process. If the loaded job modules
        # registered any `@periodic`-decorated functions and the operator
        # has not opted out, emit a one-time WARN so a forgotten sidecar
        # is visible at startup rather than at "my recurring job didn't
        # fire" time.
        if not run_once:
            self._maybe_warn_periodic_without_scheduler()

        return await worker.run(
            concurrency=concurrency,
            run_once=run_once,
            queues=queues,
        )

    def _maybe_warn_periodic_without_scheduler(self) -> None:
        """One-time warning when @periodic jobs exist and no scheduler runs.

        Suppressible with `SONIQ_SCHEDULER_SUPPRESS_WARNING=1` for
        deployments that intentionally split scheduler and worker but
        don't want this WARN cluttering the worker's logs.
        """
        import os

        if os.environ.get("SONIQ_SCHEDULER_SUPPRESS_WARNING", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return

        all_jobs = self._job_registry.list_jobs()
        periodic_jobs = [
            name
            for name, meta in all_jobs.items()
            if getattr(meta.get("func"), "_soniq_periodic", None) is not None
        ]
        if not periodic_jobs:
            return

        logger.warning(
            "Detected %d @periodic job(s) (%s) but `soniq start` no longer "
            "runs the recurring scheduler. Start `soniq scheduler` as a "
            "separate process or those jobs will never fire. Suppress "
            "this warning with SONIQ_SCHEDULER_SUPPRESS_WARNING=1.",
            len(periodic_jobs),
            ", ".join(sorted(periodic_jobs)[:3])
            + (", ..." if len(periodic_jobs) > 3 else ""),
        )

    # Job Management API

    @_with_active_app
    async def get_job(self, job_id: str):
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
    async def get_result(
        self,
        job_id: str,
        *,
        result_model: Optional[Any] = None,
    ):
        """Get the return value of a completed job, or None.

        When `result_model` is provided, the stored value is constructed
        through it before being returned. The model can be any callable
        that accepts the stored value: a Pydantic `BaseModel` (uses
        `model_validate` when present), a dataclass, or any class whose
        `__init__` accepts the dict.

        Returns `None` if the job is not done, has no return value, or
        does not exist. Raises whatever the model raises on validation
        failure.
        """
        await self._ensure_initialized()
        job = await self._backend.get_job(job_id)  # type: ignore[union-attr]
        if not job or job.get("status") != "done":
            return None
        result = job.get("result")
        if result is None or result_model is None:
            return result
        validate = getattr(result_model, "model_validate", None)
        if callable(validate):
            return validate(result)
        if isinstance(result, dict):
            return result_model(**result)
        return result_model(result)

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
        assert self._backend is not None  # narrow type after init

        # SQLite and Memory backends create tables on initialize() - nothing to migrate
        if not self._backend.supports_migrations:
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
