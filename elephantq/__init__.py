"""
ElephantQ: Async Job Queue for Python (Backed by PostgreSQL)

Simple global usage:

    import elephantq

    @elephantq.job()
    async def my_job(message: str):
        print(f"Processing: {message}")

    await elephantq.enqueue(my_job, message="Hello World")
    await elephantq.run_worker()

Instance-based usage for advanced scenarios:

    app = ElephantQ(database_url="postgresql://localhost/myapp")

    @app.job()
    async def my_job(message: str):
        print(f"Processing: {message}")

    await app.enqueue(my_job, message="Hello World")
    await app.run_worker()
"""

from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Optional, Union

from ._active import _active_app
from .app import ElephantQ
from .job import JobContext, JobStatus, Snooze
from .settings import configure as settings_configure


def _resolve_app() -> ElephantQ:
    """Return the active ElephantQ if one is on the contextvar, else the global.

    Top-level helpers (`elephantq.enqueue`, `elephantq.schedule`) used to
    unconditionally reach for the global app. A caller using an explicit
    `ElephantQ(...)` instance had their calls silently routed to the global
    app's database. Checking the contextvar first honors the caller's
    instance while preserving the zero-config global path.
    """
    active = _active_app.get()
    if isinstance(active, ElephantQ):
        return active
    return _get_global_app()


try:
    __version__ = version("elephantq")
except PackageNotFoundError:
    __version__ = "0.0.0"

# Global ElephantQ instance for convenience API
_global_app: Optional[ElephantQ] = None

# Global job registry to survive instance recreation
_global_job_registry: list[tuple] = []

__all__ = [
    "ElephantQ",
    "job",
    "enqueue",
    "schedule",
    "run_worker",
    "_setup",
    "_reset",
    "configure",
    "get_job_status",
    "cancel_job",
    "retry_job",
    "delete_job",
    "list_jobs",
    "get_queue_stats",
    "periodic",
    "JobContext",
    "JobStatus",
    "Snooze",
    "every",
    "cron",
    "features",
    "DASHBOARD_AVAILABLE",
]

# Dashboard availability flag (for CLI checks)
try:
    from .dashboard.fastapi_app import FASTAPI_AVAILABLE as DASHBOARD_AVAILABLE
except Exception:
    DASHBOARD_AVAILABLE = False


def _get_global_app() -> ElephantQ:
    """
    Get or create the global ElephantQ application instance.

    This enables a global convenience API.
    The global app is created lazily on first use with default settings.
    If the existing global app is closed, a new one is created automatically.
    """
    global _global_app

    if _global_app is None or _global_app._is_closed:
        _global_app = ElephantQ()

        # Re-register all global jobs with the new instance
        for job_func, job_kwargs in _global_job_registry:
            _global_app.job(**job_kwargs)(job_func)

    return _global_app


