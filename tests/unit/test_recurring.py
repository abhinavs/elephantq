"""
Tests for soniq.features.recurring — the recurring/scheduled job system.

Covers cron validation, feature-flag gating, the @recurring decorator registry,
fire-and-forget safety, atomic state updates, and sync convenience helpers.
"""

import importlib
import inspect
import os
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("croniter")

os.environ.setdefault("SONIQ_SCHEDULING_ENABLED", "true")


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _reset_settings():
    """Clear cached settings so env-var changes take effect."""
    import soniq.settings as s

    s._settings = None


@pytest.fixture(autouse=True)
def _enable_scheduling(monkeypatch):
    """Enable the scheduling feature flag for every test in this module."""
    monkeypatch.setenv("SONIQ_SCHEDULING_ENABLED", "true")
    import soniq.settings

    soniq.settings._settings = None
    yield
    soniq.settings._settings = None


# ---------------------------------------------------------------------------
# Cron feature-flag gating
# ---------------------------------------------------------------------------


class TestCronFeatureFlag:
    """cron() must raise RuntimeError when scheduling is disabled."""

    def test_cron_raises_when_scheduling_disabled(self):
        """cron() should raise RuntimeError when SONIQ_SCHEDULING_ENABLED=false."""
        for key in list(os.environ.keys()):
            if key.startswith("SONIQ_"):
                os.environ.pop(key, None)

        os.environ["SONIQ_SCHEDULING_ENABLED"] = "false"
        _reset_settings()

        from soniq.features import recurring

        importlib.reload(recurring)

        with pytest.raises(RuntimeError, match="Recurring scheduler"):
            recurring.cron("*/15 * * * *")

    def test_cron_works_when_scheduling_enabled(self):
        """cron() should succeed when SONIQ_SCHEDULING_ENABLED=true."""
        os.environ["SONIQ_SCHEDULING_ENABLED"] = "true"
        _reset_settings()

        from soniq.features import recurring

        importlib.reload(recurring)

        scheduler = recurring.cron("*/15 * * * *")
        assert scheduler is not None


# ---------------------------------------------------------------------------
# Cron expression validation
# ---------------------------------------------------------------------------


class TestCronValidation:
    """Invalid cron expressions must be rejected at creation time."""

    @pytest.mark.asyncio
    async def test_invalid_cron_raises_valueerror(self):
        from soniq.features.recurring import EnhancedRecurringManager

        mgr = EnhancedRecurringManager()

        async def dummy():
            pass

        with pytest.raises(ValueError, match="Invalid cron expression"):
            await mgr.add_recurring_job(
                dummy,
                schedule_type="cron",
                schedule_value="invalid cron expression",
            )

    @pytest.mark.asyncio
    async def test_valid_cron_does_not_raise(self):
        from soniq.features.recurring import EnhancedRecurringManager

        mgr = EnhancedRecurringManager()

        async def dummy():
            pass

        # Patch out _persist_job and _ensure_scheduler_running to avoid DB calls
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            with patch(
                "soniq.features.recurring._ensure_scheduler_running",
                new_callable=AsyncMock,
            ):
                job_id = await mgr.add_recurring_job(
                    dummy,
                    schedule_type="cron",
                    schedule_value="*/5 * * * *",
                )
                assert job_id is not None


# ---------------------------------------------------------------------------
# @recurring decorator registry
# ---------------------------------------------------------------------------


class TestRecurringDecoratorRegistry:
    """Verify that @recurring registers functions in _decorated_recurring_jobs."""

    def test_decorator_registers_function(self):
        from soniq.features.recurring import _decorated_recurring_jobs, recurring

        initial_count = len(_decorated_recurring_jobs)

        @recurring("30s")
        async def my_recurring_task():
            pass

        assert my_recurring_task in _decorated_recurring_jobs
        assert len(_decorated_recurring_jobs) == initial_count + 1

    def test_decorator_attaches_recurring_config(self):
        from soniq.features.recurring import recurring

        @recurring("1h", priority="high", queue="urgent")
        async def another_task():
            pass

        assert hasattr(another_task, "_recurring_config")
        config = another_task._recurring_config
        assert "scheduler" in config
        assert "config" in config

    def test_decorated_function_remains_callable(self):
        from soniq.features.recurring import recurring

        @recurring("5m")
        def sync_task():
            return 42

        assert sync_task() == 42


