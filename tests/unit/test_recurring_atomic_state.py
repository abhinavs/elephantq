"""
Tests that recurring job state updates are atomic — in-memory state is only
updated after the database write succeeds.

Written to verify HIGH-01: non-atomic state update in recurring job execution.
"""

import asyncio
import inspect
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
        jobs_update_pos = source.find('.update(')

        assert record_run_pos > 0, "_record_run not found in source"
        assert jobs_update_pos > 0, ".update() not found in source"

        # _record_run (DB write) must come BEFORE in-memory .update()
        assert record_run_pos < jobs_update_pos, (
            "In-memory state update (.update()) happens before _record_run(). "
            "If _record_run() fails, in-memory state will be inconsistent with DB."
        )
