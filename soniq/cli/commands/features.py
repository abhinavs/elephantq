"""
Extended CLI commands for Soniq (dashboard, scheduler, metrics, dead-letter).
"""

import asyncio
from typing import Callable

from ..colors import print_status
from ..registry import register_simple_command
from .core import resolve_soniq_instance


async def _with_context(args, handler):
    """Run a handler after resolving the Soniq instance from CLI args.

    Feature handlers reach for ``soniq._get_global_app()`` directly, so
    nothing extra needs threading; this helper just emits the same
    "instance vs. global" status line the older flow did and lets the
    handler run.
    """
    soniq_instance = await resolve_soniq_instance(args)
    if soniq_instance is not None:
        print_status(
            f"Using instance-based configuration: {soniq_instance.settings.database_url}",
            "info",
        )
    else:
        print_status("Using global API configuration", "info")

    result = handler(args)
    if asyncio.iscoroutine(result):
        result = await result
    return result


def with_soniq_context(handler: Callable):
    """Decorator to run CLI handlers with a configured database context."""

    def wrapper(args):
        try:
            return asyncio.run(_with_context(args, handler))
        except RuntimeError as e:
            print(str(e))
            return 1

    return wrapper


def register_feature_commands():
    """Register feature subcommands (dashboard, scheduler, metrics, dead-letter)
    against the CLI registry."""
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
        name="dashboard",
        help="Launch the Soniq web dashboard",
        description="Start the Soniq web dashboard for monitoring jobs",
        handler=handle_dashboard_command,
        arguments=[
            {
                "args": ["--host"],
                "kwargs": {"default": "127.0.0.1", "help": "Host to bind to"},
            },
            {
                "args": ["--port"],
                "kwargs": {"type": int, "default": 6161, "help": "Port to bind to"},
            },
            {
                "args": ["--reload"],
                "kwargs": {"action": "store_true", "help": "Enable auto-reload"},
            },
        ]
        + instance_arguments,
        category="features",
    )

    register_simple_command(
        name="scheduler",
        help="Run the Soniq recurring job scheduler",
        description="Start the recurring job scheduler daemon",
        handler=handle_scheduler_command,
        arguments=[
            {
                "args": ["--check-interval"],
                "kwargs": {
                    "type": int,
                    "default": 60,
                    "help": "How often to check for due jobs in seconds (default: 60)",
                },
            },
            {
                "args": ["--status"],
                "kwargs": {
                    "action": "store_true",
                    "help": "Show scheduler status and exit",
                },
            },
        ]
        + instance_arguments,
        category="features",
    )

    register_simple_command(
        name="metrics",
        help="Show Soniq performance metrics",
        description="Display performance metrics and analytics",
        handler=handle_metrics_command,
        arguments=[
            {
                "args": ["--format"],
                "kwargs": {
                    "choices": ["json", "table"],
                    "default": "table",
                    "help": "Output format (default: table)",
                },
            },
            {
                "args": ["--hours"],
                "kwargs": {"type": int, "default": 24, "help": "Time range in hours"},
            },
            {"args": ["--export"], "kwargs": {"help": "Export metrics to file"}},
        ]
        + instance_arguments,
        category="features",
    )

    register_simple_command(
        name="dead-letter",
        help="Manage dead letter queue jobs",
        description="Manage jobs in the dead letter queue",
        handler=handle_dead_letter_command,
        arguments=[
            {
                "args": ["action"],
                "kwargs": {
                    "choices": ["list", "resurrect", "delete", "cleanup", "export"],
                    "help": "Action to perform",
                },
            },
            {
                "args": ["job_ids"],
                "kwargs": {"nargs": "*", "help": "Job IDs (for resurrect)"},
            },
            {
                "args": ["--all"],
                "kwargs": {"action": "store_true", "help": "Apply action to all jobs"},
            },
            {"args": ["--filter"], "kwargs": {"help": "Filter by job name pattern"}},
            {
                "args": ["--limit"],
                "kwargs": {"type": int, "default": 50, "help": "Maximum jobs to show"},
            },
            {
                "args": ["--days"],
                "kwargs": {
                    "type": int,
                    "default": 30,
                    "help": "Remove jobs older than N days",
                },
            },
            {
                "args": ["--dry-run"],
                "kwargs": {
                    "action": "store_true",
                    "help": "Show what would be deleted",
                },
            },
            {
                "args": ["--format"],
                "kwargs": {
                    "choices": ["csv", "json"],
                    "default": "csv",
                    "help": "Export format",
                },
            },
            {"args": ["--output"], "kwargs": {"help": "Output file path"}},
        ]
        + instance_arguments,
        category="features",
    )