async def configure(
    *,
    database_url: Optional[str] = None,
    concurrency: Optional[int] = None,
    max_retries: Optional[int] = None,
    queues: Optional[list] = None,
    pool_min_size: Optional[int] = None,
    pool_max_size: Optional[int] = None,
    result_ttl: Optional[int] = None,
    debug: Optional[bool] = None,
    environment: Optional[str] = None,
    **extra,
):
    """
    Configure the global ElephantQ instance.

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
        **extra: Additional ElephantQSettings fields
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

    if settings_kwargs:
        settings_configure(**settings_kwargs)

    # Close the prior global app (and its pool) before replacing it. Missing
    # this was the leak: flipping _closed on a live app left the asyncpg
    # pool running, holding Postgres connections until the process died.
    if (
        _global_app is not None
        and _global_app._is_initialized
        and not _global_app._is_closed
    ):
        try:
            await _global_app.close()
        except Exception:
            import logging

            logging.getLogger(__name__).debug(
                "prior global app close() raised during reconfigure",
                exc_info=True,
            )

    _global_app = ElephantQ(**settings_kwargs)  # type: ignore[arg-type]

    for job_func, job_kwargs in _global_job_registry:
        _global_app.job(**job_kwargs)(job_func)


def job(**kwargs):
    """
    Global job decorator.

    Equivalent to app.job() but uses the global ElephantQ instance.
    Jobs are automatically re-registered if the global instance is recreated.
    """

    def decorator(func):
        _global_job_registry.append((func, kwargs))
        app = _get_global_app()
        return app.job(**kwargs)(func)

    return decorator


def periodic(
    *,
    cron: Optional[str] = None,
    every_seconds: Optional[int] = None,
    every_minutes: Optional[int] = None,
    every_hours: Optional[int] = None,
    **job_kwargs,
):
    """
    Decorator that registers a function as a recurring job.

    Declares both the job and its schedule at definition time.
    The scheduler picks up all @periodic functions automatically.

    Examples:
        @elephantq.periodic(cron="0 9 * * *")
        async def daily_report():
            ...

        @elephantq.periodic(every_minutes=10, queue="maintenance")
        async def cleanup():
            ...
    """
    # Determine schedule type and value
    interval_args = [
        ("seconds", every_seconds),
        ("minutes", every_minutes),
        ("hours", every_hours),
    ]
    interval_set = [(name, val) for name, val in interval_args if val is not None]

    if cron and interval_set:
        raise ValueError("Cannot specify both cron and every_* parameters")
    if not cron and not interval_set:
        raise ValueError(
            "Must specify either cron='...' or one of every_seconds/every_minutes/every_hours"
        )
    if len(interval_set) > 1:
        raise ValueError(
            "Specify only one of every_seconds, every_minutes, every_hours"
        )

    if cron:
        schedule_type = "cron"
        schedule_value: Union[str, int] = cron
    else:
        name, val = interval_set[0]
        schedule_type = "interval"
        multipliers = {"seconds": 1, "minutes": 60, "hours": 3600}
        schedule_value = val * multipliers[name]  # type: ignore[operator]

    def decorator(func):
        # Register as a job first
        wrapped = job(**job_kwargs)(func)

        # Store schedule metadata on the function
        wrapped._elephantq_periodic = {  # type: ignore[attr-defined]
            "type": schedule_type,
            "value": schedule_value,
        }

        return wrapped

    return decorator


async def enqueue(job_func, connection=None, **kwargs):
    """Enqueue a job, honoring an active `ElephantQ` instance if present.

    When called from inside an `ElephantQ(...)` instance method the active
    instance is used; otherwise the global app handles the call.
    """
    app = _resolve_app()
    return await app.enqueue(job_func, connection=connection, **kwargs)


async def schedule(
    job_func,
    *,
    run_at: Optional[datetime] = None,
    run_in: Optional[Union[int, float, timedelta]] = None,
    connection=None,
    **kwargs,
):
    """
    Schedule a job for future execution using the global ElephantQ instance.

    Use `run_at` for absolute datetime or `run_in` for relative delay.
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

    return await enqueue(job_func, connection=connection, scheduled_at=run_at, **kwargs)


async def run_worker(
    concurrency: int = 4,
    run_once: bool = False,
    queues: Optional[list] = None,
):
    """Run a worker using the active or global ElephantQ instance."""
    app = _resolve_app()
    return await app.run_worker(
        concurrency=concurrency, run_once=run_once, queues=queues
    )


async def _setup() -> int:
    """Set up ElephantQ — create database (if needed) and run migrations."""
    app = _resolve_app()
    return await app._setup()  # type: ignore[no-any-return]


async def _reset() -> None:
    """Delete all jobs and workers. Used in test fixtures."""
    app = _resolve_app()
    await app._reset()


async def get_job(job_id: str):
    """Get information for a specific job."""
    app = _resolve_app()
    return await app.get_job_status(job_id)


# Backward-compatible alias
get_job_status = get_job


async def get_result(job_id: str):
    """Get the return value of a completed job, or None."""
    app = _resolve_app()
    return await app.get_result(job_id)


async def cancel_job(job_id: str):
    """Cancel a queued job."""
    app = _resolve_app()
    return await app.cancel_job(job_id)


async def retry_job(job_id: str):
    """Retry a failed job."""
    app = _resolve_app()
    return await app.retry_job(job_id)


async def delete_job(job_id: str):
    """Delete a job from the queue."""
    app = _resolve_app()
    return await app.delete_job(job_id)


async def list_jobs(
    queue: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """List jobs with optional filtering."""
    app = _resolve_app()
    return await app.list_jobs(queue=queue, status=status, limit=limit, offset=offset)


async def get_queue_stats():
    """Get statistics for all queues."""
    app = _resolve_app()
    return await app.get_queue_stats()


# Feature namespace (advanced features live under elephantq.features)
from . import features  # noqa: E402

# Lazy imports for top-level scheduling functions to avoid circular import.
# elephantq.features.recurring imports from elephantq at module level,
# so we can't import from it at the top of this file.
_LAZY_IMPORTS = {
    "every": ("elephantq.features.recurring", "every"),
    "cron": ("elephantq.features.recurring", "cron"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        import importlib

        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module 'elephantq' has no attribute {name!r}")
