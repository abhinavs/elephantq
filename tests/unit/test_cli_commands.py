"""
Tests for cli/commands/core.py and extended.py — command registration.
"""

from soniq.cli.registry import CLIRegistry


class TestCoreCommandRegistration:
    def test_register_core_commands_populates_registry(self):
        from soniq.cli.commands.core import register_core_commands

        registry = CLIRegistry()
        # We need to temporarily replace the global registry
        import soniq.cli.registry as reg_mod

        original = reg_mod._registry
        reg_mod._registry = registry
        try:
            register_core_commands()
            commands = registry.get_all_commands()
            assert len(commands) > 0
            names = [c.name for c in commands]
            assert "start" in names
            assert "setup" in names
            assert "status" in names
        finally:
            reg_mod._registry = original

    def test_core_commands_have_handlers(self):
        from soniq.cli.commands.core import register_core_commands

        registry = CLIRegistry()
        import soniq.cli.registry as reg_mod

        original = reg_mod._registry
        reg_mod._registry = registry
        try:
            register_core_commands()
            for cmd in registry.get_all_commands():
                assert cmd.handler is not None, f"Command {cmd.name} has no handler"
        finally:
            reg_mod._registry = original


class TestExtendedCommandRegistration:
    def test_register_extended_commands_populates_registry(self):
        from soniq.cli.commands.extended import register_extended_commands

        registry = CLIRegistry()
        import soniq.cli.registry as reg_mod

        original = reg_mod._registry
        reg_mod._registry = registry
        try:
            register_extended_commands()
            commands = registry.get_all_commands()
            assert len(commands) > 0
            names = [c.name for c in commands]
            # Extended commands include dashboard, scheduler, etc.
            assert any(
                n in names for n in ["dashboard", "scheduler", "metrics", "dead-letter"]
            )
        finally:
            reg_mod._registry = original
