"""
Task name validation.

Centralised helper for validating task names against the configured
task_name_pattern. Called at @app.job(name=) registration and at
enqueue() call time so that one rule governs both ends of the wire.
"""

import re
from typing import Optional

from soniq.errors import SONIQ_INVALID_TASK_NAME, SoniqError


def validate_task_name(name: object, pattern: Optional[str] = None) -> str:
    """Return `name` if it matches `pattern`; raise otherwise.

    `pattern` defaults to `SoniqSettings.task_name_pattern`. The helper is
    intentionally cheap: a single `re.fullmatch` per call. No regex caching
    yet because validation is not in a hot path.

    Raises `SoniqError(SONIQ_INVALID_TASK_NAME)` on a non-string `name` or
    on a pattern mismatch. The error includes the offending name and the
    pattern in `context` so dashboards can render them without re-parsing
    the message.
    """
    if not isinstance(name, str):
        raise SoniqError(
            f"task name must be a string, got {type(name).__name__}",
            SONIQ_INVALID_TASK_NAME,
            context={"received_type": type(name).__name__},
        )
    if pattern is None:
        from soniq.settings import get_settings

        pattern = get_settings().task_name_pattern
    if not re.fullmatch(pattern, name):
        raise SoniqError(
            f"task name {name!r} does not match SONIQ_TASK_NAME_PATTERN "
            f"({pattern!r})",
            SONIQ_INVALID_TASK_NAME,
            context={"name": name, "pattern": pattern},
            suggestions=[
                "Use a dotted lowercase identifier (e.g. 'billing.invoices.send.v2').",
                "Override SONIQ_TASK_NAME_PATTERN if your project uses a different convention.",
            ],
        )
    return name
