"""
Tests for recurring.py uncovered paths.

Covers: Priority enum, FluentRecurringScheduler (priority, queue, max_attempts,
high_priority, background, urgent), TimeIntervalBuilder,
DailyScheduler, WeeklyScheduler, MonthlyScheduler, every/daily/weekly/monthly/hourly.
"""

import os

import pytest

pytest.importorskip("croniter")

os.environ.setdefault("ELEPHANTQ_SCHEDULING_ENABLED", "true")


@pytest.fixture(autouse=True)
def _enable_scheduling(monkeypatch):
    monkeypatch.setenv("ELEPHANTQ_SCHEDULING_ENABLED", "true")
    import elephantq.settings

    elephantq.settings._settings = None
    yield
    elephantq.settings._settings = None


class TestPriorityEnum:
    def test_priority_values(self):
        from elephantq.features.recurring import Priority

        assert Priority.URGENT.value == 1
        assert Priority.HIGH.value == 10
        assert Priority.NORMAL.value == 50
        assert Priority.LOW.value == 75
        assert Priority.BACKGROUND.value == 100


class TestFluentRecurringScheduler:
    def test_priority_with_enum(self):
        from elephantq.features.recurring import FluentRecurringScheduler, Priority

        s = FluentRecurringScheduler("interval", 60)
        result = s.priority(Priority.HIGH)
        assert result is s
        assert s._priority == 10

    def test_priority_with_int(self):
        from elephantq.features.recurring import FluentRecurringScheduler

        s = FluentRecurringScheduler("interval", 60)
        s.priority(42)
        assert s._priority == 42

    def test_priority_with_string(self):
        from elephantq.features.recurring import FluentRecurringScheduler

        s = FluentRecurringScheduler("interval", 60)
        s.priority("urgent")
        assert s._priority == 1

    def test_priority_with_unknown_string_defaults_to_normal(self):
        from elephantq.features.recurring import FluentRecurringScheduler

        s = FluentRecurringScheduler("interval", 60)
        s.priority("unknown_level")
        assert s._priority == 50

    def test_queue_sets_queue_name(self):
        from elephantq.features.recurring import FluentRecurringScheduler

        s = FluentRecurringScheduler("interval", 60)
        result = s.queue("emails")
        assert result is s
        assert s._queue == "emails"

    def test_max_attempts(self):
        from elephantq.features.recurring import FluentRecurringScheduler

        s = FluentRecurringScheduler("interval", 60)
        result = s.max_attempts(5)
        assert result is s
        assert s._max_attempts == 5

    def test_high_priority_sets_priority_and_queue(self):
        from elephantq.features.recurring import FluentRecurringScheduler

        s = FluentRecurringScheduler("interval", 60)
        result = s.high_priority()
        assert result is s
        assert s._priority == 10
        assert s._queue == "urgent"

    def test_background_sets_priority_and_queue(self):
        from elephantq.features.recurring import FluentRecurringScheduler

        s = FluentRecurringScheduler("interval", 60)
        result = s.background()
        assert result is s
        assert s._priority == 100
        assert s._queue == "background"

    def test_urgent_sets_priority_and_queue(self):
        from elephantq.features.recurring import FluentRecurringScheduler

        s = FluentRecurringScheduler("interval", 60)
        result = s.urgent()
        assert result is s
        assert s._priority == 1
        assert s._queue == "urgent"


class TestTimeIntervalBuilder:
    def test_seconds(self):
        from elephantq.features.recurring import TimeIntervalBuilder

        builder = TimeIntervalBuilder(30)
        scheduler = builder.seconds()
        assert scheduler.schedule_type == "interval"
        assert scheduler.schedule_value == 30

    def test_minutes(self):
        from elephantq.features.recurring import TimeIntervalBuilder

        builder = TimeIntervalBuilder(5)
        scheduler = builder.minutes()
        assert scheduler.schedule_value == 300

    def test_hours(self):
        from elephantq.features.recurring import TimeIntervalBuilder

        builder = TimeIntervalBuilder(2)
        scheduler = builder.hours()
        assert scheduler.schedule_value == 7200

    def test_days(self):
        from elephantq.features.recurring import TimeIntervalBuilder

        builder = TimeIntervalBuilder(1)
        scheduler = builder.days()
        assert scheduler.schedule_value == 86400


class TestEveryFactory:
    def test_every_returns_time_interval_builder(self):
        from elephantq.features.recurring import TimeIntervalBuilder, every

        result = every(5)
        assert isinstance(result, TimeIntervalBuilder)
        assert result.amount == 5

    def test_every_chained_with_minutes(self):
        from elephantq.features.recurring import FluentRecurringScheduler, every

        scheduler = every(10).minutes()
        assert isinstance(scheduler, FluentRecurringScheduler)
        assert scheduler.schedule_value == 600

    def test_every_chained_with_hours(self):
        from elephantq.features.recurring import every

        scheduler = every(2).hours()
        assert scheduler.schedule_value == 7200

    def test_every_chained_with_seconds(self):
        from elephantq.features.recurring import every

        scheduler = every(30).seconds()
        assert scheduler.schedule_value == 30

    def test_every_chained_with_days(self):
        from elephantq.features.recurring import every

        scheduler = every(1).days()
        assert scheduler.schedule_value == 86400


class TestDailyWeeklyMonthly:
    def test_daily_returns_daily_scheduler(self):
        from elephantq.features.recurring import daily

        scheduler = daily()
        assert scheduler.schedule_type == "cron"

    def test_weekly_returns_weekly_scheduler(self):
        from elephantq.features.recurring import weekly

        scheduler = weekly()
        assert scheduler.schedule_type == "cron"

    def test_monthly_returns_monthly_scheduler(self):
        from elephantq.features.recurring import monthly

        scheduler = monthly()
        assert scheduler.schedule_type == "cron"

    def test_hourly_returns_scheduler(self):
        from elephantq.features.recurring import hourly

        scheduler = hourly()
        assert scheduler.schedule_type == "interval"
        assert scheduler.schedule_value == 3600


class TestDailyScheduler:
    def test_daily_at_sets_time(self):
        from elephantq.features.recurring import daily

        scheduler = daily().at("09:30")
        assert "30 9" in scheduler.schedule_value

    def test_daily_at_invalid_raises(self):
        from elephantq.features.recurring import daily

        with pytest.raises(ValueError):
            daily().at("not-a-time")


class TestWeeklyScheduler:
    def test_weekly_on_sets_day(self):
        from elephantq.features.recurring import weekly

        scheduler = weekly().on("monday")
        assert scheduler.schedule_type == "cron"

    def test_weekly_on_unknown_day_defaults_to_sunday(self):
        from elephantq.features.recurring import weekly

        scheduler = weekly().on("not-a-day")
        # Invalid day names default to Sunday (0)
        assert scheduler._day == 0

    def test_weekly_at_sets_time(self):
        from elephantq.features.recurring import weekly

        scheduler = weekly().on("friday").at("14:00")
        assert "0 14" in scheduler.schedule_value


class TestMonthlyScheduler:
    def test_monthly_on_day_sets_day(self):
        from elephantq.features.recurring import monthly

        scheduler = monthly().on_day(15)
        assert "15" in scheduler.schedule_value

    def test_monthly_on_day_invalid_raises(self):
        from elephantq.features.recurring import monthly

        with pytest.raises(ValueError):
            monthly().on_day(32)

    def test_monthly_at_sets_time(self):
        from elephantq.features.recurring import monthly

        scheduler = monthly().on_day(1).at("08:00")
        assert "0 8" in scheduler.schedule_value
