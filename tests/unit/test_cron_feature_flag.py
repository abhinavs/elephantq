"""
TEST-03: cron() must raise RuntimeError when scheduling is disabled,
matching the pattern used by every(), daily(), weekly(), monthly().

Must fail before FIX-03 and pass after.
"""

import importlib
import os

import pytest


def _reset():
    import elephantq.settings as s

    s._settings = None


def test_cron_raises_when_scheduling_disabled():
    """cron() should raise RuntimeError when ELEPHANTQ_SCHEDULING_ENABLED=false."""
    for key in list(os.environ.keys()):
        if key.startswith("ELEPHANTQ_"):
            os.environ.pop(key, None)

    os.environ["ELEPHANTQ_SCHEDULING_ENABLED"] = "false"
    _reset()

    from elephantq.features import recurring

    importlib.reload(recurring)

    with pytest.raises(RuntimeError, match="Recurring scheduler"):
        recurring.cron("*/15 * * * *")


def test_cron_works_when_scheduling_enabled():
    """cron() should succeed when ELEPHANTQ_SCHEDULING_ENABLED=true."""
    os.environ["ELEPHANTQ_SCHEDULING_ENABLED"] = "true"
    _reset()

    from elephantq.features import recurring

    importlib.reload(recurring)

    scheduler = recurring.cron("*/15 * * * *")
    assert scheduler is not None
