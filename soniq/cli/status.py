"""``soniq status`` - print queue and worker health."""

from __future__ import annotations

import logging

from ._helpers import database_url_argument, resolve_soniq_instance
from .colors import StatusIcon, print_status

logger = logging.getLogger(__name__)


def add_status_cmd(subparsers) -> None:
    parser = subparsers.add_parser(
        "status",
        help="Show system status",
        description="Display system health, job statistics, and queue information",
    )
    parser.add_argument("--jobs", action="store_true", help="Show recent jobs")
    parser.add_argument(
        "--verbose", action="store_true", help="Show detailed information"
    )
    database_url_argument(parser)
    parser.set_defaults(func=handle_status)


async def handle_status(args) -> int:
    try:
        soniq_instance = await resolve_soniq_instance(args)
    except Exception as e:
        print_status(f"Configuration error: {e}", "error")
        return 1

    if soniq_instance is not None:
        print_status(
            "Using instance-based configuration: "
            f"{soniq_instance.settings.database_url}",
            "info",
        )
        app = soniq_instance
        owns_instance = True
    else:
        import soniq as _soniq

        print_status("Using global API configuration", "info")
        app = _soniq._get_global_app()
        owns_instance = False

    try:
        await app._ensure_initialized()
        print(f"\n{StatusIcon.rocket()} Soniq System Status")

        try:
            async with app.backend.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
            if result == 1:
                print_status("Database connection: OK", "success")
            else:
                print_status("Database connection: FAILED", "error")
                return 1
        except Exception as e:
            print_status(f"Health check failed: {e}", "error")
            return 1

        try:
            queues = await app.get_queue_stats()
            if queues:
                total_jobs = sum(q["total_jobs"] for q in queues)
                total_queued = sum(q["queued"] for q in queues)
                total_failed = sum(q["failed"] + q["dead_letter"] for q in queues)

                print("\nQueue Statistics:")
                print(f"  Total Jobs: {total_jobs}")
                print(f"  Queued: {total_queued}")
                print(f"  Failed/Dead Letter: {total_failed}")
                print(f"  Active Queues: {len(queues)}")

                if args.verbose:
                    print("\nPer-Queue Breakdown:")
                    print(
                        f"{'Queue':<15} {'Total':<8} {'Queued':<8} "
                        f"{'Done':<8} {'Failed':<8}"
                    )
                    print("-" * 60)
                    for queue in queues:
                        print(
                            f"{queue['queue']:<15} {queue['total_jobs']:<8} "
                            f"{queue['queued']:<8} {queue['done']:<8} "
                            f"{queue['failed']:<8}"
                        )

                if total_queued > 0:
                    print_status(
                        f"{total_queued} jobs waiting to be processed", "warning"
                    )
                elif total_failed > 0:
                    print_status(f"{total_failed} jobs need attention", "warning")
                else:
                    print_status("All jobs processed successfully", "success")
            else:
                print_status("No jobs found in any queue", "info")
        except Exception as e:
            print_status(f"Failed to get queue stats: {e}", "error")
            return 1

        try:
            worker_status = await app.backend.get_worker_status()
            status_counts = worker_status.get("status_counts", {})
            active_count = status_counts.get("active", 0)
            stale_count = len(worker_status.get("stale_workers", []))

            if active_count > 0 or stale_count > 0:
                worker_summary = f"{active_count} active"
                if stale_count > 0:
                    worker_summary += f", {stale_count} stale"
                worker_summary += " (use 'soniq workers' for details)"
                print(f"\nWorkers: {worker_summary}")
            else:
                print("\nWorkers: None running (use 'soniq start' to begin)")
        except Exception as e:
            logger.debug(f"Could not get worker summary: {e}")

        if args.jobs:
            try:
                recent_jobs = await app.list_jobs(limit=10)
                if recent_jobs:
                    print(f"\nRecent Jobs ({len(recent_jobs)}):")
                    print(f"{'ID'[:8]:<8} {'Name':<25} {'Status':<12} {'Queue':<10}")
                    print("-" * 60)
                    for job in recent_jobs:
                        job_name = job["job_name"].split(".")[-1]
                        print(
                            f"{job['id'][:8]:<8} {job_name:<25} "
                            f"{job['status']:<12} {job['queue']:<10}"
                        )
                else:
                    print("  No recent jobs")
            except Exception as e:
                print_status(f"Failed to get recent jobs: {e}", "error")

        return 0
    finally:
        if owns_instance and app.is_initialized:
            await app.close()
