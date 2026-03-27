"""
Tests for @elephantq.periodic() decorator.

The decorator should register the function as a job AND store
schedule metadata so the scheduler can pick it up automatically.
"""

import elephantq


def test_periodic_with_cron_registers_job():
    """@periodic(cron=...) should register the function as a job."""

    @elephantq.periodic(cron="0 9 * * *")
    async def daily_report():
        pass

    # Should be registered in the global registry
    app = elephantq._get_global_app()
    registry = app.get_job_registry()
    job_name = f"{daily_report.__module__}.{daily_report.__name__}"
    assert registry.get_job(job_name) is not None


def test_periodic_stores_schedule_metadata():
    """@periodic should store _elephantq_periodic metadata on the function."""

    @elephantq.periodic(cron="*/5 * * * *")
    async def cleanup():
        pass

    assert hasattr(cleanup, "_elephantq_periodic")
    meta = cleanup._elephantq_periodic
    assert meta["type"] == "cron"
    assert meta["value"] == "*/5 * * * *"


def test_periodic_with_interval():
    """@periodic(every_minutes=10) should store interval metadata."""

    @elephantq.periodic(every_minutes=10)
    async def health_check():
        pass

    meta = health_check._elephantq_periodic
    assert meta["type"] == "interval"
    assert meta["value"] == 600  # 10 minutes in seconds


def test_periodic_with_queue():
    """@periodic should accept queue parameter."""

    @elephantq.periodic(cron="0 0 * * *", queue="maintenance")
    async def nightly_cleanup():
        pass

    # Job should be registered with the specified queue
    app = elephantq._get_global_app()
    registry = app.get_job_registry()
    job_name = f"{nightly_cleanup.__module__}.{nightly_cleanup.__name__}"
    job_meta = registry.get_job(job_name)
    assert job_meta["queue"] == "maintenance"


def test_periodic_with_every_seconds():
    """@periodic(every_seconds=30) should work."""

    @elephantq.periodic(every_seconds=30)
    async def fast_check():
        pass

    meta = fast_check._elephantq_periodic
    assert meta["type"] == "interval"
    assert meta["value"] == 30


def test_periodic_with_every_hours():
    """@periodic(every_hours=2) should work."""

    @elephantq.periodic(every_hours=2)
    async def slow_task():
        pass

    meta = slow_task._elephantq_periodic
    assert meta["type"] == "interval"
    assert meta["value"] == 7200
