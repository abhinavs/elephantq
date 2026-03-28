"""
Tests for timeout_processor.py uncovered paths.

Covers: execute_job_with_timeout, toggle_timeout_processing.
"""

import asyncio

import pytest

import elephantq.settings as settings_module


@pytest.fixture(autouse=True)
def _enable_timeouts(monkeypatch):
    monkeypatch.setenv("ELEPHANTQ_TIMEOUTS_ENABLED", "true")
    settings_module._settings = None
    yield
    settings_module._settings = None


class TestExecuteJobWithTimeout:
    @pytest.mark.asyncio
    async def test_job_completes_within_timeout(self):
        from elephantq.features.timeout_processor import execute_job_with_timeout

        async def fast_job():
            return "done"

        result = await execute_job_with_timeout(fast_job, {}, 10)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_job_exceeds_timeout_raises(self):
        from elephantq.features.timeout_processor import (
            JobTimeoutError,
            execute_job_with_timeout,
        )

        async def slow_job():
            await asyncio.sleep(10)

        with pytest.raises(JobTimeoutError):
            await execute_job_with_timeout(slow_job, {}, 0.01)

    @pytest.mark.asyncio
    async def test_job_raises_exception_propagates(self):
        from elephantq.features.timeout_processor import execute_job_with_timeout

        async def failing_job():
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            await execute_job_with_timeout(failing_job, {}, 10)


class TestTimeoutToggle:
    def test_toggle_on_and_off(self):
        from elephantq.features.timeout_processor import toggle_timeout_processing

        # We can't easily verify the global state change without reaching
        # into internal state, but we can verify no exceptions
        toggle_timeout_processing(enabled=True)
        toggle_timeout_processing(enabled=False)

    def test_is_timeout_processing_enabled_returns_bool(self):
        from elephantq.features.timeout_processor import (
            is_timeout_processing_enabled,
            toggle_timeout_processing,
        )

        toggle_timeout_processing(enabled=True)
        assert is_timeout_processing_enabled() is True

        toggle_timeout_processing(enabled=False)
        assert is_timeout_processing_enabled() is False