@with_soniq_context
def handle_dashboard_command(args):
    from soniq import DASHBOARD_AVAILABLE

    if not DASHBOARD_AVAILABLE:
        print("Dashboard is not available. Install with: pip install soniq[dashboard]")
        return 1

    from soniq.dashboard.fastapi_app import run_dashboard

    async def _run():
        return await run_dashboard(host=args.host, port=args.port)

    return _run()


@with_soniq_context
def handle_scheduler_command(args):
    import os

    import soniq
    from soniq.cli.commands.core import _configure_cli_logging

    _configure_cli_logging(
        getattr(args, "log_level", None) or os.getenv("SONIQ_LOG_LEVEL", "INFO")
    )

    async def _run():
        app = soniq._get_global_app()
        scheduler = app.scheduler

        if args.status:
            schedules = await scheduler.list()
            active = [s for s in schedules if s["status"] == "active"]
            paused = [s for s in schedules if s["status"] == "paused"]
            print("Soniq Scheduler Status:")
            print(f"  Running: {scheduler.running}")
            print(
                f"  Scheduled jobs: {len(schedules)} ({len(active)} active, {len(paused)} paused)"
            )
            return 0

        print(
            f"Starting Soniq recurring scheduler (checking every {args.check_interval}s)"
        )
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

    return _run()


@with_soniq_context
def handle_metrics_command(args):
    from soniq.features.flags import require_feature
    from soniq.features.metrics import get_system_metrics

    async def _run():
        require_feature("metrics_enabled", "Metrics")
        metrics = await get_system_metrics(timeframe_hours=args.hours)
        if args.format == "json":
            import json

            print(json.dumps(metrics, indent=2, default=str))
        else:
            print("Soniq Metrics:")
            for key, value in metrics.items():
                print(f"  {key}: {value}")
        return 0

    return _run()


@with_soniq_context
def handle_dead_letter_command(args):
    from soniq.features.dead_letter import (
        bulk_delete_dead_letter_jobs,
        bulk_resurrect_jobs,
        cleanup_old_dead_letter_jobs,
        create_filter,
        delete_dead_letter_job,
        export_dead_letter_jobs,
        list_dead_letter_jobs,
        resurrect_job,
    )
    from soniq.features.flags import require_feature

    async def _run():
        require_feature("dead_letter_queue_enabled", "Dead letter queue")
        action = args.action
        filter_criteria = create_filter()
        filter_criteria.limit = args.limit
        if args.filter:
            filter_criteria.job_names = [args.filter]

        if action == "list":
            jobs = await list_dead_letter_jobs(filter_criteria)
            for job in jobs:
                print(f"{job.id}  {job.job_name}  {job.dead_letter_reason}")
            return 0

        if action == "resurrect":
            if args.all:
                await bulk_resurrect_jobs(filter_criteria)
                return 0
            if args.job_ids:
                for job_id in args.job_ids:
                    await resurrect_job(job_id)
                return 0
            return 1

        if action == "cleanup":
            return await cleanup_old_dead_letter_jobs(
                days=args.days, dry_run=args.dry_run
            )

        if action == "delete":
            if args.all:
                await bulk_delete_dead_letter_jobs(filter_criteria)
                return 0
            if args.job_ids:
                for job_id in args.job_ids:
                    await delete_dead_letter_job(job_id)
                return 0
            return 1

        if action == "export":
            if not args.output:
                print("--output is required for export")
                return 1
            filename = await export_dead_letter_jobs(
                filter_criteria, format=args.format
            )
            if args.output and args.output != filename:
                import os

                os.replace(filename, args.output)
                filename = args.output
            print(filename)
            return 0

        print("Unknown action")
        return 1

    return _run()
