"""
Tests that ElephantQ handles timezones correctly for users.

Users should be able to pass datetimes in any timezone (or naive local time)
and the framework converts to UTC for storage.
"""

from datetime import datetime, timedelta, timezone

import pytest

from elephantq.core.queue import _normalize_scheduled_time


class TestNormalizeScheduledTime:
    """Verify _normalize_scheduled_time handles all timezone scenarios."""

    def test_none_returns_none(self):
        assert _normalize_scheduled_time(None) is None

    def test_timedelta_returns_utc_naive(self):
        result = _normalize_scheduled_time(timedelta(seconds=30))
        assert result.tzinfo is None
        # Should be ~30 seconds from UTC now
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        diff = abs((result - utc_now).total_seconds() - 30)
        assert diff < 2

    def test_int_seconds_returns_utc_naive(self):
        result = _normalize_scheduled_time(60)
        assert result.tzinfo is None
        diff = abs((result - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() - 60)
        assert diff < 2

    def test_utc_aware_datetime_converted(self):
        """UTC-aware datetime should be converted to UTC-naive."""
        dt = datetime(2025, 6, 15, 14, 30, tzinfo=timezone.utc)
        result = _normalize_scheduled_time(dt)
        assert result.tzinfo is None
        assert result == datetime(2025, 6, 15, 14, 30)

    def test_offset_aware_datetime_converted_to_utc(self):
        """Timezone-aware datetime in non-UTC should be converted to UTC."""
        # EST is UTC-5
        est = timezone(timedelta(hours=-5))
        dt = datetime(2025, 6, 15, 14, 30, tzinfo=est)
        result = _normalize_scheduled_time(dt)
        assert result.tzinfo is None
        # 14:30 EST = 19:30 UTC
        assert result == datetime(2025, 6, 15, 19, 30)

    def test_naive_datetime_treated_as_local_time(self):
        """Naive datetimes should be interpreted as local machine time, not UTC."""
        # Create a naive datetime that represents "now" in local time
        local_now = datetime.now()
        result = _normalize_scheduled_time(local_now)
        assert result.tzinfo is None

        # The result should be close to UTC now (since we're converting local → UTC)
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        diff = abs((result - utc_now).total_seconds())
        assert diff < 2, (
            f"Naive datetime not correctly converted to UTC. "
            f"Result: {result}, UTC now: {utc_now}, diff: {diff}s"
        )

    def test_naive_datetime_not_assumed_utc(self):
        """Verify naive datetimes are NOT treated as UTC (the old broken behavior)."""
        import time

        # Get the local UTC offset
        local_offset_seconds = -time.timezone if time.daylight == 0 else -time.altzone
        if local_offset_seconds == 0:
            pytest.skip("Machine is in UTC — cannot test local vs UTC difference")

        # A naive datetime "10:00" in local time
        naive = datetime(2025, 6, 15, 10, 0, 0)
        result = _normalize_scheduled_time(naive)

        # If we're NOT in UTC, the result should differ from the input
        # (old behavior would return the input unchanged)
        assert result != naive, (
            "Naive datetime was passed through unchanged — "
            "it should be converted from local to UTC"
        )


class TestSchedulingBuilderTimezones:
    """Verify JobScheduleBuilder produces timezone-aware UTC datetimes internally."""

    def test_in_seconds_produces_utc_aware(self):
        """in_seconds() should produce a UTC-aware datetime."""
        from unittest.mock import patch
        from elephantq.features.scheduling import JobScheduleBuilder

        async def dummy():
            pass
        dummy._elephantq_name = "test.dummy"

        builder = JobScheduleBuilder(dummy)
        builder.in_seconds(30)
        # Internal _scheduled_at should be timezone-aware (UTC)
        assert builder._scheduled_at.tzinfo is not None

    def test_in_seconds_normalizes_to_correct_utc(self):
        """After normalization, in_seconds() result should be correct UTC."""
        from elephantq.features.scheduling import JobScheduleBuilder

        async def dummy():
            pass
        dummy._elephantq_name = "test.dummy"

        builder = JobScheduleBuilder(dummy)
        builder.in_seconds(60)

        result = _normalize_scheduled_time(builder._scheduled_at)
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        diff = abs((result - utc_now).total_seconds() - 60)
        assert diff < 2
