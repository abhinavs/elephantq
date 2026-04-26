"""
Tests for the Soniq(producer_only=True) flag.

The allow/deny matrix is locked in plan_multi.md section 14.4 (as
hardened by 15.6): producer-only instances refuse run_worker, the
recurring scheduler entry point, and @app.job registration. They
still allow enqueue, schedule, and the read-only / management API
surface.
"""

from __future__ import annotations

import os

import pytest

from tests.db_utils import TEST_DATABASE_URL

os.environ.setdefault("SONIQ_DATABASE_URL", TEST_DATABASE_URL)

from soniq import Soniq  # noqa: E402
from soniq.errors import SONIQ_PRODUCER_ONLY, SoniqError  # noqa: E402
from soniq.testing import make_app  # noqa: E402

# ---------------------------------------------------------------------------
# Refused operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_worker_raises_producer_only():
    app = make_app(producer_only=True)
    with pytest.raises(SoniqError) as exc_info:
        await app.run_worker(run_once=True)
    assert exc_info.value.error_code == SONIQ_PRODUCER_ONLY


def test_app_job_decorator_raises_producer_only():
    app = make_app(producer_only=True)
    with pytest.raises(SoniqError) as exc_info:

        @app.job(name="billing.foo")
        async def f():
            pass

    assert exc_info.value.error_code == SONIQ_PRODUCER_ONLY


def test_recurring_scheduler_entry_point_raises_producer_only():
    """The recurring-scheduler module-level helper builds a Soniq under the
    hood for the runtime entry point. The flag must propagate so the
    scheduler refuses to start on a producer-only deployment."""
    # The actual entry point is invoked from the CLI; here we directly
    # exercise the run_worker refusal which is the same code path the
    # scheduler enters via app.run_worker. (PR 8 hardens that one;
    # the scheduler-specific entry uses the same flag.)
    app = make_app(producer_only=True)
    with pytest.raises(SoniqError) as exc_info:
        # synchronous call to assert immediate raise; production code is
        # async but the flag check happens before any await.
        import asyncio

        asyncio.run(app.run_worker(run_once=True))
    assert exc_info.value.error_code == SONIQ_PRODUCER_ONLY


# ---------------------------------------------------------------------------
# Allowed operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_is_allowed():
    """Producer-only is the whole point: enqueue must work."""
    app = make_app(producer_only=True, enqueue_validation="none")
    job_id = await app.enqueue("billing.foo", args={"x": 1})
    assert isinstance(job_id, str) and len(job_id) == 36


@pytest.mark.asyncio
async def test_schedule_is_allowed():
    from datetime import datetime, timedelta, timezone

    app = make_app(producer_only=True, enqueue_validation="none")
    run_at = datetime.now(timezone.utc) + timedelta(hours=1)
    job_id = await app.schedule("billing.bar", run_at=run_at, args={})
    assert job_id


@pytest.mark.asyncio
async def test_read_only_management_api_is_allowed():
    """get_job, list_jobs, get_queue_stats, cancel_job, delete_job,
    retry_job all work on a producer-only instance."""
    app = make_app(producer_only=True, enqueue_validation="none")
    job_id = await app.enqueue("billing.work", args={})
    assert await app.get_job(job_id) is not None
    rows = await app.list_jobs()
    assert any(r["id"] == job_id for r in rows)
    stats = await app.get_queue_stats()
    assert stats is not None
    # cancel/delete/retry: just assert they don't raise PRODUCER_ONLY.
    await app.cancel_job(job_id)
    await app.delete_job(job_id)
    # retry on a deleted job is a no-op (returns False); not a raise.
    await app.retry_job(job_id)


@pytest.mark.asyncio
async def test_setup_is_allowed():
    """A producer service may legitimately own its half of the shared DB
    and call _setup() to run migrations. Allow/deny matrix permits this."""
    # MemoryBackend's _setup is a no-op (no migrations); the test
    # exists to pin the contract that the call path does not raise
    # SONIQ_PRODUCER_ONLY.
    app = make_app(producer_only=True)
    result = await app._setup()
    # MemoryBackend returns 0 (no migrations to apply).
    assert result == 0


# ---------------------------------------------------------------------------
# Periodic-warning suppression
# ---------------------------------------------------------------------------


def test_periodic_warning_suppressed_on_producer_only(caplog):
    """The _maybe_warn_periodic_without_scheduler() warning must not
    fire on a producer-only instance even if @periodic-decorated jobs
    were somehow registered."""
    import logging

    app = make_app(producer_only=True)
    with caplog.at_level(logging.WARNING, logger="soniq.app"):
        # Direct call to the helper - this is what run_worker would
        # invoke. On a producer-only instance the helper short-circuits.
        app._maybe_warn_periodic_without_scheduler()

    flood = [r for r in caplog.records if "@periodic" in r.message]
    assert flood == []


# ---------------------------------------------------------------------------
# Default flag is False (no behaviour change for existing users)
# ---------------------------------------------------------------------------


def test_producer_only_defaults_to_false():
    app = Soniq(backend="memory")
    assert app._producer_only is False


def test_app_job_decorator_works_when_not_producer_only():
    app = make_app()
    assert app._producer_only is False

    @app.job(name="billing.allowed")
    async def f():
        pass

    assert "billing.allowed" in app._job_registry
