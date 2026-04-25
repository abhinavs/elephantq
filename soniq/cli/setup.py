"""``soniq setup`` - apply pending database migrations."""

from __future__ import annotations

from ._helpers import database_url_argument, resolve_soniq_instance
from .colors import print_status


def add_setup_cmd(subparsers) -> None:
    parser = subparsers.add_parser(
        "setup",
        help="Setup Soniq database",
        description="Initialize or update Soniq database schema",
    )
    database_url_argument(parser)
    parser.set_defaults(func=handle_setup)


async def handle_setup(args) -> int:
    try:
        soniq_instance = await resolve_soniq_instance(args)
    except Exception as e:
        print_status(f"Configuration error: {e}", "error")
        return 1

    owns_instance = soniq_instance is not None
    if soniq_instance is None:
        import soniq as _soniq

        soniq_instance = _soniq._get_global_app()

    try:
        print_status("Setting up Soniq database...", "info")

        print_status(
            "Using instance-based configuration "
            f"(database: {soniq_instance.settings.database_url})",
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
        # Friendly mapping for the common shapes operators hit.
        msg = str(e).lower()
        if "connection" in msg or "connect" in msg:
            print_status("Can't connect to database", "error")
            print("Make sure PostgreSQL is running and your database URL is correct")
        elif "database" in msg and "does not exist" in msg:
            print_status("Database doesn't exist", "error")
            print("Run: createdb your_database_name")
        elif "permission" in msg or "authentication" in msg:
            print_status("Database permission error", "error")
            print("Check your database username/password in the connection URL")
        else:
            print_status(f"Setup failed: {e}", "error")
        return 1
    finally:
        # Only close instances we constructed. The global app is shared.
        if owns_instance and soniq_instance and soniq_instance.is_initialized:
            await soniq_instance.close()
