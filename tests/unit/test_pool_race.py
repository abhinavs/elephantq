"""
Verify that the global app's initialization is safe under concurrent access.
"""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_concurrent_access_all_get_same_backend():
    """
    Multiple concurrent _ensure_initialized() calls should all
    end up with the same backend instance.
    """
    from elephantq.client import ElephantQ

    app = ElephantQ(backend="memory")

    # Fire 10 concurrent _ensure_initialized calls
    await asyncio.gather(*[app._ensure_initialized() for _ in range(10)])

    assert app.is_initialized
    assert app.backend is not None

    # All resolved to the same backend
    backend = app.backend
    await app._ensure_initialized()
    assert app.backend is backend

    await app.close()
