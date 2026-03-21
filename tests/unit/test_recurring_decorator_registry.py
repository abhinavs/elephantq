"""Tests for the @recurring decorator registry (M4 fix)."""

import os

import pytest


@pytest.fixture(autouse=True)
def _enable_scheduling(monkeypatch):
    """Enable scheduling feature flag for all tests in this module."""
    monkeypatch.setenv("ELEPHANTQ_SCHEDULING_ENABLED", "true")
    import elephantq.settings

    elephantq.settings._settings = None
    yield
    elephantq.settings._settings = None


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
