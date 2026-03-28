"""
Tests for scheduling.py uncovered paths.

Covers: in_seconds/minutes/hours/days, at_time parsing, dry_run,
with_priority/in_queue/with_retries/with_tags/with_timeout/if_condition,
BatchScheduler.get_batch_info, schedule() type dispatch, scheduled() decorator,
get/clear job metadata.
"""

import importlib
import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("ELEPHANTQ_SCHEDULING_ENABLED", "true")

import elephantq.settings as settings_module  # noqa: E402
from elephantq.features import scheduling  # noqa: E402


@pytest.fixture(autouse=True)
def _enable_scheduling(monkeypatch):
    monkeypatch.setenv("ELEPHANTQ_SCHEDULING_ENABLED", "true")
    settings_module._settings = None
    importlib.reload(settings_module)
    importlib.reload(scheduling)
    yield


class TestJobScheduleBuilderTimeMethods:
    def test_in_seconds(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task)
        result = builder.in_seconds(120)
        assert result is builder
        assert builder._scheduled_at is not None
        diff = builder._scheduled_at - datetime.now(timezone.utc)
        assert 110 < diff.total_seconds() < 130

    def test_in_minutes(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task).in_minutes(5)
        diff = builder._scheduled_at - datetime.now(timezone.utc)
        assert 290 < diff.total_seconds() < 310

    def test_in_hours(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task).in_hours(2)
        diff = builder._scheduled_at - datetime.now(timezone.utc)
        assert 7100 < diff.total_seconds() < 7300

    def test_in_days(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task).in_days(1)
        diff = builder._scheduled_at - datetime.now(timezone.utc)
        assert 86000 < diff.total_seconds() < 86500


class TestAtTimeParsing:
    def test_at_time_iso_format(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task)
        builder.at_time("2025-12-25T09:00:00+00:00")
        assert builder._scheduled_at.year == 2025
        assert builder._scheduled_at.month == 12

    def test_at_time_hh_mm_format(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task)
        builder.at_time("23:59")
        assert builder._scheduled_at is not None

    def test_at_time_invalid_raises(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task)
        with pytest.raises(ValueError, match="Invalid time format"):
            builder.at_time("not-a-time")


class TestBuilderConfigMethods:
    def test_with_priority(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task)
        result = builder.with_priority(5)
        assert result is builder
        assert builder._priority == 5

    def test_in_queue(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task).in_queue("critical")
        assert builder._queue == "critical"

    def test_with_retries(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task).with_retries(10)
        assert builder._retries == 10

    def test_with_tags(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task).with_tags("a", "b")
        assert builder._tags == ["a", "b"]

    def test_with_timeout(self):
        async def task():
            pass

        builder = scheduling.JobScheduleBuilder(task).with_timeout(30)
        assert builder._timeout == 30

    def test_if_condition(self):
        async def task():
            pass

        cond = lambda: True  # noqa: E731
        builder = scheduling.JobScheduleBuilder(task).if_condition(cond)
        assert builder._condition is cond


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_config_dict(self):
        async def my_task():
            pass

        builder = scheduling.JobScheduleBuilder(my_task)
        result = await builder.in_seconds(60).with_priority(5).dry_run().enqueue(x=1)
        assert isinstance(result, dict)
        assert result["priority"] == 5
        assert result["arguments"] == {"x": 1}
        assert "my_task" in result["job_function"]


class TestScheduleTypeDispatch:
    @pytest.mark.asyncio
    async def test_schedule_unsupported_type_raises(self):
        async def task():
            pass

        with pytest.raises(TypeError, match="Unsupported schedule type"):
            await scheduling.schedule(task, when="invalid")


class TestScheduledDecorator:
    def test_scheduled_decorator_attaches_config(self):
        @scheduling.scheduled("daily", time="09:00")
        async def my_task():
            pass

        assert hasattr(my_task, "_schedule_config")
        assert my_task._schedule_config["type"] == "daily"
        assert my_task._schedule_config["kwargs"]["time"] == "09:00"


class TestJobMetadata:
    def test_get_metadata_returns_none_for_missing(self):
        assert scheduling.get_job_metadata("nonexistent") is None

    def test_clear_metadata_returns_false_for_missing(self):
        assert scheduling.clear_job_metadata("nonexistent") is False

    def test_clear_metadata_returns_true_and_removes(self):
        scheduling._scheduler_metadata["test-id"] = {"tags": []}
        assert scheduling.clear_job_metadata("test-id") is True
        assert scheduling.get_job_metadata("test-id") is None


class TestBatchSchedulerInfo:
    def test_get_batch_info(self):
        async def task_a():
            pass

        async def task_b():
            pass

        batch = scheduling.BatchScheduler("my-batch")
        batch.add_job(task_a).in_seconds(10)
        batch.add(task_b).in_minutes(5)

        info = batch.get_batch_info()
        assert info["batch_name"] == "my-batch"
        assert info["job_count"] == 2
        assert len(info["jobs"]) == 2
