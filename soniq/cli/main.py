"""
Soniq CLI - Simplified main module with consolidated commands
"""

import argparse
import asyncio

from .colors import print_status

# Import extensible command system
from .commands.core import register_core_commands
from .commands.database import register_database_commands
from .commands.features import register_feature_commands
from .registry import get_cli_registry


def main():
    """Main CLI entry point with organized command structure"""
    parser = argparse.ArgumentParser(
        description="Soniq CLI - Unified Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  soniq start --concurrency 4 --queues default,urgen
  soniq setup
  soniq status --verbose --jobs

For more information, visit: https://github.com/abhinavs/soniq
        """,
    )

    subparsers = parser.add_subparsers(dest="command", title="Available commands")

    # Register core commands (start, status, workers, cli-debug)
    register_core_commands()

    # Register database commands (setup, migrate-status)
    register_database_commands()

    # Register feature commands (dashboard, scheduler, metrics, dead-letter)
    register_feature_commands()

    # Add all registered commands to the parser
    registry = get_cli_registry()
    registry.add_to_parser(subparsers)

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Execute the command
    try:
        if hasattr(args, "func"):
            # Core command handler
            if asyncio.iscoroutinefunction(args.func):
                return asyncio.run(args.func(args))
            else:
                return args.func(args)
        else:
            print_status(f"Command '{args.command}' has no handler", "error")
            return 1

    except KeyboardInterrupt:
        print_status("Operation interrupted by user", "info")
        return 0
    except Exception as e:
        print_status(f"Command failed: {e}", "error")
        return 1


if __name__ == "__main__":
    exit(main())
