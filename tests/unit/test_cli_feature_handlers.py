"""
Tests for cli/commands/features.py — context wrapper and registration.
"""

import argparse
from unittest.mock import AsyncMock, patch

import pytest

from soniq.cli.commands.features import (
    _with_context,
    register_feature_commands,
    with_soniq_context,
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
            "soniq.cli.commands.features.resolve_soniq_instance",
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
            "soniq.cli.commands.features.resolve_soniq_instance",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await _with_context(args, handler)


class TestWithElephantqContextDecorator:
    def test_decorator_wraps_handler(self):
        async def handler(args):
            return 0

        wrapped = with_soniq_context(handler)
        assert callable(wrapped)


class TestRegisterExtendedCommands:
    def test_registers_commands(self):
        import soniq.cli.registry as reg_mod
        from soniq.cli.registry import CLIRegistry

        original = reg_mod._registry
        registry = CLIRegistry()
        reg_mod._registry = registry
        try:
            register_feature_commands()
            names = [c.name for c in registry.get_all_commands()]
            assert len(names) >= 3
        finally:
            reg_mod._registry = original
