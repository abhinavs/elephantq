"""
Soniq: Async Job Queue for Python (Backed by PostgreSQL)

Simple global usage::

    import soniq

    @soniq.job
    async def my_job(message: str):
        print(f"Processing: {message}")

    # Task name is derived from `f"{module}.{qualname}"` by default.
    await soniq.enqueue("myapp.my_job", args={"message": "Hello World"})
    await soniq.run_worker()

Or pass an explicit name (recommended for cross-service deployments
where the name is a wire-protocol identifier)::

    @app.job(name="users.send_welcome")
    async def send_welcome(user_id: int):
        ...

    await app.enqueue("users.send_welcome", args={"user_id": 42})
"""

from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from .types import QueueStats

from .app import Soniq
from .job import JobContext, JobStatus, Snooze
from .schedules import cron, daily, every, monthly, weekly
from .task_ref import TaskRef, task_ref

try:
    __version__ = version("soniq")
except PackageNotFoundError:
    __version__ = "0.0.0"

# Global Soniq instance for convenience API
_global_app: Optional[Soniq] = None

# Global job registry to survive instance recreation
_global_job_registry: list[tuple[Any, dict[str, Any]]] = []

__all__ = [
    "Soniq",
    "job",
    "enqueue",
    "schedule",
    "run_worker",
    "setup",
    "_reset",
    "configure",
    "get_job",
    "get_result",
    "cancel_job",
    "retry_job",
    "delete_job",
    "list_jobs",
    "get_queue_stats",
    "periodic",
    "JobContext",
    "JobStatus",
    "Snooze",
    "TaskRef",
    "task_ref",
    "every",
    "cron",
    "daily",
    "weekly",
    "monthly",
    "DASHBOARD_AVAILABLE",
    "get_global_app",
]

# Dashboard availability flag (for CLI checks)
try:
    from .dashboard.server import FASTAPI_AVAILABLE as DASHBOARD_AVAILABLE
except Exception:
    DASHBOARD_AVAILABLE = False


def get_global_app() -> Soniq:
    """Get or create the global Soniq application instance.

    Lazy: the first call constructs a ``Soniq`` with default settings,
    re-registering all globally-defined jobs against it. Subsequent
    calls return the same instance until ``close()`` runs.

    Used by the global convenience API (``soniq.enqueue``,
    ``soniq.run_worker``, ...) and by feature services that want to
    fall back to the global app when no instance was wired in.
    """
    global _global_app

    if _global_app is None or _global_app.is_closed:
        _global_app = Soniq()

        # Re-register all global jobs with the new instance
        for job_func, job_kwargs in _global_job_registry:
            _global_app.job(**job_kwargs)(job_func)

    return _global_app


async def configure(
    *,
    database_url: Optional[str] = None,
    concurrency: Optional[int] = None,
    max_retries: Optional[int] = None,
    queues: Optional[list[str]] = None,
    pool_min_size: Optional[int] = None,
    pool_max_size: Optional[int] = None,
    result_ttl: Optional[int] = None,
    debug: Optional[bool] = None,
    environment: Optional[str] = None,
    **extra: Any,
) -> None:
    """
    Configure the global Soniq instance.

    This is async because reconfiguring must close the prior app's asyncpg
    pool before the replacement is wired up. The old behavior only flipped a
    private `_closed` flag and orphaned the pool, leaking connections on
    every reconfigure (visible in test suites and hot-reload dev workflows).

    Args:
        database_url: Database connection URL
        concurrency: Worker concurrency (1-100)
        max_retries: Default max retry attempts (0-10)
        queues: Default queues to process
        pool_min_size: Minimum connection pool size
        pool_max_size: Maximum connection pool size
        result_ttl: Seconds to keep completed job results
        debug: Enable debug mode
        environment: Environment name (development, testing, production)
        **extra: Additional SoniqSettings fields
    """
    global _global_app

    settings_kwargs = {}
    explicit = {
        "database_url": database_url,
        "concurrency": concurrency,
        "max_retries": max_retries,
        "queues": queues,
        "pool_min_size": pool_min_size,
        "pool_max_size": pool_max_size,
        "result_ttl": result_ttl,
        "debug": debug,
        "environment": environment,
    }
    for key, value in explicit.items():
        if value is not None:
            settings_kwargs[key] = value
    settings_kwargs.update(extra)

    # Close the prior global app (and its pool) before replacing it. Missing
    # this was the leak: flipping _closed on a live app left the asyncpg
    # pool running, holding Postgres connections until the process died.
    if (
        _global_app is not None
        and _global_app.is_initialized
        and not _global_app.is_closed
    ):
        try:
            await _global_app.close()
        except Exception:
            import logging

            logging.getLogger(__name__).debug(
                "prior global app close() raised during reconfigure",
                exc_info=True,
            )

    _global_app = Soniq(**settings_kwargs)  # type: ignore[arg-type]

    for job_func, job_kwargs in _global_job_registry:
        _global_app.job(**job_kwargs)(job_func)


