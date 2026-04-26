"""``soniq workers`` - inspect worker registrations and heartbeats."""

from __future__ import annotations

from ._helpers import database_url_argument, resolve_soniq_instance
from .colors import StatusIcon, print_status


def add_workers_cmd(subparsers) -> None:
    parser = subparsers.add_parser(
        "workers",
        help="Show worker status",
        description="Display active workers, heartbeats, and monitoring information",
    )
    parser.add_argument("--stale", action="store_true", help="Show stale/dead workers")
    parser.add_argument(
        "--cleanup", action="store_true", help="Clean up stale worker records"
    )
    database_url_argument(parser)
    parser.set_defaults(func=handle_workers)


async def handle_workers(args) -> int:
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
        print(f"\n{StatusIcon.workers()} Soniq Worker Status")

        if args.cleanup:
            print_status("Cleaning up stale worker records...", "info")
            stale_threshold = int(app.settings.heartbeat_timeout)
            cleaned = await app.backend.cleanup_stale_workers(stale_threshold)
            if cleaned > 0:
                print_status(f"Cleaned up {cleaned} stale worker records", "success")
            else:
                print_status("No stale workers found", "info")
            print()

        worker_status = await app.backend.get_worker_status()

        status_counts = worker_status.get("status_counts", {})
        active_count = status_counts.get("active", 0)
        stopped_count = status_counts.get("stopped", 0)
        total_concurrency = worker_status.get("total_concurrency", 0)
        health = worker_status.get("health", "unknown")

        print(f"Health: {health.upper()}")
        print(f"Active Workers: {active_count}")
        print(f"Stopped Workers: {stopped_count}")
        print(f"Total Concurrency: {total_concurrency}")

        active_workers = worker_status.get("active_workers", [])
        if active_workers:
            print("\nActive Workers:")
            for worker in active_workers:
                uptime = int(worker["uptime_seconds"])
                uptime_str = (
                    f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s"
                )
                queues_str = (
                    ", ".join(worker["queues"]) if worker["queues"] else "all queues"
                )

                print(f"  🟢 {worker['hostname']}:{worker['pid']}")
                print(f"     Queues: {queues_str}")
                print(f"     Concurrency: {worker['concurrency']}")
                print(f"     Uptime: {uptime_str}")
                print(f"     Last Heartbeat: {worker['last_heartbeat']}")

                metadata = worker.get("metadata", {})
                if isinstance(metadata, dict) and metadata:
                    if "cpu_percent" in metadata:
                        print(f"     CPU: {metadata['cpu_percent']}%")
                    if "memory_mb" in metadata:
                        print(f"     Memory: {metadata['memory_mb']} MB")
                print()

        stale_workers = worker_status.get("stale_workers", [])
        if stale_workers and (args.stale or health == "degraded"):
            print("\nStale Workers (no recent heartbeat):")
            for worker in stale_workers:
                print(f"  🔴 {worker['hostname']}:{worker['pid']}")
                print(f"     Last Heartbeat: {worker['last_heartbeat']}")
                print()

            if not args.cleanup:
                print("Use --cleanup to remove stale worker records")

        if not active_workers and not stale_workers:
            print("\nNo workers found. Start workers with: soniq start")

        return 0
    except Exception as e:
        print_status(f"Failed to get worker status: {e}", "error")
        return 1
    finally:
        if owns_instance and app.is_initialized:
            await app.close()
