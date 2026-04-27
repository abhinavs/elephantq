"""``soniq scheduler`` - run the recurring-job scheduler."""

from __future__ import annotations

import asyncio
import os

from ._helpers import (
    configure_cli_logging,
    database_url_argument,
    resolve_soniq_instance,
)
from .colors import print_status


def add_scheduler_cmd(subparsers) -> None:
    parser = subparsers.add_parser(
        "scheduler",
        help="Run the Soniq recurring job scheduler",
        description="Start the recurring job scheduler daemon",
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=60,
        help="How often to check for due jobs in seconds (default: 60)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show scheduler status and exit",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Root logger level (default: INFO, or $SONIQ_LOG_LEVEL)",
    )
    database_url_argument(parser)
    parser.set_defaults(func=handle_scheduler)


async def handle_scheduler(args) -> int:
    import soniq

    soniq_instance = await resolve_soniq_instance(args)
    if soniq_instance is not None:
        print_status(
            "Using instance-based configuration: "
            f"{soniq_instance.settings.database_url}",
            "info",
        )
        app = soniq_instance
    else:
        print_status("Using global API configuration", "info")
        app = soniq.get_global_app()

    log_level: str = (
        getattr(args, "log_level", None) or os.getenv("SONIQ_LOG_LEVEL") or "INFO"
    )
    configure_cli_logging(log_level)

    scheduler = app.scheduler

    if args.status:
        schedules = await scheduler.list()
        active = [s for s in schedules if s["status"] == "active"]
        paused = [s for s in schedules if s["status"] == "paused"]
        print("Soniq Scheduler Status:")
        print(f"  Running: {scheduler.running}")
        print(
            f"  Scheduled jobs: {len(schedules)} "
            f"({len(active)} active, {len(paused)} paused)"
        )
        return 0

    print(f"Starting Soniq recurring scheduler (checking every {args.check_interval}s)")
    print("Use Ctrl+C to stop gracefully")

    try:
        await scheduler.start(check_interval=args.check_interval)
        while scheduler.running:
            await asyncio.sleep(10)
        print("Scheduler stopped unexpectedly")
    except KeyboardInterrupt:
        print("Stopping scheduler...")
        await scheduler.stop()
        print("Scheduler stopped")
    except Exception as e:
        print(f"Scheduler error: {e}")
        return 1
    return 0
