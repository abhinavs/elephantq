"""
Tests for elephantq.features.recurring — the recurring/scheduled job system.

Covers cron validation, feature-flag gating, the @recurring decorator registry,
fire-and-forget safety, atomic state updates, and sync convenience helpers.
"""

import importlib
import inspect
import os
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("croniter")

os.environ.setdefault("ELEPHANTQ_SCHEDULING_ENABLED", "true")


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _reset_settings():
    """Clear cached settings so env-var changes take effect."""
    import elephantq.settings as s

    s._settings = None


@pytest.fixture(autouse=True)
def _enable_scheduling(monkeypatch):
    """Enable the scheduling feature flag for every test in this module."""
    monkeypatch.setenv("ELEPHANTQ_SCHEDULING_ENABLED", "true")
    import elephantq.settings

    elephantq.settings._settings = None
    yield
    elephantq.settings._settings = None


# ---------------------------------------------------------------------------
# Cron feature-flag gating
# ---------------------------------------------------------------------------


class TestCronFeatureFlag:
    """cron() must raise RuntimeError when scheduling is disabled."""

    def test_cron_raises_when_scheduling_disabled(self):
        """cron() should raise RuntimeError when ELEPHANTQ_SCHEDULING_ENABLED=false."""
        for key in list(os.environ.keys()):
            if key.startswith("ELEPHANTQ_"):
                os.environ.pop(key, None)

        os.environ["ELEPHANTQ_SCHEDULING_ENABLED"] = "false"
        _reset_settings()

        from elephantq.features import recurring

        importlib.reload(recurring)

        with pytest.raises(RuntimeError, match="Recurring scheduler"):
            recurring.cron("*/15 * * * *")

    def test_cron_works_when_scheduling_enabled(self):
        """cron() should succeed when ELEPHANTQ_SCHEDULING_ENABLED=true."""
        os.environ["ELEPHANTQ_SCHEDULING_ENABLED"] = "true"
        _reset_settings()

        from elephantq.features import recurring

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
        from elephantq.features.recurring import EnhancedRecurringManager

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
        from elephantq.features.recurring import EnhancedRecurringManager

        mgr = EnhancedRecurringManager()

        async def dummy():
            pass

        # Patch out _persist_job and _ensure_scheduler_running to avoid DB calls
        with patch.object(mgr, "_persist_job", new_callable=AsyncMock):
            with patch(
                "elephantq.features.recurring._ensure_scheduler_running",
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
        from elephantq.features.recurring import _decorated_recurring_jobs, recurring

        initial_count = len(_decorated_recurring_jobs)

        @recurring("30s")
        async def my_recurring_task():
            pass

        assert my_recurring_task in _decorated_recurring_jobs
        assert len(_decorated_recurring_jobs) == initial_count + 1

    def test_decorator_attaches_recurring_config(self):
        from elephantq.features.recurring import recurring

        @recurring("1h", priority="high", queue="urgent")
        async def another_task():
            pass

        assert hasattr(another_task, "_recurring_config")
        config = another_task._recurring_config
        assert "scheduler" in config
        assert "config" in config

    def test_decorated_function_remains_callable(self):
        from elephantq.features.recurring import recurring

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
        import elephantq.features.recurring as mod

        source = inspect.getsource(mod.EnhancedRecurringManager._ensure_loaded)
        assert (
            "create_task" not in source
        ), "_ensure_loaded() still uses fire-and-forget create_task()"

    def test_no_create_task_in_schedule_update(self):
        """_schedule_update should not use loop.create_task()."""
        import elephantq.features.recurring as mod

        source = inspect.getsource(mod.EnhancedRecurringManager._schedule_update)
        assert (
            "create_task" not in source
        ), "_schedule_update() still uses fire-and-forget create_task()"

    def test_ensure_loaded_is_async(self):
        """_ensure_loaded must be async so callers can await it."""
        import elephantq.features.recurring as mod

        assert inspect.iscoroutinefunction(
            mod.EnhancedRecurringManager._ensure_loaded
        ), "_ensure_loaded() must be an async method"

    def test_schedule_update_is_async(self):
        """_schedule_update must be async so callers can await it."""
        import elephantq.features.recurring as mod

        assert inspect.iscoroutinefunction(
            mod.EnhancedRecurringManager._schedule_update
        ), "_schedule_update() must be an async method"

    def test_list_jobs_is_async(self):
        """list_jobs must be async since it calls async _ensure_loaded."""
        import elephantq.features.recurring as mod

        assert inspect.iscoroutinefunction(
            mod.EnhancedRecurringManager.list_jobs
        ), "list_jobs() must be async"

    def test_get_job_is_async(self):
        """get_job must be async since it calls async _ensure_loaded."""
        import elephantq.features.recurring as mod

        assert inspect.iscoroutinefunction(
            mod.EnhancedRecurringManager.get_job
        ), "get_job() must be async"


# ---------------------------------------------------------------------------
# Atomic state updates
# ---------------------------------------------------------------------------


class TestRecurringAtomicState:
    """Verify in-memory state is updated only after DB write succeeds."""

    def test_record_run_called_before_in_memory_update(self):
        """In the execute_recurring_job function, _record_run must be called
        BEFORE in-memory state is updated with last_run/run_count/next_run."""
        import elephantq.features.recurring as mod

        source = inspect.getsource(mod.EnhancedRecurringScheduler._execute_job)

        # Find positions of key operations
        record_run_pos = source.find("_record_run")
        # Find in-memory update: jobs[job_id].update( or jobs[job_id]["
        jobs_update_pos = source.find(".update(")

        assert record_run_pos > 0, "_record_run not found in source"
        assert jobs_update_pos > 0, ".update() not found in source"

        # _record_run (DB write) must come BEFORE in-memory .update()
        assert record_run_pos < jobs_update_pos, (
            "In-memory state update (.update()) happens before _record_run(). "
            "If _record_run() fails, in-memory state will be inconsistent with DB."
        )


# ---------------------------------------------------------------------------
# Sync convenience helpers
# ---------------------------------------------------------------------------


class TestRecurringSyncConvenience:
    """high_priority(), background(), and urgent() must be synchronous."""

    def test_high_priority_is_sync(self):
        from elephantq.features.recurring import high_priority

        assert not inspect.iscoroutinefunction(high_priority)

    def test_background_is_sync(self):
        from elephantq.features.recurring import background

        assert not inspect.iscoroutinefunction(background)

    def test_urgent_is_sync(self):
        from elephantq.features.recurring import urgent

        assert not inspect.iscoroutinefunction(urgent)
