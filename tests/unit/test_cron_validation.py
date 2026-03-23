"""
Tests that invalid cron expressions are rejected at creation time.

Written to verify LOW-02.
"""

import os

import pytest

os.environ.setdefault("ELEPHANTQ_SCHEDULING_ENABLED", "true")


class TestCronValidation:
    @pytest.mark.asyncio
    async def test_invalid_cron_raises_valueerror(self):
        from unittest.mock import AsyncMock, patch

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
        from unittest.mock import AsyncMock, patch

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
