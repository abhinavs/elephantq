"""
Database-management subcommands: `soniq setup` (apply migrations) and
`soniq migrate-status` (show pending vs applied).

Split out of `core.py` to keep file boundaries aligned with command roles.
The handlers were imported from this module's previous home unchanged.
"""

import logging

from ..colors import print_status
from ..registry import register_simple_command
from .core import resolve_soniq_instance

logger = logging.getLogger(__name__)


def register_database_commands():
    """Register the `setup` and `migrate-status` subcommands."""
    instance_arguments = [
        {
            "args": ["--database-url"],
            "kwargs": {
                "help": "Database URL (overrides SONIQ_DATABASE_URL environment variable)",
                "metavar": "URL",
            },
        },
    ]

    register_simple_command(
        name="setup",
        help="Setup Soniq database",
        description="Initialize or update Soniq database schema",
        handler=handle_setup_command,
        arguments=instance_arguments,
        category="database",
    )

    register_simple_command(
        name="migrate-status",
        help="Show database migration status",
        description="Display current database migration status and pending migrations",
        handler=handle_migrate_status_command,
        arguments=instance_arguments,
        category="database",
    )


async def handle_setup_command(args):
    """Handle setup command (migration functionality)"""

    # Resolve Soniq instance from CLI arguments
    try:
        soniq_instance = await resolve_soniq_instance(args)
    except Exception as e:
        print_status(f"Configuration error: {e}", "error")
        return 1

    # When no explicit instance is provided, fall back to the global Soniq.
    # Migrations always run against an explicit instance now; the previous
    # "global pool" path went away with the get_context_pool fallback.
    _owns_instance = False
    if soniq_instance is None:
        import soniq as _soniq

        soniq_instance = _soniq._get_global_app()
        _owns_instance = False  # do not close the global app
    try:
        print_status("Setting up Soniq database...", "info")

        print_status(
            f"Using instance-based configuration (database: {soniq_instance.settings.database_url})",
            "info",
        )
        status = await soniq_instance._get_migration_status()
        applied_count = await soniq_instance._run_migrations()

        print(f"  Found {status['total_migrations']} total migrations")

        if status["pending_migrations"]:
            print(
                f"  Applying {len(status['pending_migrations'])} pending migrations..."
            )
            for migration in status["pending_migrations"]:
                print(f"    - {migration}")
        else:
            print("  Database schema is already up to date")

        if applied_count > 0:
            print_status(f"Applied {applied_count} migrations successfully", "success")
        else:
            print_status("Database setup completed (no migrations needed)", "success")

        return 0
    except Exception as e:
        # Make setup errors friendlier
        error_msg = str(e).lower()
        if "connection" in error_msg or "connect" in error_msg:
            print_status("Can't connect to database", "error")
            print("Make sure PostgreSQL is running and your database URL is correct")
        elif "database" in error_msg and "does not exist" in error_msg:
            print_status("Database doesn't exist", "error")
            print("Run: createdb your_database_name")
        elif "permission" in error_msg or "authentication" in error_msg:
            print_status("Database permission error", "error")
            print("Check your database username/password in the connection URL")
        else:
            print_status(f"Setup failed: {e}", "error")
        return 1
    finally:
        # Clean up instance only if we constructed it ourselves (the
        # `--database-url` path).  The global app is shared, so don't close it.
        if _owns_instance and soniq_instance and soniq_instance._is_initialized:
            await soniq_instance.close()


async def handle_migrate_status_command(args):
    """Handle migrate status command"""

    # Resolve Soniq instance from CLI arguments
    try:
        soniq_instance = await resolve_soniq_instance(args)
    except Exception as e:
        print_status(f"Configuration error: {e}", "error")
        return 1

    if soniq_instance is None:
        import soniq as _soniq

        soniq_instance = _soniq._get_global_app()

    print_status(
        f"Using instance-based configuration: {soniq_instance.settings.database_url}",
        "info",
    )

    try:
        print_status("Soniq Database Migration Status", "info")
        print("=" * 50)

        status = await soniq_instance._get_migration_status()

        print(f"Total migrations: {status['total_migrations']}")
        print(f"Applied migrations: {len(status['applied_migrations'])}")
        print(f"Pending migrations: {len(status['pending_migrations'])}")
        print(
            f"Status: {'Up to date' if status['is_up_to_date'] else 'Migrations pending'}"
        )

        if status["applied_migrations"]:
            print("\nApplied migrations:")
            for migration in status["applied_migrations"]:
                print(f"  ✅ {migration}")

        if status["pending_migrations"]:
            print("\nPending migrations:")
            for migration in status["pending_migrations"]:
                print(f"  ⏳ {migration}")
            print("\nRun 'soniq setup' to apply pending migrations")

        return 0
    except Exception as e:
        print_status(f"Failed to get migration status: {e}", "error")
        return 1
