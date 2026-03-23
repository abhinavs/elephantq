"""
Tests that recurring convenience functions are not async.

Written to verify MED-04: high_priority(), background(), urgent() should be sync.
"""

import inspect
import os

import pytest

os.environ.setdefault("ELEPHANTQ_SCHEDULING_ENABLED", "true")


class TestRecurringSyncConvenience:
    def test_high_priority_is_sync(self):
        from elephantq.features.recurring import high_priority

        assert not inspect.iscoroutinefunction(high_priority)

    def test_background_is_sync(self):
        from elephantq.features.recurring import background

        assert not inspect.iscoroutinefunction(background)

    def test_urgent_is_sync(self):
        from elephantq.features.recurring import urgent

        assert not inspect.iscoroutinefunction(urgent)
