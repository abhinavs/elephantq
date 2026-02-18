"""
Extended CLI commands for ElephantQ (dashboard, scheduler, metrics, dead-letter).
"""

import asyncio
from typing import Callable

from ..colors import print_status
from ..registry import register_simple_command
from .core import resolve_elephantq_instance


async def _with_context(args, handler):
    """Run a handler with a properly configured database context."""
    from elephantq.db.context import (
        DatabaseContext,
        clear_current_context,
        set_current_context,
    )

    try:
        elephantq_instance = await resolve_elephantq_instance(args)

        if elephantq_instance:
            context = DatabaseContext.from_instance(elephantq_instance)
            print_status(
                f"Using instance-based configuration: {elephantq_instance.settings.database_url}",
                "info",
            )
        else:
            context = DatabaseContext.from_global_api()
            print_status("Using global API configuration", "info")

        set_current_context(context)

        result = handler(args)
        if asyncio.iscoroutine(result):
            result = await result
        return result
    finally:
        clear_current_context()


def with_elephantq_context(handler: Callable):
    """Decorator to run CLI handlers with a configured database context."""

    def wrapper(args):
        try:
            return asyncio.run(_with_context(args, handler))
        except RuntimeError as e:
            print(str(e))
            return 1

    return wrapper


def register_extended_commands():
    """Register extended commands using the registry system."""
    instance_arguments = [
        {
            "args": ["--database-url"],
            "kwargs": {
                "help": "Database URL (overrides ELEPHANTQ_DATABASE_URL environment variable)",
                "metavar": "URL",
            },
        },
    ]

    register_simple_command(
        name="dashboard",
        help="Launch the ElephantQ web dashboard",
        description="Start the ElephantQ web dashboard for monitoring jobs",
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
        help="Run the ElephantQ recurring job scheduler",
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
        help="Show ElephantQ performance metrics",
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


@with_elephantq_context
def handle_dashboard_command(args):
    from elephantq import DASHBOARD_AVAILABLE

    if not DASHBOARD_AVAILABLE:
        print(
            "Dashboard is not available. Install with: pip install elephantq[dashboard]"
        )
        return 1

    from elephantq.dashboard.fastapi_app import run_dashboard

    async def _run():
        return await run_dashboard(host=args.host, port=args.port)

    return _run()


@with_elephantq_context
def handle_scheduler_command(args):
    from elephantq.features.recurring import (
        get_scheduler_status,
        start_recurring_scheduler,
        stop_recurring_scheduler,
    )

    async def _run():
        if args.status:
            status = get_scheduler_status()
            print("ElephantQ Scheduler Status:")
            print(f"  Running: {status['running']}")
            print(f"  Scheduler exists: {status['scheduler_exists']}")
            print(f"  Scheduled jobs: {status['scheduled_jobs']}")
            if status.get("check_interval"):
                print(f"  Check interval: {status['check_interval']}s")
            return 0

        print(
            f"Starting ElephantQ recurring scheduler (checking every {args.check_interval}s)"
        )
        print("Use Ctrl+C to stop gracefully")

        try:
            await start_recurring_scheduler(args.check_interval)
            while True:
                status = get_scheduler_status()
                if not status["running"]:
                    print("Scheduler stopped unexpectedly")
                    break
                await asyncio.sleep(10)
        except KeyboardInterrupt:
            print("Stopping scheduler...")
            await stop_recurring_scheduler()
            print("Scheduler stopped")
        except Exception as e:
            print(f"Scheduler error: {e}")
            return 1
        return 0

    return _run()


@with_elephantq_context
def handle_metrics_command(args):
    from elephantq.features.flags import require_feature
    from elephantq.features.metrics import get_system_metrics

    async def _run():
        require_feature("metrics_enabled", "Metrics")
        metrics = await get_system_metrics(timeframe_hours=args.hours)
        if args.format == "json":
            import json

            print(json.dumps(metrics, indent=2, default=str))
        else:
            print("ElephantQ Metrics:")
            for key, value in metrics.items():
                print(f"  {key}: {value}")
        return 0

    return _run()


@with_elephantq_context
def handle_dead_letter_command(args):
    from elephantq.features.dead_letter import (
        bulk_delete_dead_letter_jobs,
        bulk_resurrect_jobs,
        cleanup_old_dead_letter_jobs,
        create_filter,
        delete_dead_letter_job,
        export_dead_letter_jobs,
        list_dead_letter_jobs,
        resurrect_job,
    )
    from elephantq.features.flags import require_feature

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
