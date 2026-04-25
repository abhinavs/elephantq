"""
Tests for cli/commands/core.py, database.py, and features.py - command
registration.
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
            assert "status" in names
            assert "workers" in names
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


class TestDatabaseCommandRegistration:
    def test_register_database_commands_populates_registry(self):
        from soniq.cli.commands.database import register_database_commands

        registry = CLIRegistry()
        import soniq.cli.registry as reg_mod

        original = reg_mod._registry
        reg_mod._registry = registry
        try:
            register_database_commands()
            names = [c.name for c in registry.get_all_commands()]
            assert "setup" in names
            assert "migrate-status" in names
        finally:
            reg_mod._registry = original


class TestFeatureCommandRegistration:
    def test_register_feature_commands_populates_registry(self):
        from soniq.cli.commands.features import register_feature_commands

        registry = CLIRegistry()
        import soniq.cli.registry as reg_mod

        original = reg_mod._registry
        reg_mod._registry = registry
        try:
            register_feature_commands()
            commands = registry.get_all_commands()
            assert len(commands) > 0
            names = [c.name for c in commands]
            assert any(
                n in names for n in ["dashboard", "scheduler", "metrics", "dead-letter"]
            )
        finally:
            reg_mod._registry = original
