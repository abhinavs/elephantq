"""
Unit test conftest — MemoryBackend, zero external dependencies.

No PostgreSQL, no SQLite files, no network. Pure in-memory.
"""

import pytest


@pytest.fixture(autouse=True)
async def reset_global_state():
    """Reset global ElephantQ state between unit tests."""
    yield

    # Reset global app if it was used
    import elephantq

    if elephantq._global_app is not None:
        if (
            elephantq._global_app._is_initialized
            and not elephantq._global_app._is_closed
        ):
            try:
                await elephantq._global_app.close()
            except Exception:
                pass
        elephantq._global_app = None

    # Reset settings cache
    from elephantq.settings import get_settings

    get_settings(reload=True)
