"""
Tests for @soniq.periodic() decorator.

The decorator should register the function as a job AND store
schedule metadata so the scheduler can pick it up automatically.
"""

import soniq


def test_periodic_with_cron_registers_job():
    """@periodic(cron=...) should register the function as a job."""

    @soniq.periodic(cron="0 9 * * *")
    async def daily_report():
        pass

    # Should be registered in the global registry under the derived name
    # (Celery-style: f"{module}.{qualname}").
    app = soniq._get_global_app()
    registry = app._get_job_registry()
    derived = f"{daily_report.__module__}.{daily_report.__name__}"
    assert registry.get_job(derived) is not None


def test_periodic_stores_schedule_metadata():
    """@periodic should store _soniq_periodic metadata on the function."""

    @soniq.periodic(cron="*/5 * * * *")
    async def cleanup():
        pass

    assert hasattr(cleanup, "_soniq_periodic")
    meta = cleanup._soniq_periodic
    assert meta["type"] == "cron"
    assert meta["value"] == "*/5 * * * *"


def test_periodic_with_interval():
    """@periodic(every_minutes=10) should store interval metadata."""

    @soniq.periodic(every_minutes=10)
    async def health_check():
        pass

    meta = health_check._soniq_periodic
    assert meta["type"] == "interval"
    assert meta["value"] == 600  # 10 minutes in seconds


def test_periodic_with_queue():
    """@periodic should accept queue parameter."""

    @soniq.periodic(cron="0 0 * * *", queue="maintenance")
    async def nightly_cleanup():
        pass

    # Job should be registered with the specified queue
    app = soniq._get_global_app()
    registry = app._get_job_registry()
    derived = f"{nightly_cleanup.__module__}.{nightly_cleanup.__name__}"
    job_meta = registry.get_job(derived)
    assert job_meta["queue"] == "maintenance"


def test_periodic_with_every_seconds():
    """@periodic(every_seconds=30) should work."""

    @soniq.periodic(every_seconds=30)
    async def fast_check():
        pass

    meta = fast_check._soniq_periodic
    assert meta["type"] == "interval"
    assert meta["value"] == 30


def test_periodic_with_every_hours():
    """@periodic(every_hours=2) should work."""

    @soniq.periodic(every_hours=2)
    async def slow_task():
        pass

    meta = slow_task._soniq_periodic
    assert meta["type"] == "interval"
    assert meta["value"] == 7200
