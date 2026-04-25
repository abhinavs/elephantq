"""
When `_record_run` fails *after* a recurring job has been claimed and
enqueued, the failure used to be swallowed with `except Exception: pass`.
That kept `last_run`, `run_count`, and `last_job_id` out of sync with the
jobs actually dispatched, and operators had no indication anything went
wrong. The claim already succeeded, so we can't retry, but we must log.
"""

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from soniq.features.recurring import (
    EnhancedRecurringManager,
    EnhancedRecurringScheduler,
)


@pytest.mark.asyncio
async def test_record_run_failure_is_logged(monkeypatch, caplog):
    """Post-claim `_record_run` failure emits an error log, doesn't silently pass."""
    from soniq.features import recurring

    # Swap the module-level manager/scheduler with clean instances so we can
    # control their internals for this test without touching global state.
    manager = EnhancedRecurringManager()
    scheduler = EnhancedRecurringScheduler()
    monkeypatch.setattr(recurring, "_enhanced_manager", manager)
    monkeypatch.setattr(recurring, "_enhanced_scheduler", scheduler)

    # Register a fake recurring job in the manager.
    async def dummy_job():
        return "ok"

    job_record = {
        "id": "00000000-0000-0000-0000-000000000abc",
        "job_name": "test.dummy_job",
        "job_func": dummy_job,
        "schedule_type": "interval",
        "schedule_value": 60,
        "priority": 100,
        "queue": "default",
        "max_attempts": 3,
        "job_kwargs": {},
        "next_run": datetime.now(timezone.utc),
        "run_count": 0,
        "status": "active",
        "last_job_id": None,
    }
    manager.jobs[job_record["id"]] = job_record

    # Claim succeeds; enqueue succeeds; but the post-claim record_run fails.
    manager._claim_and_advance_run = AsyncMock(return_value=True)
    manager._record_run = AsyncMock(side_effect=RuntimeError("db unavailable"))

    async def fake_enqueue(func, **kwargs):
        return "enqueued-job-xyz"

    monkeypatch.setattr(recurring, "enqueue", fake_enqueue)

    with caplog.at_level(logging.ERROR, logger="soniq.features.recurring"):
        await scheduler._execute_job(
            job_record["id"], job_record, datetime.now(timezone.utc)
        )

    # Enqueue still happened — claim already succeeded.
    manager._record_run.assert_awaited_once()

    # But the failure was logged, not swallowed.
    assert any(
        "db unavailable" in record.getMessage()
        or "record" in record.getMessage().lower()
        for record in caplog.records
    ), f"expected error log mentioning the failure, got: {[r.getMessage() for r in caplog.records]}"
