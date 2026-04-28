"""
Soniq Application Instance

Instance-based architecture to replace global state patterns.
Enables multiple isolated Soniq instances with independent configurations.
"""

import asyncio
import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    List,
    Optional,
    ParamSpec,
    TypeVar,
    Union,
    overload,
)

import asyncpg
from pydantic import ValidationError

from .backends import StorageBackend
from .backends.postgres import PostgresBackend
from .backends.postgres.migration_runner import MigrationRunner
from .backends.sqlite import SQLiteBackend
from .core.naming import validate_task_name
from .core.queue import _normalize_scheduled_time
from .core.registry import JobRegistry
from .core.retry import DEFAULT_RETRY_POLICY
from .core.worker import Worker
from .dashboard.app import DashboardService
from .errors import (
    SONIQ_TASK_ARGS_INVALID,
    SONIQ_UNKNOWN_TASK_NAME,
    SoniqError,
)
from .features.dead_letter import DeadLetterService
from .features.logging import LogService
from .features.scheduler import Scheduler, _coerce_schedule
from .features.signing import SigningService
from .features.webhooks import HTTPTransport, WebhookService
from .observability.metrics import DEFAULT_METRICS_SINK
from .plugin import (
    PluginCLI,
    PluginDashboard,
    PluginMigrations,
    PluginRegistry,
    discover_plugins,
)
from .settings import SoniqSettings
from .task_ref import TaskRef
from .testing.memory_backend import MemoryBackend
from .utils.hashing import compute_args_hash
from .utils.producer_id import resolve_producer_id
from .utils.rate_limit import default_warner
from .utils.serialization import DEFAULT_SERIALIZER

if TYPE_CHECKING:
    from .types import QueueStats

_P = ParamSpec("_P")

