"""
`elephantq.configure` replaces the global app. Prior to this PR it marked the
old app "closed" via a private flag without awaiting its pool shutdown,
leaking asyncpg pools on every reconfigure. That is observable in tests that
reconfigure in a loop and in any hot-reload dev workflow.
"""

import asyncio
import inspect

import pytest

import elephantq


def test_configure_is_async():
    """configure must be awaitable so it can close the prior pool in sequence."""
    assert inspect.iscoroutinefunction(elephantq.configure)


@pytest.mark.asyncio
async def test_configure_closes_prior_global_app(monkeypatch):
    """Reconfigure awaits the outgoing app's close() before replacing it."""
    closed = asyncio.Event()

    class _FakeApp:
        _initialized = True
        _closed = False
        _is_initialized = True
        _is_closed = False

        def __init__(self, **_):
            pass

        async def close(self):
            closed.set()
            _FakeApp._is_closed = True

        def job(self, **_):
            # configure() re-registers globally-decorated jobs onto the new
            # instance. Leave this as a noop for the fake.
            def decorator(func):
                return func

            return decorator

    # Seed a fake global app in the "initialized, not closed" state.
    prior = _FakeApp()
    prior._is_closed = False
    elephantq._global_app = prior

    # Replacing it with a new config should close the prior.
    monkeypatch.setattr(elephantq, "ElephantQ", _FakeApp)
    await elephantq.configure(database_url="postgresql://localhost/elephantq")

    assert closed.is_set(), "prior global app was not closed on reconfigure"
    # And the replacement is attached.
    assert elephantq._global_app is not prior
