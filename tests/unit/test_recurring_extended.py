"""
Extended tests for recurring.py — convenience functions, cron helper,
get_scheduler_status, recurring decorator parsing.
"""

import os

import pytest

pytest.importorskip("croniter")

os.environ.setdefault("SONIQ_SCHEDULING_ENABLED", "true")


@pytest.fixture(autouse=True)
def _enable_scheduling(monkeypatch):
    monkeypatch.setenv("SONIQ_SCHEDULING_ENABLED", "true")
    import soniq.settings

    soniq.settings._settings = None
    yield
    soniq.settings._settings = None


class TestCronHelper:
    def test_cron_returns_scheduler(self):
        from soniq.features.recurring import FluentRecurringScheduler, cron

        scheduler = cron("*/15 * * * *")
        assert isinstance(scheduler, FluentRecurringScheduler)
        assert scheduler.schedule_type == "cron"
        assert scheduler.schedule_value == "*/15 * * * *"


class TestHighPriorityConvenience:
    def test_high_priority_function(self):
        from soniq.features.recurring import high_priority

        scheduler = high_priority()
        assert scheduler._priority == 10
        assert scheduler._queue == "urgent"

    def test_background_function(self):
        from soniq.features.recurring import background

        scheduler = background()
        assert scheduler._priority == 100
        assert scheduler._queue == "background"

    def test_urgent_function(self):
        from soniq.features.recurring import urgent

        scheduler = urgent()
        assert scheduler._priority == 1
        assert scheduler._queue == "urgent"


class TestGetSchedulerStatus:
    def test_returns_dict(self):
        from soniq.features.recurring import get_scheduler_status

        status = get_scheduler_status()
        assert isinstance(status, dict)
        assert "running" in status
        assert "total_jobs" in status
        assert "active_jobs" in status


class TestRecurringDecoratorParsing:
    def test_parses_seconds_interval(self):
        from soniq.features.recurring import recurring

        @recurring("30s")
        async def my_task():
            pass

        config = my_task._recurring_config
        assert config["scheduler"].schedule_type == "interval"
        assert config["scheduler"].schedule_value == 30

    def test_parses_minutes_interval(self):
        from soniq.features.recurring import recurring

        @recurring("5m")
        async def my_task():
            pass

        config = my_task._recurring_config
        assert config["scheduler"].schedule_value == 300

    def test_parses_hours_interval(self):
        from soniq.features.recurring import recurring

        @recurring("2h")
        async def my_task():
            pass

        config = my_task._recurring_config
        assert config["scheduler"].schedule_value == 7200

    def test_parses_days_interval(self):
        from soniq.features.recurring import recurring

        @recurring("1d")
        async def my_task():
            pass

        config = my_task._recurring_config
        assert config["scheduler"].schedule_value == 86400

    def test_parses_cron_expression(self):
        from soniq.features.recurring import recurring

        @recurring("0 9 * * 1-5")
        async def weekday_report():
            pass

        config = weekday_report._recurring_config
        assert config["scheduler"].schedule_type == "cron"
        assert config["scheduler"].schedule_value == "0 9 * * 1-5"

    def test_applies_priority_config(self):
        from soniq.features.recurring import recurring

        @recurring("1h", priority="high")
        async def my_task():
            pass

        config = my_task._recurring_config
        assert config["scheduler"]._priority == 10

    def test_applies_queue_config(self):
        from soniq.features.recurring import recurring

        @recurring("1h", queue="emails")
        async def my_task():
            pass

        config = my_task._recurring_config
        assert config["scheduler"]._queue == "emails"

    def test_applies_max_attempts_config(self):
        from soniq.features.recurring import recurring

        @recurring("1h", max_attempts=5)
        async def my_task():
            pass

        config = my_task._recurring_config
        assert config["scheduler"]._max_attempts == 5
