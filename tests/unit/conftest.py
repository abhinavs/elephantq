"""
Unit test conftest — MemoryBackend, zero external dependencies.

No PostgreSQL, no SQLite files, no network. Pure in-memory.
"""

import pytest


@pytest.fixture(autouse=True)
async def reset_global_state():
    """Reset global Soniq state between unit tests."""
    yield

    # Reset global app if it was used
    import soniq

    if soniq._global_app is not None:
        if soniq._global_app.is_initialized and not soniq._global_app.is_closed:
            try:
                await soniq._global_app.close()
            except Exception:
                pass
        soniq._global_app = None

    # Reset settings cache
    from soniq.settings import get_settings

    get_settings(reload=True)
