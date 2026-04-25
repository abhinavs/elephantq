"""
Soniq CLI - flat dispatch.

Each subcommand lives in its own module and exposes one
``add_X_cmd(subparsers)`` function that creates the subparser and
attaches its handler via ``parser.set_defaults(func=...)``. ``main``
just lists them and dispatches whichever the user picked.
"""

import argparse
import asyncio

from .colors import print_status
from .dashboard import add_dashboard_cmd
from .dead_letter import add_dead_letter_cmd
from .metrics import add_metrics_cmd
from .migrate_status import add_migrate_status_cmd
from .scheduler import add_scheduler_cmd
from .setup import add_setup_cmd
from .start import add_start_cmd
from .status import add_status_cmd
from .tasks import add_tasks_cmd
from .workers import add_workers_cmd


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level parser with every subcommand wired in.

    Exposed for tests so they can introspect the parser without
    invoking ``main``.
    """
    parser = argparse.ArgumentParser(
        description="Soniq CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  soniq start --concurrency 4 --queues default,urgent
  soniq setup
  soniq status --verbose --jobs

For more information, visit: https://github.com/abhinavs/soniq
        """,
    )
    sub = parser.add_subparsers(dest="command", title="Commands")

    add_start_cmd(sub)
    add_setup_cmd(sub)
    add_status_cmd(sub)
    add_workers_cmd(sub)
    add_migrate_status_cmd(sub)
    add_dashboard_cmd(sub)
    add_scheduler_cmd(sub)
    add_metrics_cmd(sub)
    add_dead_letter_cmd(sub)
    add_tasks_cmd(sub)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        if hasattr(args, "func"):
            if asyncio.iscoroutinefunction(args.func):
                rc = asyncio.run(args.func(args))
            else:
                rc = args.func(args)
            return int(rc) if rc is not None else 0
        print_status(f"Command '{args.command}' has no handler", "error")
        return 1
    except KeyboardInterrupt:
        print_status("Operation interrupted by user", "info")
        return 0
    except Exception as e:
        print_status(f"Command failed: {e}", "error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