logger = logging.getLogger(__name__)


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
        backend: Optional[Any] = None,
        retry_policy: Optional[Any] = None,
        serializer: Optional[Any] = None,
        log_sink: Optional[Any] = None,
        metrics_sink: Optional[Any] = None,
        plugins: Optional[List[Any]] = None,
        autoload_plugins: bool = False,
        **settings_overrides: Any,
    ) -> None:
        """
        Initialize Soniq application instance.

        Args:
            database_url: PostgreSQL connection URL
            backend: Optional StorageBackend instance. If not provided,
                creates a PostgresBackend from the database_url.
            retry_policy: Optional `soniq.core.retry.RetryPolicy` instance.
                Defaults to `ExponentialBackoff()` which honors per-job
                `retry_delay` / `retry_backoff` / `retry_max_delay` /
                `retry_jitter` set via the `@app.job(...)` decorator.
                Also settable post-construct via ``app.retry_policy = ...``
                up until ``await app.setup()`` runs.
            serializer: Optional `soniq.utils.serialization.Serializer`
                instance. Defaults to `JSONSerializer`. Custom serializers
                are advisory only at present: backends store via JSONB /
                JSON-text and read via the same path, so non-JSON formats
                require a serializer-aware backend.
                Also settable post-construct via ``app.serializer = ...``.
            log_sink: Optional `soniq.features.logging.LogSink` instance.
                When provided, log records flow into this sink instead of
                (or in addition to) the built-in ``DatabaseLogHandler``.
                Also settable post-construct via ``app.log_sink = ...``.
            metrics_sink: Optional `soniq.observability.MetricsSink`
                instance. Defaults to `NoopMetricsSink`. Pass
                `PrometheusMetricsSink()` to expose per-job metrics
                via `prometheus_client`. The sink is invoked by the
                worker around each job's execution.
                Also settable post-construct via ``app.metrics_sink = ...``.
            plugins: Optional list of ``SoniqPlugin`` instances to install
                during construction. Equivalent to calling ``app.use(p)``
                for each in order. ``SONIQ_PLUGIN_DUPLICATE`` is raised on
                a name collision.
            autoload_plugins: When True, resolve plugins via the
                ``soniq.plugins`` entry-point group and install them
                after the explicit ``plugins=`` list. Off by default so
                imports never have side effects; opt in per instance,
                or via the ``SONIQ_PLUGINS`` env var / ``--plugins`` CLI
                flag.
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
        # Typed as Optional[StorageBackend]: None until _ensure_initialized()
        # constructs a lazy PostgresBackend.
        self._backend: Optional[StorageBackend] = backend

        # Pluggable extension points. Defaults are wired so callers that
        # never touch these fields keep the existing behavior verbatim.
        self._retry_policy = retry_policy or DEFAULT_RETRY_POLICY
        self._serializer = serializer or DEFAULT_SERIALIZER
        self._log_sink = log_sink  # None means "use the built-in handler"
        self._metrics_sink = metrics_sink or DEFAULT_METRICS_SINK

        # Settings with overrides
        # Only pass database_url to settings for postgres backend
        # (SQLite and Memory backends use database_url as a file path, not a Postgres URL)
        if database_url and self._backend is None:
            settings_overrides["database_url"] = database_url

        self._settings = SoniqSettings(**settings_overrides)

        # Instance components (initialized lazily)
        self._job_registry = JobRegistry()
        self._hooks: dict[str, list[Any]] = {
            "before_job": [],
            "after_job": [],
            "on_error": [],
        }
        self._middleware: list[Any] = []
        self._scheduler: Optional[Any] = None
        self._webhooks: Optional[Any] = None
        self._dead_letter: Optional[Any] = None
        self._logs: Optional[Any] = None
        self._signing: Optional[Any] = None
        self._dashboard_data: Optional[Any] = None

        # Plugin infrastructure. ``cli`` / ``dashboard`` / ``migrations``
        # are lazy handles plugins reach for in their ``install()``; the
        # built-in CLI and dashboard read these to discover plugin
        # contributions at parse / render time.
        self._plugins: list[Any] = []
        self._cli = PluginCLI()
        self._dashboard = PluginDashboard()
        self._migrations = PluginMigrations()

        # Bounded executor + post-claim semaphore for sync handlers.
        # The semaphore is loop-affine (created lazily on first use because
        # construction can happen outside an event loop). The executor is a
        # bounded ThreadPoolExecutor so saturation surfaces as backpressure
        # rather than as unbounded thread spawning via asyncio.to_thread.
        self._sync_executor: Optional[ThreadPoolExecutor] = None
        self._sync_pool_semaphore: Optional[asyncio.Semaphore] = None

        for plugin in plugins or []:
            self.use(plugin)
        if autoload_plugins:
            for plugin in discover_plugins():
                self.use(plugin)

        logger.debug("Created Soniq instance")

    def _check_setup_frozen(self, attr: str) -> None:
        """Refuse to mutate a pluggable extension point after setup() ran.

        ``retry_policy`` / ``serializer`` / ``metrics_sink`` / ``log_sink``
        are read by the worker construction path. Letting callers swap them
        after the worker has captured a reference would silently fork
        behavior between in-flight and future jobs; per O.4 they are
        settable up until ``_ensure_initialized()`` runs.
        """
        if self._initialized:
            raise SoniqError(
                f"Cannot set {attr} after Soniq.setup() has run. "
                f"Configure pluggable extension points before the first "
                f"async call (or ``await app.setup()``).",
                "SONIQ_APP_FROZEN",
            )

    @property
    def retry_policy(self) -> Any:
        return self._retry_policy

    @retry_policy.setter
    def retry_policy(self, value: Any) -> None:
        self._check_setup_frozen("retry_policy")
        self._retry_policy = value

    @property
    def serializer(self) -> Any:
        return self._serializer

    @serializer.setter
    def serializer(self, value: Any) -> None:
        self._check_setup_frozen("serializer")
        self._serializer = value

    @property
    def metrics_sink(self) -> Any:
        return self._metrics_sink

    @metrics_sink.setter
    def metrics_sink(self, value: Any) -> None:
        self._check_setup_frozen("metrics_sink")
        self._metrics_sink = value

    @property
    def log_sink(self) -> Any:
        return self._log_sink

    @log_sink.setter
    def log_sink(self, value: Any) -> None:
        self._check_setup_frozen("log_sink")
        self._log_sink = value

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
            return SQLiteBackend(database_url)

        return None  # Default to Postgres

    @staticmethod
    def _resolve_backend_name(name: str, database_url: Optional[str] = None) -> Any:
        """Resolve a string backend name to a backend instance."""
        if name == "memory":
            return MemoryBackend()
        elif name == "sqlite":
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
    def backend(self) -> Any:
        """Public accessor for the storage backend.

        Feature services (`WebhookService`, `DeadLetterService`, ...) take a
        `Soniq` and reach the database through `app.backend.acquire()`. Returns
        `None` until `_ensure_initialized()` has run; lazy backends create
        their pool there.
        """
        return self._backend

    @property
    def registry(self) -> JobRegistry:
        """Public accessor for this instance's job registry."""
        return self._job_registry

    @property
    def is_initialized(self) -> bool:
        """Whether the app has been initialized (backend connected)."""
        return self._initialized

    @property
    def is_closed(self) -> bool:
        """Whether the app has been closed."""
        return self._closed

    async def ensure_initialized(self) -> None:
        """Public idempotent init.

        Plugins, feature services, and library code that may run before
        an explicit ``await app.setup()`` call this to guarantee the
        backend is connected. Returns immediately on subsequent calls.
        """
        await self._ensure_initialized()

    async def _ensure_initialized(self) -> None:
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
                self._backend = PostgresBackend(
                    database_url=self._settings.database_url,
                    pool_min_size=self._settings.pool_min_size,
                    pool_max_size=self._settings.pool_max_size,
                )

            await self._backend.initialize()

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

        Only applies to ``PostgresBackend``. Memory and SQLite backends
        have no asyncpg pool and skip the check. A warning here was what
        we had before; operators missed it and workers stalled in
        production. Promoting to a hard error puts the misconfiguration
        in front of them at startup instead of at 3am.
        """
        if not isinstance(self._backend, PostgresBackend):
            return
        err = _pool_sizing_error(
            concurrency=concurrency,
            pool_max_size=self._settings.pool_max_size,
            pool_headroom=self._settings.pool_headroom,
        )
        if err is not None:
            raise err

    async def __aenter__(self) -> "Soniq":
        await self._ensure_initialized()
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> bool:
        await self.close()
        return False

    async def close(self) -> None:
        """
        Close the Soniq application and cleanup resources.

        Plugin ``on_shutdown`` hooks fire first, in reverse install
        order. Failures during shutdown are logged and swallowed -
        cleanup is best-effort and one plugin's bug must not block the
        next from running.
        """
        if self._closed:
            logger.warning("Soniq already closed")
            return

        logger.info("Closing Soniq application...")

        # Plugin shutdown - reverse install order so the last-installed
        # plugin sees teardown first, mirroring stack semantics.
        for plugin in reversed(self._plugins):
            hook = getattr(plugin, "on_shutdown", None)
            if hook is None:
                continue
            try:
                await hook(self)
            except Exception:
                logger.warning(
                    "Plugin %s on_shutdown failed; continuing.",
                    plugin.name,
                    exc_info=True,
                )

        try:
            # Close backend (which closes its pool)
            if self._backend:
                await self._backend.close()
                logger.debug("Closed backend")

            # Tear down the sync executor. wait=False because the worker
            # shutdown path is responsible for waiting on in-flight sync
            # threads (per docs/contracts/shutdown.md); blocking here a
            # second time would just stall close() during operator-driven
            # rebuilds in tests.
            if self._sync_executor is not None:
                self._sync_executor.shutdown(wait=False)
                self._sync_executor = None
            self._sync_pool_semaphore = None

            self._closed = True
            self._initialized = False
            logger.info("Soniq application closed successfully")

        except Exception as e:
            logger.error(f"Error during Soniq application cleanup: {e}")
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

    def job(self, _func: Optional[Callable[..., Any]] = None, /, **kwargs: Any) -> Any:
        """
        Job decorator for this Soniq instance.

        Celery-style name resolution: when ``name=`` is omitted the task
        name is derived as ``f"{module}.{qualname}"``. Pass ``name=``
        explicitly for cross-service deployments where the name is a
        stable wire-protocol identifier; explicit names are validated
        against ``SONIQ_TASK_NAME_PATTERN``.

        Supports both ``@app.job`` (no parens) and ``@app.job(...)``
        (with kwargs).

        Example - single-repo, derived name::

            @app.job
            async def send_welcome(user_id: int): ...
            # registers as "myapp.tasks.send_welcome"

        Example - explicit name (recommended cross-service)::

            @app.job(name="billing.invoices.send.v2", validate=InvoiceArgs)
            async def send_v2(order_id: str, customer: str): ...

        Args:
            **kwargs: Job configuration options. ``name`` is optional;
                see ``JobRegistry.register_job`` for the full list.

        Returns:
            Job decorator function. The decorated callable preserves its
            original signature via ParamSpec on the inner type annotation.

        Raises:
            SoniqError(SONIQ_INVALID_TASK_NAME): explicit ``name=`` was
                passed and violates the configured task name pattern.
        """
        _JP = ParamSpec("_JP")
        _JR = TypeVar("_JR")

        # Hand the per-instance route_map and task_name_pattern to
        # register_job so consumer-side prefix routing and name validation
        # are resolved against this Soniq's settings, not a global cache
        # (multiple Soniq instances may have different maps / patterns).
        route_map = dict(self._settings.route_map or {})
        task_name_pattern = self._settings.task_name_pattern

        def decorator(
            func: Callable[_JP, Awaitable[_JR]],
        ) -> Callable[_JP, Awaitable[_JR]]:
            return self._job_registry.register_job(
                func,
                _route_map=route_map,
                _task_name_pattern=task_name_pattern,
                **kwargs,
            )

        # `@app.job` (no parens) - Python passed the function in directly.
        if _func is not None:
            return decorator(_func)
        return decorator

    @property
    def scheduler(self) -> Any:
        """Lazy per-app `Scheduler` service.

        Constructed once and reused for the life of the Soniq instance.
        Stays cheap to access from sync code: `Scheduler.__init__` does no
        I/O and never touches the backend until an async method runs.
        """
        if self._scheduler is None:
            self._scheduler = Scheduler(self)
        return self._scheduler

    @property
    def webhooks(self) -> Any:
        """Lazy per-app `WebhookService` (HTTP transport by default).

        Construct ``WebhookService(app, transport=...)`` directly and assign
        to ``app._webhooks`` if you want a non-HTTP transport (e.g. tests).
        """
        if self._webhooks is None:
            self._webhooks = WebhookService(self, transport=HTTPTransport())
        return self._webhooks

    @property
    def dead_letter(self) -> Any:
        """Lazy per-app `DeadLetterService`."""
        if self._dead_letter is None:
            self._dead_letter = DeadLetterService(self)
        return self._dead_letter

    @property
    def logs(self) -> Any:
        """Lazy per-app structured-log query service."""
        if self._logs is None:
            self._logs = LogService(self)
        return self._logs

    @property
    def signing(self) -> Any:
        """Lazy per-app `SigningService` (Fernet encryption helpers)."""
        if self._signing is None:
            self._signing = SigningService(self)
        return self._signing

    @property
    def dashboard_data(self) -> Any:
        """Lazy per-app `DashboardService` (the data layer for the dashboard).

        The HTML/FastAPI surface is constructed by
        ``soniq.dashboard.server.create_dashboard_app(app)``; this
        property is the underlying data accessor that FastAPI handlers use.
        """
        if self._dashboard_data is None:
            self._dashboard_data = DashboardService(self)
        return self._dashboard_data

    def periodic(
        self,
        *,
        cron: Any = None,
        every: Any = None,
        **job_kwargs: Any,
    ) -> Callable[..., Any]:
        """Register a recurring job in one decorator.

        Stamps `_soniq_periodic` on the wrapped callable so
        `Scheduler.start()` (called by `soniq scheduler`) finds it on
        startup, and registers the function with `@app.job` in the same
        pass so callers don't need to stack two decorators. `name=` is
        optional - falls back to `f"{module}.{qualname}"`, same as
        `@app.job`.

        Pass `cron=` for cron expressions (5 fields, or any object whose
        `__str__` is a cron expression like the builders in
        ``soniq.schedules``) and `every=` for an interval (a
        ``timedelta`` or seconds as int/float). They are mutually
        exclusive.
        """
        if cron is None and every is None:
            raise ValueError("@app.periodic requires either cron= or every=")
        if cron is not None and every is not None:
            raise ValueError("@app.periodic cannot accept both cron= and every=")

        # Normalize the schedule shape now so the error surfaces at import
        # time rather than at scheduler.start(). The Scheduler service
        # re-validates on add() in case a caller hand-builds the spec.
        schedule_type, schedule_value = _coerce_schedule(cron=cron, every=every)

        # Capture args / queue / priority / max_attempts off the @app.job
        # kwargs so the scheduler can use them when materializing the
        # schedule on startup. The remaining kwargs flow to @app.job.
        sched_args = job_kwargs.pop("schedule_args", None)

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            wrapped: Any = self.job(**job_kwargs)(func)
            retries = job_kwargs.get("retries")
            wrapped._soniq_periodic = {
                "cron": schedule_value if schedule_type == "cron" else None,
                "every": int(schedule_value) if schedule_type == "interval" else None,
                "args": sched_args or {},
                "queue": job_kwargs.get("queue"),
                "priority": job_kwargs.get("priority"),
                "max_attempts": (retries + 1) if retries is not None else None,
            }
            return wrapped  # type: ignore[no-any-return]

        return decorator

    def before_job(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook called before each job executes."""
        self._hooks["before_job"].append(fn)
        return fn

    def after_job(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook called after each job completes successfully."""
        self._hooks["after_job"].append(fn)
        return fn

    def on_error(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook called when a job fails."""
        self._hooks["on_error"].append(fn)
        return fn

    def middleware(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a middleware that wraps every job's execution.

        Middleware are async callables matching the
        ``soniq.core.middleware.Middleware`` Protocol::

            @app.middleware
            async def trace(ctx, call_next):
                with tracer.start_span(ctx.job_name):
                    return await call_next(ctx)

        Middleware run in registration order (first registered is the
        outermost wrapper). The handler return value flows back through
        the chain. For one-shot side effects without wrapping, prefer
        ``before_job`` / ``after_job`` / ``on_error``.
        """
        self._middleware.append(fn)
        return fn

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def use(self, plugin: Any) -> Any:
        """Install a plugin against this Soniq instance.

        Idempotent on ``plugin.name``: a second installation of the same
        name raises ``SoniqError(SONIQ_PLUGIN_DUPLICATE)`` so two
        deployments accidentally pulling the same plugin twice fail
        loud rather than registering hooks twice.

        ``install`` runs synchronously and must not perform I/O. Plugins
        with deferred work implement ``on_startup`` / ``on_shutdown``,
        which the lifecycle in ``setup()`` / ``close()`` invokes.
        """
        if any(p.name == plugin.name for p in self._plugins):
            raise SoniqError(
                f"Plugin {plugin.name!r} is already installed.",
                "SONIQ_PLUGIN_DUPLICATE",
                context={
                    "name": plugin.name,
                    "version": getattr(plugin, "version", "unknown"),
                },
            )
        plugin.install(self)
        self._plugins.append(plugin)
        logger.debug("Installed plugin %s (version %s)", plugin.name, plugin.version)
        return plugin

    @property
    def plugins(self) -> Any:
        """Read-only registry of installed plugins.

        ``app.plugins["stripe"]`` returns the installed instance,
        ``"stripe" in app.plugins`` and iteration both work. Use this
        to ask "is plugin X installed and at what version?"
        """
        return PluginRegistry(self._plugins)

    @property
    def cli(self) -> Any:
        """Plugin-facing CLI registry.

        Plugins call ``app.cli.add_command(spec)`` in ``install()``;
        ``soniq.cli.main`` reads the registered specs at parse time and
        wires them as additional argparse subparsers.
        """
        return self._cli

    @property
    def dashboard(self) -> Any:
        """Plugin-facing dashboard registry.

        Plugins call ``app.dashboard.add_panel(spec)`` in ``install()``;
        the dashboard server iterates registered panels alongside the
        built-ins. For the data layer (queries against the jobs table),
        see ``app.dashboard_data``.
        """
        return self._dashboard

    @property
    def migrations(self) -> Any:
        """Plugin-facing migration source registry.

        Plugins ship their own ``.sql`` files and register the
        directory: ``app.migrations.register_source(<path>, prefix="0100")``.
        The migration runner discovers plugin sources at ``app.setup()``
        and applies them under the same advisory lock as core.
        """
        return self._migrations

    @overload
    async def enqueue(
        self,
        target: Callable[_P, Awaitable[Any]],
        /,
        *,
        queue: Optional[str] = ...,
        priority: Optional[int] = ...,
        scheduled_at: Union[datetime, timedelta, int, float, None] = ...,
        unique: Optional[bool] = ...,
        dedup_key: Optional[str] = ...,
        connection: Optional[Any] = ...,
        **func_kwargs: Any,
    ) -> str: ...

    @overload
    async def enqueue(
        self,
        target: str,
        /,
        *,
        args: Optional[dict[str, Any]] = ...,
        queue: Optional[str] = ...,
        priority: Optional[int] = ...,
        scheduled_at: Union[datetime, timedelta, int, float, None] = ...,
        unique: Optional[bool] = ...,
        dedup_key: Optional[str] = ...,
        connection: Optional[Any] = ...,
    ) -> str: ...

    @overload
    async def enqueue(
        self,
        target: "TaskRef",
        /,
        *,
        args: Optional[dict[str, Any]] = ...,
        queue: Optional[str] = ...,
        priority: Optional[int] = ...,
        scheduled_at: Union[datetime, timedelta, int, float, None] = ...,
        unique: Optional[bool] = ...,
        dedup_key: Optional[str] = ...,
        connection: Optional[Any] = ...,
    ) -> str: ...

    async def enqueue(
        self,
        target: Any,
        /,
        *,
        args: Optional[dict[str, Any]] = None,
        queue: Optional[str] = None,
        priority: Optional[int] = None,
        scheduled_at: Any = None,
        unique: Optional[bool] = None,
        dedup_key: Optional[str] = None,
        connection: Any = None,
        **func_kwargs: Any,
    ) -> str:
        """
        Enqueue a task for processing. Three input shapes:

        1. **Callable** (single-repo, Celery-style)::

               await app.enqueue(send_welcome, user_id=42)

           The task name is read from ``func._soniq_name`` (set by
           ``@app.job``) or derived as ``f"{module}.{qualname}"``.
           Function arguments travel as ``**func_kwargs``. ``args=`` must
           NOT be passed in this form.

        2. **String task name** (cross-service, by-name)::

               await app.enqueue("users.send_welcome", args={"user_id": 42})

           The name is validated against ``SONIQ_TASK_NAME_PATTERN``.
           Function arguments travel in the explicit ``args=`` dict.
           Behaviour for an unregistered name is governed by
           ``SONIQ_ENQUEUE_VALIDATION``: ``"strict"`` (default) raises
           ``SONIQ_UNKNOWN_TASK_NAME``; ``"warn"`` logs and proceeds;
           ``"none"`` is silent.

        3. **TaskRef** (typed cross-service stub)::

               await app.enqueue(send_welcome_ref, args={"user_id": 42})

           Validates ``args`` against ``ref.args_model`` and uses
           ``ref.default_queue`` if no explicit ``queue=``.

        The shape is disambiguated by the type of ``target``: callable,
        ``str``, or ``TaskRef``. Mixing ``args=`` with ``**func_kwargs``
        raises ``TypeError``; mixing a string ``target`` with
        ``**func_kwargs`` raises ``TypeError`` (kwargs would collide with
        enqueue options - use ``args=dict``).

        Args:
            target: Callable, string task name, or ``TaskRef``.
            args: Task arguments as a dict. For string / TaskRef shapes.
                Defaults to ``{}``. Cannot be combined with
                ``**func_kwargs``.
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
            **func_kwargs: Function arguments when ``target`` is a
                callable. If your function has parameters that collide
                with the enqueue options above, pass them via
                ``args=dict`` instead.

        Returns:
            Job UUID (non-empty string).

        Raises:
            SoniqError(SONIQ_INVALID_TASK_NAME): string name violates
                the configured pattern.
            SoniqError(SONIQ_UNKNOWN_TASK_NAME):
                ``SONIQ_ENQUEUE_VALIDATION="strict"`` and the name is not
                registered locally.
            SoniqError(SONIQ_TASK_ARGS_INVALID): args fail the
                registered or TaskRef ``args_model`` validation.
            TypeError: ``args=`` mixed with ``**func_kwargs``, or
                string ``target`` with ``**func_kwargs``, or ``target``
                is not a callable / str / TaskRef.
        """
        await self._ensure_initialized()
        assert self._backend is not None  # narrow type after init

        # Three-way dispatch on the type of `target`. The TaskRef arm
        # short-circuits the registry-validation step (the ref *is* the
        # local declaration of the name); the callable arm derives the
        # name and uses **func_kwargs as the function args; the string
        # arm requires args=dict.
        ref: Optional[TaskRef] = None
        if isinstance(target, TaskRef):
            ref = target
            job_name = ref.name
            if func_kwargs:
                raise TypeError(
                    "enqueue(TaskRef, ...) cannot accept **kwargs as function "
                    "arguments; pass args=dict instead."
                )
        elif isinstance(target, str):
            job_name = validate_task_name(target, self._settings.task_name_pattern)
            if func_kwargs:
                raise TypeError(
                    "enqueue('name', ...) cannot accept **kwargs as function "
                    "arguments (they would collide with enqueue options "
                    "like queue=, priority=); pass args=dict instead."
                )
        elif callable(target):
            # Callable form: derive name from the registration metadata,
            # use **func_kwargs as function args.
            if args is not None:
                raise TypeError(
                    "enqueue(callable, ...) cannot mix args=dict with "
                    "**kwargs; use one or the other."
                )
            job_name = (
                getattr(target, "_soniq_name", None)
                or f"{target.__module__}.{target.__name__}"
            )
            args = func_kwargs
        else:
            raise TypeError(
                f"enqueue() target must be a callable, string, or TaskRef; "
                f"got {type(target).__name__}"
            )

        if args is None:
            args = {}
        elif not isinstance(args, dict):
            raise TypeError(f"enqueue() args must be a dict, got {type(args).__name__}")

        # TaskRef args_model validation runs even when the name is also
        # registered locally - the ref's model is the producer-side
        # contract.
        if ref is not None and ref.args_model is not None:
            try:
                ref.args_model(**args)
            except ValidationError as e:
                raise SoniqError(
                    f"Invalid arguments for task {job_name!r}: {e}",
                    SONIQ_TASK_ARGS_INVALID,
                    context={"task_name": job_name},
                ) from e

        job_meta = self._job_registry.get_job(job_name)

        # Strict-mode boundary: this consults *only* the in-process registry.
        # The TaskRef arm skips registry validation entirely: the ref is the
        # local declaration of the name. SONIQ_ENQUEUE_VALIDATION governs
        # only the string-name path.
        if job_meta is None and ref is None:
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
                if default_warner().should_warn(job_name):
                    logger.warning(
                        "enqueue: task %r is not registered locally "
                        "(SONIQ_ENQUEUE_VALIDATION=warn); enqueueing anyway. "
                        "Further warnings for this name are rate-limited.",
                        job_name,
                    )
            # mode == "none" -> silent

        # When the task is registered, validate args against the model and
        # use registered defaults for unset enqueue options.
        if job_meta is not None:
            args_model = job_meta.get("args_model")
            # Skip the duplicate validation when the TaskRef arm already ran
            # its own args_model check above.
            if args_model is not None and ref is None:
                try:
                    args_model(**args)
                except ValidationError as e:
                    raise SoniqError(
                        f"Invalid arguments for task {job_name!r}: {e}",
                        SONIQ_TASK_ARGS_INVALID,
                        context={"task_name": job_name},
                    ) from e
            final_priority = priority if priority is not None else job_meta["priority"]
            # Queue precedence: explicit `queue=` > ref.default_queue >
            # registered job_meta queue > system default. The TaskRef arm
            # carries default_queue across the wire to the producer side
            # without coupling to the consumer's registration.
            if queue is not None:
                final_queue = queue
            elif ref is not None and ref.default_queue is not None:
                final_queue = ref.default_queue
            else:
                final_queue = job_meta["queue"]
            final_unique = unique if unique is not None else job_meta["unique"]
            max_attempts = job_meta["max_retries"] + 1
        else:
            # Pure-producer path. Pin defaults here so a future refactor
            # cannot silently change the on-the-wire shape for unregistered
            # names.
            final_priority = priority if priority is not None else 100
            if queue is not None:
                final_queue = queue
            elif ref is not None and ref.default_queue is not None:
                final_queue = ref.default_queue
            else:
                final_queue = "default"
            final_unique = unique if unique is not None else False
            max_attempts = self._settings.max_retries + 1

        scheduled_at = _normalize_scheduled_time(scheduled_at)
        args_hash = compute_args_hash(args) if final_unique else None
        job_id = str(uuid.uuid4())

        producer_id = resolve_producer_id(self._settings.producer_id)

        if connection is not None:
            if isinstance(self._backend, PostgresBackend):
                txn_id = await self._backend.create_job_transactional(
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
                    producer_id=producer_id,
                )
                return txn_id or job_id
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
            producer_id=producer_id,
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

    async def schedule(
        self,
        target: Any,
        run_at: Any,
        *,
        args: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        """Schedule a task for future execution.

        Thin wrapper over ``enqueue`` that sets ``scheduled_at=run_at``.
        ``target`` and ``args`` (or ``**kwargs`` for the callable form)
        follow the same shape as ``enqueue``.
        """
        return await self.enqueue(target, args=args, scheduled_at=run_at, **kwargs)

    async def _get_pool(self) -> Any:
        """Internal: get the underlying asyncpg pool, if any.

        Reserved for the few internal call sites that need raw pool
        access (test fixtures, advanced integration). Public callers
        should go through ``app.backend.acquire()``.
        """
        await self._ensure_initialized()
        if not isinstance(self._backend, PostgresBackend):
            return None
        return self._backend._pool

    def _get_job_registry(self) -> JobRegistry:
        """Get job registry."""
        return self._job_registry

    def _get_sync_dispatch(self) -> tuple[ThreadPoolExecutor, asyncio.Semaphore]:
        """Return the per-instance sync executor and post-claim semaphore.

        Lazy because constructing an `asyncio.Semaphore` requires a running
        event loop in older asyncio versions and we do not want to force one
        at `Soniq()` construction time. The pair is created on the first
        worker dispatch of a sync handler and reused for the instance's
        lifetime; `close()` shuts the executor down.
        """
        if self._sync_executor is None:
            self._sync_executor = ThreadPoolExecutor(
                max_workers=self._settings.sync_handler_pool_size,
                thread_name_prefix="soniq-sync",
            )
        if self._sync_pool_semaphore is None:
            self._sync_pool_semaphore = asyncio.Semaphore(
                self._settings.sync_handler_pool_size
            )
        return self._sync_executor, self._sync_pool_semaphore

    async def run_worker(
        self,
        concurrency: int = 4,
        run_once: bool = False,
        queues: Optional[List[str]] = None,
    ) -> Any:
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
        assert self._backend is not None  # narrowed after _ensure_initialized

        self._check_pool_sizing(concurrency)

        sync_executor, sync_pool_semaphore = self._get_sync_dispatch()
        worker = Worker(
            backend=self._backend,
            registry=self._job_registry,
            settings=self._settings,
            hooks=self._hooks,
            middleware=self._middleware,
            retry_policy=self._retry_policy,
            metrics_sink=self._metrics_sink,
            sync_executor=sync_executor,
            sync_pool_semaphore=sync_pool_semaphore,
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

    async def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """
        Get status information for a specific job.

        Args:
            job_id: UUID of the job to check

        Returns:
            Dict with job information or None if job not found
        """
        await self._ensure_initialized()
        return await self._backend.get_job(job_id)  # type: ignore[union-attr]

    async def get_result(
        self,
        job_id: str,
        *,
        result_model: Optional[Any] = None,
    ) -> Any:
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

    async def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a queued job.

        Args:
            job_id: UUID of the job to cancel

        Returns:
            True if job was cancelled, False if job wasn't found or already processed
        """
        await self._ensure_initialized()
        return await self._backend.cancel_job(job_id)  # type: ignore[union-attr]

    async def retry_job(self, job_id: str) -> bool:
        """
        Retry a failed job.

        Args:
            job_id: UUID of the job to retry

        Returns:
            True if job was queued for retry, False if job wasn't found or can't be retried
        """
        await self._ensure_initialized()
        return await self._backend.retry_job(job_id)  # type: ignore[union-attr]

    async def delete_job(self, job_id: str) -> bool:
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
    ) -> List[dict[str, Any]]:
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

    async def get_queue_stats(self) -> "QueueStats":
        """Whole-instance job state counts in the canonical 6-key shape.

        Returns a single ``QueueStats`` dict (``soniq.types.QueueStats``).
        See ``docs/contracts/queue_stats.md``.
        """
        await self._ensure_initialized()
        assert self._backend is not None
        return await self._backend.get_queue_stats()

    async def _get_migration_status(
        self, version_filter: str | None = None
    ) -> dict[str, Any]:
        """
        Get current database migration status for this instance.

        Args:
            version_filter: Optional 4-digit version prefix; ``"000"``
                limits the report to the core ``0001``-``0009`` slice
                that ``setup()`` applies.

        Returns:
            Dictionary with migration status information
        """
        await self._ensure_initialized()

        migration_runner = MigrationRunner(
            plugin_sources=self._migrations.list_sources()
        )
        async with self._backend.acquire() as conn:  # type: ignore[union-attr]
            return await migration_runner._get_migration_status_with_connection(
                conn, version_filter=version_filter
            )

    async def _run_migrations(self, version_filter: str | None = None) -> int:
        """
        Run all pending database migrations for this instance.

        Args:
            version_filter: Optional 4-digit version prefix. ``"000"``
                applies the core ``0001``-``0009`` slice; ``"0010"``
                applies only the scheduler slice. ``None`` applies
                everything (used by tests; production uses the scoped
                form so each feature opts in).

        Returns:
            Number of migrations applied

        Raises:
            MigrationError: If any migration fails
        """
        await self._ensure_initialized()

        migration_runner = MigrationRunner(
            plugin_sources=self._migrations.list_sources()
        )
        async with self._backend.acquire() as conn:  # type: ignore[union-attr]
            return await migration_runner._run_migrations_with_connection(
                conn, version_filter=version_filter
            )

    async def setup(self) -> int:
        """
        Set up Soniq - create database (if needed) and run migrations.

        - PostgreSQL: creates the database if it doesn't exist, then runs migrations
        - SQLite: tables created automatically by SQLiteBackend.initialize()
        - Memory: no-op

        After migrations, plugin ``on_startup`` hooks fire in install
        order. Failures propagate so a misconfigured plugin can't be
        ignored at boot time.

        Returns:
            Number of migrations applied (0 for SQLite/Memory)
        """
        will_use_postgres = self._backend is None or isinstance(
            self._backend, PostgresBackend
        )
        if will_use_postgres:
            await self._ensure_postgres_database_exists()

        await self._ensure_initialized()
        assert self._backend is not None

        applied = 0
        if isinstance(self._backend, PostgresBackend):
            applied = await self._run_migrations(version_filter="000")

        await self._run_plugin_startup_hooks()
        return applied

    async def _run_plugin_startup_hooks(self) -> None:
        """Invoke ``on_startup(self)`` on every installed plugin in install
        order. Failures propagate; plugins are load-bearing."""
        for plugin in self._plugins:
            hook = getattr(plugin, "on_startup", None)
            if hook is None:
                continue
            await hook(self)

    async def _ensure_postgres_database_exists(self) -> None:
        """Create the PostgreSQL database if it doesn't exist."""
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
            conn = await asyncpg.connect(server_url)
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

    async def _cleanup_on_error(self) -> None:
        """Cleanup resources after initialization error."""
        try:
            if self._backend is not None:
                await self._backend.close()
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
