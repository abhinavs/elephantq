"""
Tests that recurring.py does not use fire-and-forget create_task() calls.

Written to verify BLOCKER-03: _ensure_loaded() and _schedule_update() must
await their coroutines directly, not fire-and-forget via create_task().
"""

import ast
import inspect

import pytest


class TestNoFireAndForget:
    """Verify no fire-and-forget create_task() calls in recurring.py."""

    def test_no_create_task_in_ensure_loaded(self):
        """_ensure_loaded should not use loop.create_task()."""
        import elephantq.features.recurring as mod

        source = inspect.getsource(mod.EnhancedRecurringManager._ensure_loaded)
        assert "create_task" not in source, (
            "_ensure_loaded() still uses fire-and-forget create_task()"
        )

    def test_no_create_task_in_schedule_update(self):
        """_schedule_update should not use loop.create_task()."""
        import elephantq.features.recurring as mod

        source = inspect.getsource(mod.EnhancedRecurringManager._schedule_update)
        assert "create_task" not in source, (
            "_schedule_update() still uses fire-and-forget create_task()"
        )

    def test_ensure_loaded_is_async(self):
        """_ensure_loaded must be async so callers can await it."""
        import elephantq.features.recurring as mod

        assert inspect.iscoroutinefunction(mod.EnhancedRecurringManager._ensure_loaded), (
            "_ensure_loaded() must be an async method"
        )

    def test_schedule_update_is_async(self):
        """_schedule_update must be async so callers can await it."""
        import elephantq.features.recurring as mod

        assert inspect.iscoroutinefunction(mod.EnhancedRecurringManager._schedule_update), (
            "_schedule_update() must be an async method"
        )

    def test_list_jobs_is_async(self):
        """list_jobs must be async since it calls async _ensure_loaded."""
        import elephantq.features.recurring as mod

        assert inspect.iscoroutinefunction(mod.EnhancedRecurringManager.list_jobs), (
            "list_jobs() must be async"
        )

    def test_get_job_is_async(self):
        """get_job must be async since it calls async _ensure_loaded."""
        import elephantq.features.recurring as mod

        assert inspect.iscoroutinefunction(mod.EnhancedRecurringManager.get_job), (
            "get_job() must be async"
        )
