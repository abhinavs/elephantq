"""``soniq dead-letter`` - operate on dead-letter queue jobs."""

from __future__ import annotations

import os

import soniq as _soniq
from soniq.features.dead_letter import DeadLetterFilter

from ._helpers import database_url_argument, resolve_soniq_instance
from .colors import print_status


def add_dead_letter_cmd(subparsers) -> None:
    parser = subparsers.add_parser(
        "dead-letter",
        help="Manage dead letter queue jobs",
        description="Manage jobs in the dead letter queue",
    )
    parser.add_argument(
        "action",
        choices=["list", "resurrect", "delete", "cleanup", "export"],
        help="Action to perform",
    )
    parser.add_argument("job_ids", nargs="*", help="Job IDs (for resurrect)")
    parser.add_argument("--all", action="store_true", help="Apply action to all jobs")
    parser.add_argument("--filter", help="Filter by job name pattern")
    parser.add_argument("--limit", type=int, default=50, help="Maximum jobs to show")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Remove jobs older than N days",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be deleted"
    )
    parser.add_argument(
        "--format",
        choices=["csv", "json"],
        default="csv",
        help="Export format",
    )
    parser.add_argument("--output", help="Output file path")
    database_url_argument(parser)
    parser.set_defaults(func=handle_dead_letter)


async def handle_dead_letter(args) -> int:
    soniq_instance = await resolve_soniq_instance(args)
    owns_instance = soniq_instance is not None
    if soniq_instance is not None:
        print_status(
            "Using instance-based configuration: "
            f"{soniq_instance.settings.database_url}",
            "info",
        )
    else:
        print_status("Using global API configuration", "info")
        soniq_instance = _soniq.get_global_app()

    dead_letter = soniq_instance.dead_letter

    try:
        action = args.action
        filter_criteria = DeadLetterFilter()
        filter_criteria.limit = args.limit
        if args.filter:
            filter_criteria.job_names = [args.filter]

        if action == "list":
            jobs = await dead_letter.list_dead_letter_jobs(filter_criteria)
            for job in jobs:
                print(f"{job.id}  {job.job_name}  {job.dead_letter_reason}")
            return 0

        if action == "resurrect":
            if args.all:
                await dead_letter.bulk_resurrect(filter_criteria)
                return 0
            if args.job_ids:
                for job_id in args.job_ids:
                    await dead_letter.resurrect_job(job_id)
                return 0
            return 1

        if action == "cleanup":
            # ``cleanup_old_dead_letter_jobs`` does not honour ``--dry-run``;
            # the flag stays on the parser for symmetry but is a no-op here.
            removed = await dead_letter.cleanup_old_dead_letter_jobs(days=args.days)
            return int(removed)

        if action == "delete":
            if args.all:
                await dead_letter.bulk_delete(filter_criteria)
                return 0
            if args.job_ids:
                for job_id in args.job_ids:
                    await dead_letter.delete_dead_letter_job(job_id)
                return 0
            return 1

        if action == "export":
            if not args.output:
                print("--output is required for export")
                return 1
            filename = await dead_letter.export_dead_letter_jobs(
                filter_criteria, format=args.format
            )
            if args.output and args.output != filename:
                os.replace(filename, args.output)
                filename = args.output
            print(filename)
            return 0

        print("Unknown action")
        return 1
    finally:
        if owns_instance and soniq_instance.is_initialized:
            await soniq_instance.close()
