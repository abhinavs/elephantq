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

from datetime import datetime, timedelta
from typing import Optional, Union

from .client import ElephantQ
from .settings import configure as settings_configure

__version__ = "0.1.0"

# Global ElephantQ instance for convenience API
_global_app: ElephantQ = None

# Global job registry to survive instance recreation
_global_job_registry = []

__all__ = [
    "ElephantQ",
    "job",
    "enqueue",
    "schedule",
    "run_worker",
    "setup",
    "configure",
    "get_job_status",
    "cancel_job",
    "retry_job",
    "delete_job",
    "list_jobs",
    "get_queue_stats",
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
    global _global_app, _global_job_registry

    if _global_app is None or _global_app.is_closed:
        _global_app = ElephantQ()

        # Re-register all global jobs with the new instance
        for job_func, job_kwargs in _global_job_registry:
            _global_app.job(**job_kwargs)(job_func)

    return _global_app


def configure(**kwargs):
    """
    Configure ElephantQ with enhanced validation and better developer experience.

    Args:
        **kwargs: Configuration options

    Examples:
        import elephantq

        elephantq.configure(
            database_url="postgresql://localhost/myapp",
            worker_concurrency=8,
            pool_size=30,
        )

        @elephantq.job()
        async def my_job():
            pass
    """
    global _global_app, _global_job_registry

    settings_kwargs = {}
    enhanced_to_elephantq = {
        "worker_concurrency": "default_concurrency",
        "max_retries": "default_max_retries",
        "default_queue": "default_queues",
        "pool_size": "db_pool_max_size",
    }

    for key, value in kwargs.items():
        elephantq_key = enhanced_to_elephantq.get(key, key)
        if key == "default_queue":
            settings_kwargs[elephantq_key] = [value] if isinstance(value, str) else value
        else:
            settings_kwargs[elephantq_key] = value

    if settings_kwargs:
        settings_configure(**settings_kwargs)

    # Close old global app if it exists and is initialized
    if _global_app is not None and _global_app.is_initialized:
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.create_task(_global_app.close())
        except RuntimeError:
            pass

    _global_app = ElephantQ(**settings_kwargs)

    for job_func, job_kwargs in _global_job_registry:
        _global_app.job(**job_kwargs)(job_func)


def job(**kwargs):
    """
    Global job decorator.

    Equivalent to app.job() but uses the global ElephantQ instance.
    Jobs are automatically re-registered if the global instance is recreated.
    """
    global _global_job_registry

    def decorator(func):
        _global_job_registry.append((func, kwargs))
        app = _get_global_app()
        return app.job(**kwargs)(func)

    return decorator


async def enqueue(job_func, **kwargs):
    """Enqueue a job using the global ElephantQ instance."""
    app = _get_global_app()
    return await app.enqueue(job_func, **kwargs)


async def schedule(
    job_func,
    *,
    run_at: Optional[datetime] = None,
    run_in: Optional[Union[int, float, timedelta]] = None,
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
            run_at = datetime.now() + timedelta(seconds=run_in)
        elif isinstance(run_in, timedelta):
            run_at = datetime.now() + run_in
        else:
            raise ValueError("run_in must be int, float (seconds), or timedelta")

    return await enqueue(job_func, scheduled_at=run_at, **kwargs)


async def run_worker(
    concurrency: int = 4,
    run_once: bool = False,
    queues: list = None,
):
    """Run a worker using the global ElephantQ instance."""
    app = _get_global_app()
    return await app.run_worker(
        concurrency=concurrency, run_once=run_once, queues=queues
    )


async def setup() -> int:
    """Create/upgrade ElephantQ tables via migrations (global API)."""
    from elephantq.db.migrations import run_migrations

    return await run_migrations()


async def get_job_status(job_id: str):
    """Get status information for a specific job."""
    app = _get_global_app()
    return await app.get_job_status(job_id)


async def cancel_job(job_id: str):
    """Cancel a queued job."""
    app = _get_global_app()
    return await app.cancel_job(job_id)


async def retry_job(job_id: str):
    """Retry a failed job."""
    app = _get_global_app()
    return await app.retry_job(job_id)


async def delete_job(job_id: str):
    """Delete a job from the queue."""
    app = _get_global_app()
    return await app.delete_job(job_id)


async def list_jobs(
    queue: str = None, status: str = None, limit: int = 100, offset: int = 0
):
    """List jobs with optional filtering."""
    app = _get_global_app()
    return await app.list_jobs(queue=queue, status=status, limit=limit, offset=offset)


async def get_queue_stats():
    """Get statistics for all queues."""
    app = _get_global_app()
    return await app.get_queue_stats()


# Feature namespace (advanced features live under elephantq.features)
from . import features  # noqa: E402
