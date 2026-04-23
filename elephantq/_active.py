"""
Active-ElephantQ tracking for feature helpers.

Feature modules (`features/recurring.py`, `features/scheduling.py`, and the
module-level `elephantq.enqueue` / `elephantq.schedule` helpers) historically
reached for the global ElephantQ app unconditionally. That silently crossed
database boundaries for users who created their own `ElephantQ(...)` instance
and called those helpers from inside one of its async methods: the helper
would write to the global app's Postgres, not the caller's.

This module exposes a `ContextVar` that instance methods populate while they
run, so downstream helpers can ask "who's in charge right now?" without the
caller having to thread an app reference through every API.

Kept out of `elephantq/app.py` to avoid a circular import: `_active_app` is
typed as `Optional[Any]` here rather than `Optional[ElephantQ]`.
"""

from contextvars import ContextVar
from typing import Any, Optional

_active_app: ContextVar[Optional[Any]] = ContextVar(
    "elephantq_active_app", default=None
)


def get_active_app() -> Optional[Any]:
    """Return the `ElephantQ` instance currently driving a call, if any."""
    return _active_app.get()
