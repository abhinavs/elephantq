"""
run_worker should start the recurring scheduler in continuous mode
and leave it alone in run_once mode.
"""

import pytest

from elephantq.app import ElephantQ
from elephantq.features import recurring


@pytest.mark.asyncio
async def test_run_worker_starts_and_stops_recurring_scheduler(monkeypatch):
    calls = {"ensure": 0, "stop": 0, "worker_run": 0}

    async def fake_ensure():
        calls["ensure"] += 1

    async def fake_stop():
        calls["stop"] += 1

    monkeypatch.setattr(recurring, "_ensure_scheduler_running", fake_ensure)
    monkeypatch.setattr(recurring, "stop_recurring_scheduler", fake_stop)

    app = ElephantQ(database_url="postgresql://user:pass@localhost/testdb")

    async def fake_init():
        return None

    monkeypatch.setattr(app, "_ensure_initialized", fake_init)
    monkeypatch.setattr(app, "_warn_if_pool_too_small", lambda concurrency: None)

    class FakeWorker:
        def __init__(self, **kwargs):
            pass

        async def run(self, **kwargs):
            calls["worker_run"] += 1
            return True

    monkeypatch.setattr("elephantq.worker.Worker", FakeWorker)

    await app.run_worker(concurrency=1)

    assert calls["ensure"] == 1
    assert calls["stop"] == 1
    assert calls["worker_run"] == 1


@pytest.mark.asyncio
async def test_run_worker_run_once_skips_scheduler(monkeypatch):
    calls = {"ensure": 0, "stop": 0}

    async def fake_ensure():
        calls["ensure"] += 1

    async def fake_stop():
        calls["stop"] += 1

    monkeypatch.setattr(recurring, "_ensure_scheduler_running", fake_ensure)
    monkeypatch.setattr(recurring, "stop_recurring_scheduler", fake_stop)

    app = ElephantQ(database_url="postgresql://user:pass@localhost/testdb")

    async def fake_init():
        return None

    monkeypatch.setattr(app, "_ensure_initialized", fake_init)
    monkeypatch.setattr(app, "_warn_if_pool_too_small", lambda concurrency: None)

    class FakeWorker:
        def __init__(self, **kwargs):
            pass

        async def run(self, **kwargs):
            return True

    monkeypatch.setattr("elephantq.worker.Worker", FakeWorker)

    await app.run_worker(concurrency=1, run_once=True)

    assert calls["ensure"] == 0
    assert calls["stop"] == 0


@pytest.mark.asyncio
async def test_run_worker_tolerates_scheduler_start_failure(monkeypatch):
    """If the scheduler can't start, the worker should still run."""
    worker_ran = {"v": False}

    async def failing_ensure():
        raise RuntimeError("scheduling feature disabled")

    async def fake_stop():
        pytest.fail("stop should not be called if start failed")

    monkeypatch.setattr(recurring, "_ensure_scheduler_running", failing_ensure)
    monkeypatch.setattr(recurring, "stop_recurring_scheduler", fake_stop)

    app = ElephantQ(database_url="postgresql://user:pass@localhost/testdb")

    async def fake_init():
        return None

    monkeypatch.setattr(app, "_ensure_initialized", fake_init)
    monkeypatch.setattr(app, "_warn_if_pool_too_small", lambda concurrency: None)

    class FakeWorker:
        def __init__(self, **kwargs):
            pass

        async def run(self, **kwargs):
            worker_ran["v"] = True
            return True

    monkeypatch.setattr("elephantq.worker.Worker", FakeWorker)

    await app.run_worker(concurrency=1)
    assert worker_ran["v"] is True
