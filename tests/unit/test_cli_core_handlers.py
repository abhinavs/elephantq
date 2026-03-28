"""
Tests for cli/commands/core.py handler functions.

Covers: resolve_elephantq_instance, handle_cli_debug_command.
"""

import argparse

import pytest

from elephantq.cli.commands.core import (
    handle_cli_debug_command,
    resolve_elephantq_instance,
)


class TestResolveElephantqInstance:
    @pytest.mark.asyncio
    async def test_returns_none_without_database_url(self):
        args = argparse.Namespace()
        result = await resolve_elephantq_instance(args)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_database_url_empty(self):
        args = argparse.Namespace(database_url="")
        result = await resolve_elephantq_instance(args)
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_instance_with_valid_url(self):
        args = argparse.Namespace(
            database_url="postgresql://user:pass@localhost/testdb"
        )
        instance = await resolve_elephantq_instance(args)
        assert instance is not None
        assert (
            instance.settings.database_url == "postgresql://user:pass@localhost/testdb"
        )

    @pytest.mark.asyncio
    async def test_returns_instance_for_any_url(self):
        # ElephantQ accepts any URL format (validation happens at connect time)
        args = argparse.Namespace(database_url="postgresql://localhost/any")
        result = await resolve_elephantq_instance(args)
        assert result is not None


class TestHandleCliDebugCommand:
    @pytest.mark.asyncio
    async def test_returns_zero(self, capsys):
        from elephantq.cli.commands.core import register_core_commands

        register_core_commands()
        args = argparse.Namespace()
        result = await handle_cli_debug_command(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Command Registry" in captured.out
        assert "Total commands" in captured.out
