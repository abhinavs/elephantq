"""
Tests for cli/registry.py — CLICommand and CLIRegistry.
"""

import argparse

from soniq.cli.registry import CLICommand, CLIRegistry, get_cli_registry


def _dummy_handler(args):
    return 0


class TestCLICommand:
    def test_basic_creation(self):
        cmd = CLICommand(
            name="test",
            help="Test command",
            description="A test command",
            handler=_dummy_handler,
        )
        assert cmd.name == "test"
        assert cmd.help == "Test command"
        assert cmd.handler is _dummy_handler
        assert cmd.category == "core"
        assert cmd.aliases == []
        assert cmd.arguments == []

    def test_add_to_parser(self):
        cmd = CLICommand(
            name="greet",
            help="Say hello",
            description="Greeting command",
            handler=_dummy_handler,
            arguments=[
                {"args": ["--name"], "kwargs": {"default": "world"}},
            ],
            aliases=["hi"],
        )
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        cmd.add_to_parser(subparsers)

        args = parser.parse_args(["greet", "--name", "Alice"])
        assert args.name == "Alice"
        assert args.func is _dummy_handler


class TestCLIRegistry:
    def test_register_and_get_command(self):
        registry = CLIRegistry()
        cmd = CLICommand("test", "help", "desc", _dummy_handler)
        registry.register_command(cmd)
        assert registry.get_command("test") is cmd

    def test_get_command_returns_none_for_missing(self):
        registry = CLIRegistry()
        assert registry.get_command("nonexistent") is None

    def test_register_simple_command(self):
        registry = CLIRegistry()
        registry.register_simple_command(
            name="simple",
            help="A simple command",
            handler=_dummy_handler,
            category="tools",
        )
        cmd = registry.get_command("simple")
        assert cmd is not None
        assert cmd.category == "tools"

    def test_get_commands_by_category(self):
        registry = CLIRegistry()
        registry.register_simple_command("a", "help", _dummy_handler, category="core")
        registry.register_simple_command("b", "help", _dummy_handler, category="core")
        registry.register_simple_command("c", "help", _dummy_handler, category="ext")

        core_cmds = registry.get_commands_by_category("core")
        assert len(core_cmds) == 2

        ext_cmds = registry.get_commands_by_category("ext")
        assert len(ext_cmds) == 1

        empty = registry.get_commands_by_category("nonexistent")
        assert empty == []

    def test_get_all_commands(self):
        registry = CLIRegistry()
        registry.register_simple_command("a", "help", _dummy_handler)
        registry.register_simple_command("b", "help", _dummy_handler)

        all_cmds = registry.get_all_commands()
        assert len(all_cmds) == 2

    def test_get_categories(self):
        registry = CLIRegistry()
        registry.register_simple_command("a", "help", _dummy_handler, category="core")
        registry.register_simple_command("b", "help", _dummy_handler, category="tools")

        cats = registry.get_categories()
        assert "core" in cats
        assert "tools" in cats

    def test_add_to_parser(self):
        registry = CLIRegistry()
        registry.register_simple_command("run", "Run worker", _dummy_handler)

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        registry.add_to_parser(subparsers)

        args = parser.parse_args(["run"])
        assert args.command == "run"

    def test_get_registry_status(self):
        registry = CLIRegistry()
        registry.register_simple_command("a", "help", _dummy_handler, category="core")
        registry.register_simple_command("b", "help", _dummy_handler, category="ext")

        status = registry.get_registry_status()
        assert status["total_commands"] == 2
        assert "core" in status["categories"]
        assert status["command_names"] == ["a", "b"]

    def test_override_existing_command(self):
        registry = CLIRegistry()
        registry.register_simple_command("a", "first", _dummy_handler)
        registry.register_simple_command("a", "second", _dummy_handler)

        cmd = registry.get_command("a")
        assert cmd.help == "second"


class TestGlobalRegistry:
    def test_get_cli_registry_returns_singleton(self):
        r1 = get_cli_registry()
        r2 = get_cli_registry()
        assert r1 is r2
