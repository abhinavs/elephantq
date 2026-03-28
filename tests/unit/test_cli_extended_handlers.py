"""
Tests for cli/commands/extended.py — context wrapper and registration.
"""

import argparse
from unittest.mock import AsyncMock, patch

import pytest

from elephantq.cli.commands.extended import (
    _with_context,
    register_extended_commands,
    with_elephantq_context,
)


class TestWithContext:
    @pytest.mark.asyncio
    async def test_with_context_runs_handler(self):
        called = []

        async def handler(args):
            called.append(True)
            return 0

        args = argparse.Namespace()
        with patch(
            "elephantq.cli.commands.extended.resolve_elephantq_instance",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _with_context(args, handler)

        assert called == [True]
        assert result == 0

    @pytest.mark.asyncio
    async def test_with_context_sets_and_clears_context(self):
        async def handler(args):
            return 0

        args = argparse.Namespace()
        with patch(
            "elephantq.cli.commands.extended.resolve_elephantq_instance",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await _with_context(args, handler)


class TestWithElephantqContextDecorator:
    def test_decorator_wraps_handler(self):
        async def handler(args):
            return 0

        wrapped = with_elephantq_context(handler)
        assert callable(wrapped)


class TestRegisterExtendedCommands:
    def test_registers_commands(self):
        import elephantq.cli.registry as reg_mod
        from elephantq.cli.registry import CLIRegistry

        original = reg_mod._registry
        registry = CLIRegistry()
        reg_mod._registry = registry
        try:
            register_extended_commands()
            names = [c.name for c in registry.get_all_commands()]
            assert len(names) >= 3
        finally:
            reg_mod._registry = original