def job(*decorator_args: Any, **kwargs: Any) -> Any:
    """
    Global job decorator.

    Equivalent to ``app.job()`` but uses the global Soniq instance. Jobs
    are automatically re-registered if the global instance is recreated.

    Celery-style: ``name=`` is optional. When omitted the task name is
    derived as ``f"{module}.{qualname}"``. Pass ``name=`` explicitly for
    cross-service deployments where the name is a wire-protocol
    identifier.

    Supports both ``@soniq.job`` (no parens) and ``@soniq.job(...)``
    (with kwargs).
    """
    # Support `@soniq.job` (no parentheses) by detecting a single
    # positional callable. Keep backward-compatible with the
    # `@soniq.job(name=...)` form.
    if len(decorator_args) == 1 and callable(decorator_args[0]) and not kwargs:
        func = decorator_args[0]
        app = get_global_app()
        wrapped = app.job()(func)
        _global_job_registry.append((func, {}))
        return wrapped

    def decorator(func: Any) -> Any:
        # Register with the global app first so a missing/invalid name=
        # raises before we mutate the global registry. Otherwise a test
        # that exercises the negative path (`@soniq.job()` with no
        # name=) would leave a poison tuple in _global_job_registry
        # that breaks later tests when configure() iterates the list.
        app = get_global_app()
        wrapped = app.job(**kwargs)(func)
        _global_job_registry.append((func, kwargs))
        return wrapped

    return decorator


def periodic(*, cron: Any = None, every: Any = None, **job_kwargs: Any) -> Any:
    """
    Module-level convenience decorator that registers a recurring job
    against the global Soniq instance. Delegates to ``app.periodic(...)``.

    Pass ``cron=`` for a cron expression (a string, or any object whose
    ``__str__`` is a cron expression - e.g. ``daily().at("09:00")`` from
    ``soniq.schedules``) and ``every=`` for an interval (a ``timedelta``
    or seconds as int/float). They are mutually exclusive. Remaining
    kwargs flow to ``@app.job``.

    Examples:
        @soniq.periodic(cron="0 9 * * *")
        async def daily_report():
            ...

        @soniq.periodic(every=timedelta(minutes=10), queue="maintenance")
        async def cleanup():
            ...
    """
    app = get_global_app()
    inner = app.periodic(cron=cron, every=every, **job_kwargs)

    def decorator(func: Any) -> Any:
        wrapped = inner(func)
        # Mirror the registration into the global registry so a later
        # configure() that recreates the global app re-applies it like
        # any other @soniq.job-registered function.
        _global_job_registry.append((func, dict(job_kwargs)))
        return wrapped

    return decorator


async def enqueue(
    target: Any,
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
    """Enqueue a task. Accepts a callable, a string name, or a TaskRef.

    Thin wrapper over ``Soniq.enqueue`` that routes through the global
    app. Callers with their own ``Soniq(...)`` instance should call
    ``app.enqueue(...)`` directly. See ``Soniq.enqueue`` for the full
    contract and the three input shapes.
    """
    app = get_global_app()
    return await app.enqueue(
        target,
        args=args,
        queue=queue,
        priority=priority,
        scheduled_at=scheduled_at,
        unique=unique,
        dedup_key=dedup_key,
        connection=connection,
        **func_kwargs,
    )


async def schedule(
    target: Any,
    *,
    run_at: Optional[datetime] = None,
    run_in: Optional[Union[int, float, timedelta]] = None,
    args: Optional[dict[str, Any]] = None,
    connection: Any = None,
    **kwargs: Any,
) -> str:
    """
    Schedule a task for future execution using the global Soniq instance.

    Use ``run_at`` for absolute datetime or ``run_in`` for relative delay.
    ``target`` and ``args`` (or ``**kwargs`` for the callable form) follow
    the same shape as ``enqueue``.
    """
    if run_at is None and run_in is None:
        raise ValueError("Must specify either run_at (absolute) or run_in (relative)")
    if run_at is not None and run_in is not None:
        raise ValueError("Cannot specify both run_at and run_in")

    if run_in is not None:
        if isinstance(run_in, (int, float)):
            run_at = datetime.now(timezone.utc) + timedelta(seconds=run_in)
        elif isinstance(run_in, timedelta):
            run_at = datetime.now(timezone.utc) + run_in
        else:
            raise ValueError("run_in must be int, float (seconds), or timedelta")

    return await enqueue(
        target,
        args=args,
        connection=connection,
        scheduled_at=run_at,
        **kwargs,
    )


async def run_worker(
    concurrency: int = 4,
    run_once: bool = False,
    queues: Optional[list[str]] = None,
) -> Any:
    """Run a worker using the global Soniq instance."""
    app = get_global_app()
    return await app.run_worker(
        concurrency=concurrency, run_once=run_once, queues=queues
    )


async def setup() -> int:
    """Set up Soniq — create database (if needed) and run migrations."""
    app = get_global_app()
    return await app.setup()


async def _reset() -> None:
    """Delete all jobs and workers. Used in test fixtures."""
    app = get_global_app()
    await app._reset()


async def get_job(job_id: str) -> Optional[dict[str, Any]]:
    """Get information for a specific job."""
    app = get_global_app()
    return await app.get_job(job_id)


async def get_result(job_id: str, *, result_model: Optional[Any] = None) -> Any:
    """Get the return value of a completed job, or None."""
    app = get_global_app()
    return await app.get_result(job_id, result_model=result_model)


async def cancel_job(job_id: str) -> bool:
    """Cancel a queued job."""
    app = get_global_app()
    return await app.cancel_job(job_id)


async def retry_job(job_id: str) -> bool:
    """Retry a failed job."""
    app = get_global_app()
    return await app.retry_job(job_id)


async def delete_job(job_id: str) -> bool:
    """Delete a job from the queue."""
    app = get_global_app()
    return await app.delete_job(job_id)


async def list_jobs(
    queue: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List jobs with optional filtering."""
    app = get_global_app()
    return await app.list_jobs(queue=queue, status=status, limit=limit, offset=offset)


async def get_queue_stats() -> "QueueStats":
    """Whole-instance job state counts. See ``docs/contracts/queue_stats.md``."""
    app = get_global_app()
    return await app.get_queue_stats()
