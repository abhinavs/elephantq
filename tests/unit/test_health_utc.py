"""
Tests that health.py uses UTC timestamps consistently.

Written to verify MED-02: datetime.now() without timezone replaced with UTC.
"""

import inspect

import pytest


class TestHealthUTC:
    """Verify health.py does not use naive datetime.now()."""

    def test_no_naive_datetime_now(self):
        """health.py should not use datetime.now() without timezone."""
        import elephantq.health as mod

        source = inspect.getsource(mod)
        # Count occurrences of datetime.now() without timezone
        lines = source.split("\n")
        violations = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if "datetime.now()" in stripped and "timezone" not in stripped:
                violations.append(f"Line {i}: {stripped}")

        assert not violations, (
            f"health.py uses datetime.now() without timezone:\n"
            + "\n".join(violations)
        )
