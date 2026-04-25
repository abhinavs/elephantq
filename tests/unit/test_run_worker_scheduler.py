"""
0.0.2 contract: `Soniq.run_worker` does not start or stop the recurring
scheduler. Recurring jobs require a separate `soniq scheduler` process.
If `@periodic` jobs are registered, `run_worker` emits a one-time WARN
on startup unless `SONIQ_SCHEDULER_SUPPRESS_WARNING=1`.
"""

import logging

import pytest

from soniq.app import Soniq


class _FakeWorker:
    def __init__(self, **kwargs):
        self.calls = 0

    async def run(self, **kwargs):
        return True


def _make_app(monkeypatch):
    app = Soniq(database_url="postgresql://user:pass@localhost/testdb")

    async def fake_init():
        return None

    monkeypatch.setattr(app, "_ensure_initialized", fake_init)
    monkeypatch.setattr(app, "_check_pool_sizing", lambda concurrency: None)
    monkeypatch.setattr("soniq.worker.Worker", _FakeWorker)
    return app


@pytest.mark.asyncio
async def test_run_worker_does_not_touch_scheduler(monkeypatch):
    """Neither continuous nor run-once mode should call into the recurring
    scheduler module. The sidecar `soniq scheduler` is the only path that
    starts/stops it."""
    from soniq.features import recurring

    async def fail(*_, **__):
        pytest.fail("run_worker should not touch the recurring scheduler")

    monkeypatch.setattr(recurring, "_ensure_scheduler_running", fail)
    monkeypatch.setattr(recurring, "stop_recurring_scheduler", fail)

    app = _make_app(monkeypatch)
    await app.run_worker(concurrency=1)
    await app.run_worker(concurrency=1, run_once=True)


@pytest.mark.asyncio
async def test_run_worker_warns_when_periodic_jobs_registered(monkeypatch, caplog):
    app = _make_app(monkeypatch)

    @app.job()
    async def regular_job():
        pass

    @app.job()
    async def periodic_job():
        pass

    # Mark periodic_job as a @periodic-decorated function.
    periodic_job._soniq_periodic = {"type": "interval", "value": 60}  # type: ignore[attr-defined]

    caplog.set_level(logging.WARNING, logger="soniq.app")
    await app.run_worker(concurrency=1)

    warns = [r for r in caplog.records if "@periodic job" in r.getMessage()]
    assert len(warns) == 1, "expected exactly one WARN about periodic-without-scheduler"
    assert "soniq scheduler" in warns[0].getMessage()


@pytest.mark.asyncio
async def test_run_worker_warning_suppressible_via_env(monkeypatch, caplog):
    app = _make_app(monkeypatch)

    @app.job()
    async def periodic_job():
        pass

    periodic_job._soniq_periodic = {"type": "interval", "value": 60}  # type: ignore[attr-defined]

    monkeypatch.setenv("SONIQ_SCHEDULER_SUPPRESS_WARNING", "1")
    caplog.set_level(logging.WARNING, logger="soniq.app")
    await app.run_worker(concurrency=1)

    warns = [r for r in caplog.records if "@periodic job" in r.getMessage()]
    assert warns == []


@pytest.mark.asyncio
async def test_run_worker_no_warning_when_no_periodic_jobs(monkeypatch, caplog):
    app = _make_app(monkeypatch)

    @app.job()
    async def regular_job():
        pass

    caplog.set_level(logging.WARNING, logger="soniq.app")
    await app.run_worker(concurrency=1)

    warns = [r for r in caplog.records if "@periodic job" in r.getMessage()]
    assert warns == []


@pytest.mark.asyncio
async def test_run_worker_no_warning_in_run_once_mode(monkeypatch, caplog):
    app = _make_app(monkeypatch)

    @app.job()
    async def periodic_job():
        pass

    periodic_job._soniq_periodic = {"type": "interval", "value": 60}  # type: ignore[attr-defined]

    caplog.set_level(logging.WARNING, logger="soniq.app")
    await app.run_worker(concurrency=1, run_once=True)

    # run_once is ad-hoc / test usage; no scheduler-sidecar warning needed.
    warns = [r for r in caplog.records if "@periodic job" in r.getMessage()]
    assert warns == []
