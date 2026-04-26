"""
Tests for the active-app contextvar.

Features (`every`, `daily`, `schedule_job`, `@periodic`, etc.) used to reach
for `_get_global_app()` unconditionally. A user calling them from inside an
`Soniq(...)` instance method silently crossed database boundaries: the
feature wrote to the *global* app's Postgres, not the instance's. The
contextvar lets instance methods announce "I'm the active app" so features
can honor the caller's choice while keeping the zero-config global path.
"""

import pytest

import soniq


@pytest.mark.asyncio
async def test_contextvar_set_during_instance_method(monkeypatch):
    """Soniq instance methods attach self to the active-app contextvar.

    We observe the var from within a function the wrapped method calls,
    rather than by overriding the method itself (which would bypass the
    decorator).
    """
    from soniq._active import get_active_app

    app = soniq.Soniq(database_url="postgresql://localhost/test")

    observed = {}

    # Stub out the backend path so list_jobs is a no-op but still routed
    # through the `_with_active_app` wrapper on the instance method.
    class _StubBackend:
        async def list_jobs(self, **_):
            observed["active"] = get_active_app()
            return []

    app._backend = _StubBackend()
    app._initialized = True

    assert get_active_app() is None, "outside any method, no active app"
    await app.list_jobs()
    assert observed["active"] is app, "active app should be the caller's instance"
    assert get_active_app() is None, "contextvar cleared after method returns"


@pytest.mark.asyncio
async def test_global_enqueue_uses_active_app_when_set():
    """soniq.enqueue delegates to the active instance, not the global, when set."""
    from soniq._active import _active_app

    class _FakeApp(soniq.Soniq):
        # isinstance(active, Soniq) in _resolve_app picks us up only if we
        # inherit from the real class. Subclassing lets us keep the type guard.
        def __init__(self):
            pass

        async def enqueue(self, name_or_ref=None, **kwargs):
            target = (
                name_or_ref if name_or_ref is not None else kwargs.get("name_or_ref")
            )
            return f"fake::{target}"

    fake = _FakeApp()
    token = _active_app.set(fake)
    try:
        result = await soniq.enqueue("task")
    finally:
        _active_app.reset(token)

    assert result == "fake::task"


@pytest.mark.asyncio
async def test_global_enqueue_falls_back_to_global_when_no_active():
    """No active app set: global API behaves as before."""
    import unittest.mock as mock

    async def task():
        return None

    with mock.patch("soniq._get_global_app") as get_global:
        fake_global = mock.MagicMock()
        fake_global.enqueue = mock.AsyncMock(return_value="global::task")
        get_global.return_value = fake_global

        result = await soniq.enqueue("task")

    assert result == "global::task"