# ---------------------------------------------------------------------------
# No fire-and-forget create_task() calls
# ---------------------------------------------------------------------------


class TestNoFireAndForget:
    """Verify no fire-and-forget create_task() calls in recurring.py."""

    def test_no_create_task_in_ensure_loaded(self):
        """_ensure_loaded should not use loop.create_task()."""
        import soniq.features.recurring as mod

        source = inspect.getsource(mod.EnhancedRecurringManager._ensure_loaded)
        assert (
            "create_task" not in source
        ), "_ensure_loaded() still uses fire-and-forget create_task()"

    def test_no_create_task_in_schedule_update(self):
        """_schedule_update should not use loop.create_task()."""
        import soniq.features.recurring as mod

        source = inspect.getsource(mod.EnhancedRecurringManager._schedule_update)
        assert (
            "create_task" not in source
        ), "_schedule_update() still uses fire-and-forget create_task()"

    def test_ensure_loaded_is_async(self):
        """_ensure_loaded must be async so callers can await it."""
        import soniq.features.recurring as mod

        assert inspect.iscoroutinefunction(
            mod.EnhancedRecurringManager._ensure_loaded
        ), "_ensure_loaded() must be an async method"

    def test_schedule_update_is_async(self):
        """_schedule_update must be async so callers can await it."""
        import soniq.features.recurring as mod

        assert inspect.iscoroutinefunction(
            mod.EnhancedRecurringManager._schedule_update
        ), "_schedule_update() must be an async method"

    def test_list_jobs_is_async(self):
        """list_jobs must be async since it calls async _ensure_loaded."""
        import soniq.features.recurring as mod

        assert inspect.iscoroutinefunction(
            mod.EnhancedRecurringManager.list_jobs
        ), "list_jobs() must be async"

    def test_get_job_is_async(self):
        """get_job must be async since it calls async _ensure_loaded."""
        import soniq.features.recurring as mod

        assert inspect.iscoroutinefunction(
            mod.EnhancedRecurringManager.get_job
        ), "get_job() must be async"


# ---------------------------------------------------------------------------
# Atomic state updates
# ---------------------------------------------------------------------------


class TestRecurringAtomicState:
    """In-memory state must only be updated after the DB transaction commits."""

    def test_in_memory_update_is_outside_transaction_block(self):
        """`_execute_job` claims, enqueues, and records inside one
        `conn.transaction()`. The in-memory `jobs[job_id].update(...)` must
        sit *outside* that block: if the transaction rolls back (failed
        enqueue, lost claim race), the in-memory cache should not advance."""
        import soniq.features.recurring as mod

        source = inspect.getsource(mod.EnhancedRecurringScheduler._execute_job)

        # The transaction block exits when async-with returns. The in-memory
        # update must come after that. We approximate "after the transaction
        # block" as: position of `.update(` minus position of last
        # `conn.transaction()` is positive AND no other update sits inside.
        update_pos = source.rfind(".update(")
        txn_pos = source.rfind("conn.transaction()")

        assert update_pos > 0, ".update() not found in _execute_job source"
        assert txn_pos > 0, "conn.transaction() not found in _execute_job source"
        assert update_pos > txn_pos, (
            "In-memory `.update()` should appear after the transaction block; "
            "if a failed enqueue or lost claim rolls back the DB, the cache "
            "must not have already advanced."
        )


# ---------------------------------------------------------------------------
# Sync convenience helpers
# ---------------------------------------------------------------------------


class TestRecurringSyncConvenience:
    """high_priority(), background(), and urgent() must be synchronous."""

    def test_high_priority_is_sync(self):
        from soniq.features.recurring import high_priority

        assert not inspect.iscoroutinefunction(high_priority)

    def test_background_is_sync(self):
        from soniq.features.recurring import background

        assert not inspect.iscoroutinefunction(background)

    def test_urgent_is_sync(self):
        from soniq.features.recurring import urgent

        assert not inspect.iscoroutinefunction(urgent)
