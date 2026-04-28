"""
Unit tests for the unified CLI app helper.

``soniq.cli._context.cli_app`` and ``resolve_app`` are the entry points
every CLI subcommand uses. The helper:

- builds a fresh Soniq from ``--database-url`` (owns=True) or returns
  the process-wide global (owns=False);
- closes the instance on context-manager exit only when it owns it.
"""

from __future__ import annotations

import argparse

import pytest

import soniq as _soniq
from soniq.cli._context import cli_app, resolve_app


class _FakeSoniq:
    def __init__(self, database_url: str = "postgresql://fake/global"):
        self.settings = argparse.Namespace(database_url=database_url)
        self.is_initialized = False
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_resolve_app_returns_global_when_no_flag(monkeypatch):
    """No ``--database-url`` -> global app, owns=False."""
    fake = _FakeSoniq()
    monkeypatch.setattr(_soniq, "get_global_app", lambda: fake)

    args = argparse.Namespace(database_url=None)
    app, owns = await resolve_app(args)

    assert app is fake
    assert owns is False


@pytest.mark.asyncio
async def test_resolve_app_builds_fresh_instance_from_flag():
    """``--database-url`` -> fresh Soniq, owns=True."""
    args = argparse.Namespace(
        database_url="postgresql://u:p@localhost:5432/explicit_db"
    )
    app, owns = await resolve_app(args)

    assert owns is True
    assert app.settings.database_url == "postgresql://u:p@localhost:5432/explicit_db"


@pytest.mark.asyncio
async def test_cli_app_closes_owned_instance_on_exit(monkeypatch):
    """When we own the instance, we close it. Spy on Soniq.close to
    avoid needing a real database."""
    from soniq import Soniq

    closed: list[Soniq] = []

    async def fake_close(self):
        closed.append(self)

    monkeypatch.setattr(Soniq, "close", fake_close)
    monkeypatch.setattr(Soniq, "is_initialized", property(lambda self: True))

    args = argparse.Namespace(database_url="postgresql://u:p@localhost:5432/owned_db")

    async with cli_app(args) as app:
        assert isinstance(app, Soniq)

    assert closed == [app], "Owned instance should have been closed on exit."


@pytest.mark.asyncio
async def test_cli_app_does_not_close_global(monkeypatch):
    """When we don't own the instance, we must not close it. Other
    callers in the process still hold the global."""
    fake = _FakeSoniq()
    monkeypatch.setattr(_soniq, "get_global_app", lambda: fake)

    args = argparse.Namespace(database_url=None)
    async with cli_app(args) as app:
        app.is_initialized = True

    assert fake.closed is False, (
        "cli_app must not close the global Soniq - it is shared with " "other callers."
    )
