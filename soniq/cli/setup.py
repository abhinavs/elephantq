"""``soniq setup`` - apply pending database migrations."""

from __future__ import annotations

import soniq as _soniq

from ._helpers import database_url_argument, resolve_soniq_instance
from .colors import print_status

# Map a feature name to the service-attribute on Soniq that owns its
# migrations. Picking up `app.<attr>.setup()` keeps the CLI agnostic to
# which version-prefix each feature uses.
_FEATURE_SETUP_ATTRS = {
    "scheduler": "scheduler",
    "webhooks": "webhooks",
    "logs": "logs",
}


def add_setup_cmd(subparsers) -> None:
    parser = subparsers.add_parser(
        "setup",
        help="Setup Soniq database",
        description="Initialize or update Soniq database schema",
    )
    database_url_argument(parser)
    parser.add_argument(
        "--features",
        help=(
            "Comma-separated list of optional features to set up alongside "
            "the core schema. Choices: " + ", ".join(sorted(_FEATURE_SETUP_ATTRS)) + "."
        ),
        default="",
        metavar="LIST",
    )
    parser.set_defaults(func=handle_setup)


def _parse_features(raw: str) -> list[str]:
    if not raw:
        return []
    requested = [f.strip() for f in raw.split(",") if f.strip()]
    unknown = [f for f in requested if f not in _FEATURE_SETUP_ATTRS]
    if unknown:
        valid = ", ".join(sorted(_FEATURE_SETUP_ATTRS))
        raise ValueError(
            f"Unknown feature(s): {', '.join(unknown)}. Valid choices: {valid}."
        )
    return requested


async def handle_setup(args) -> int:
    try:
        features = _parse_features(getattr(args, "features", "") or "")
    except ValueError as e:
        print_status(str(e), "error")
        return 2

    try:
        soniq_instance = await resolve_soniq_instance(args)
    except Exception as e:
        print_status(f"Configuration error: {e}", "error")
        return 1

    owns_instance = soniq_instance is not None
    if soniq_instance is None:
        soniq_instance = _soniq.get_global_app()

    try:
        print_status("Setting up Soniq database...", "info")

        print_status(
            "Using instance-based configuration "
            f"(database: {soniq_instance.settings.database_url})",
            "info",
        )
        status = await soniq_instance._get_migration_status(version_filter="000")
        applied_count = await soniq_instance._run_migrations(version_filter="000")

        print(f"  Found {status['total_migrations']} core migrations")

        if status["pending_migrations"]:
            print(
                f"  Applying {len(status['pending_migrations'])} pending migrations..."
            )
            for migration in status["pending_migrations"]:
                print(f"    - {migration}")
        else:
            print("  Core schema is already up to date")

        # Optional feature migrations. Each feature's setup() is
        # idempotent, so re-running is safe.
        for feature in features:
            attr = _FEATURE_SETUP_ATTRS[feature]
            print_status(f"Setting up feature: {feature}", "info")
            service = getattr(soniq_instance, attr)
            applied_count += await service.setup()

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
