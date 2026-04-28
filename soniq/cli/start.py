"""``soniq start`` - run a worker."""

from __future__ import annotations

import os
import sys

import soniq
from soniq.discovery import discover_and_import_modules, parse_jobs_modules

from ._helpers import (
    configure_cli_logging,
    database_url_argument,
    resolve_soniq_instance,
)
from .colors import print_status


def add_start_cmd(subparsers) -> None:
    parser = subparsers.add_parser(
        "start",
        help="Start Soniq worker",
        description="Start Soniq worker to process background jobs",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Number of concurrent workers (default: 4)",
    )
    parser.add_argument(
        "--queues",
        default=None,
        help="Comma-separated list of queues to process (default: all queues)",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Process jobs once and exit (useful for testing)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="Root logger level (default: INFO, or $SONIQ_LOG_LEVEL)",
    )
    database_url_argument(parser)
    parser.set_defaults(func=handle_start)


async def handle_start(args) -> int:
    log_level: str = (
        getattr(args, "log_level", None) or os.getenv("SONIQ_LOG_LEVEL") or "INFO"
    )
    configure_cli_logging(log_level)

    jobs_modules_env = os.getenv("SONIQ_JOBS_MODULES", "")
    if not jobs_modules_env:
        print(
            "Error: SONIQ_JOBS_MODULES is not set. "
            "Please configure the path to your job modules.",
            file=sys.stderr,
        )
        sys.exit(1)

    modules = parse_jobs_modules(jobs_modules_env)
    if len(modules) == 1:
        print(f"Discovering jobs in: {modules[0]}")
    else:
        print("Discovering jobs in:")
        for mod in modules:
            print(f"  {mod}")

    discover_and_import_modules(modules)
    for mod in modules:
        print(f"  - Imported '{mod}'")

    try:
        soniq_instance = await resolve_soniq_instance(args)
    except Exception as e:
        print_status(f"Configuration error: {e}", "error")
        return 1

    if args.queues is None:
        queues = None
        queue_msg = "all available queues"
    else:
        queues = [q.strip() for q in args.queues.split(",")]
        queue_msg = ", ".join(queues)

    print_status(f"Starting Soniq worker with {args.concurrency} workers", "info")
    print_status(f"Processing queues: {queue_msg}", "info")

    if soniq_instance:
        print_status(
            "Using instance-based configuration "
            f"(database: {soniq_instance.settings.database_url})",
            "info",
        )
    else:
        print_status("Using global API configuration", "info")

    try:
        if soniq_instance:
            await soniq_instance.run_worker(
                concurrency=args.concurrency, queues=queues, run_once=args.run_once
            )
        else:
            await soniq.run_worker(
                concurrency=args.concurrency, queues=queues, run_once=args.run_once
            )
    except KeyboardInterrupt:
        print_status("Worker stopped by user", "info")
        return 0
    except Exception as e:
        print_status(f"Worker error: {e}", "error")
        return 1
    finally:
        if soniq_instance and soniq_instance.is_initialized:
            await soniq_instance.close()

    return 0
