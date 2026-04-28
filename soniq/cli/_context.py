"""
Unified CLI app resolution + lifecycle.

Every subcommand that talks to a Soniq instance goes through ``cli_app``:

    async with cli_app(args) as app:
        ...

``cli_app`` resolves an app (precedence: ``--database-url`` > env
``SONIQ_DATABASE_URL`` > global singleton), logs which source was used,
and closes the instance on exit when we built it. The global app is not
closed - it may be shared with other callers in the same process.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Tuple

import soniq as _soniq
from soniq import Soniq

from ._helpers import resolve_soniq_instance
from .colors import print_status


async def resolve_app(args: Any) -> Tuple[Soniq, bool]:
    """Resolve the Soniq instance for a CLI subcommand.

    Returns ``(app, owns)``. ``owns`` is True when the caller is
    responsible for closing the app (we built a fresh instance for this
    invocation), False when ``app`` is the process-wide global.
    """
    instance = await resolve_soniq_instance(args)
    if instance is not None:
        return instance, True
    return _soniq.get_global_app(), False


@asynccontextmanager
async def cli_app(args: Any) -> AsyncIterator[Soniq]:
    """Yield a Soniq instance for a CLI subcommand.

    Logs the chosen configuration source and closes the instance on
    exit when ``resolve_app`` constructed one.
    """
    app, owns = await resolve_app(args)
    if owns:
        print_status(
            "Using instance-based configuration: " f"{app.settings.database_url}",
            "info",
        )
    else:
        print_status("Using global API configuration", "info")
    try:
        yield app
    finally:
        if owns and app.is_initialized:
            await app.close()
