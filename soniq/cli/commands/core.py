"""
Consolidated Soniq CLI commands - refactored for extensibility
"""

import logging

from ..colors import StatusIcon, print_status
from ..registry import register_simple_command

logger = logging.getLogger(__name__)


def _configure_cli_logging(level: str = "INFO") -> None:
    """Attach a stream handler to the root logger so long-running CLI
    commands (worker, scheduler) emit job-lifecycle logs to the terminal.

    Safe to call multiple times; it won't duplicate handlers.
    """
    root = logging.getLogger()
    try:
        resolved = getattr(logging, str(level).upper())
    except AttributeError:
        resolved = logging.INFO
    root.setLevel(resolved)
    already_configured = any(
        getattr(h, "_soniq_cli_handler", False) for h in root.handlers
    )
    if not already_configured:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handler._soniq_cli_handler = True  # type: ignore[attr-defined]
        root.addHandler(handler)


async def resolve_soniq_instance(args):
    """
    Resolve Soniq instance configuration from CLI arguments.

    If --database-url is provided, returns a Soniq instance.
    Otherwise, returns None to use the global API.

    Returns:
        Soniq instance or None (to use global API)
    """
    from pydantic import ValidationError

    from soniq import Soniq

    # Use instance-based API if database URL is provided
    if hasattr(args, "database_url") and args.database_url:
        try:
            return Soniq(database_url=args.database_url)
        except ValidationError as e:
            # Make database URL errors friendlier
            if "database_url" in str(e):
                if "postgresql" in str(e).lower():
                    raise ValueError(
                        f"Invalid database URL: {args.database_url}\nSoniq requires PostgreSQL URLs like: postgresql://user:password@localhost/database"
                    )
                else:
                    raise ValueError(f"Invalid database URL: {args.database_url}")
            raise ValueError(f"Configuration error: {e}")
        except Exception as e:
            # Handle other connection/config errors
            if "connect" in str(e).lower() or "connection" in str(e).lower():
                raise ValueError(
                    f"Can't connect to database: {args.database_url}\nMake sure PostgreSQL is running and the URL is correct"
                )
            raise ValueError(f"Database configuration error: {e}")

    # Otherwise use global API
    return None


def register_core_commands():
    """Register all core CLI commands using the registry system."""

    # Common instance argument for commands that support instance-based usage
    instance_arguments = [
        {
            "args": ["--database-url"],
            "kwargs": {
                "help": "Database URL (overrides SONIQ_DATABASE_URL environment variable)",
                "metavar": "URL",
            },
        },
    ]

    # Start command (worker functionality)
    register_simple_command(
        name="start",
        help="Start Soniq worker",
        description="Start Soniq worker to process background jobs",
        handler=handle_start_command,
        arguments=[
            {
                "args": ["--concurrency"],
                "kwargs": {
                    "type": int,
                    "default": 4,
                    "help": "Number of concurrent workers (default: 4)",
                },
            },
            {
                "args": ["--queues"],
                "kwargs": {
                    "default": None,
                    "help": "Comma-separated list of queues to process (default: all queues)",
                },
            },
            {
                "args": ["--run-once"],
                "kwargs": {
                    "action": "store_true",
                    "help": "Process jobs once and exit (useful for testing)",
                },
            },
            {
                "args": ["--log-level"],
                "kwargs": {
                    "default": None,
                    "help": "Root logger level (default: INFO, or $SONIQ_LOG_LEVEL)",
                },
            },
        ]
        + instance_arguments,
        category="worker",
    )

    # Status command (monitoring)
    register_simple_command(
        name="status",
        help="Show system status",
        description="Display system health, job statistics, and queue information",
        handler=handle_status_command,
        arguments=[
            {
                "args": ["--jobs"],
                "kwargs": {"action": "store_true", "help": "Show recent jobs"},
            },
            {
                "args": ["--verbose"],
                "kwargs": {"action": "store_true", "help": "Show detailed information"},
            },
        ]
        + instance_arguments,
        category="monitoring",
    )

    # Worker status command (monitoring)
    register_simple_command(
        name="workers",
        help="Show worker status",
        description="Display active workers, heartbeats, and monitoring information",
        handler=handle_workers_command,
        arguments=[
            {
                "args": ["--stale"],
                "kwargs": {"action": "store_true", "help": "Show stale/dead workers"},
            },
            {
                "args": ["--cleanup"],
                "kwargs": {
                    "action": "store_true",
                    "help": "Clean up stale worker records",
                },
            },
        ]
        + instance_arguments,
        category="monitoring",
    )

    # CLI debug command (development)
    register_simple_command(
        name="cli-debug",
        help="Show CLI command registry information",
        description="Display information about registered CLI commands for debugging",
        handler=handle_cli_debug_command,
        arguments=[],
        category="debug",
    )


async def handle_start_command(args):
    """Handle start command (worker functionality)"""
    # --- BEGIN DISCOVERY SNIPPET ---
    import os
    import sys

    from soniq import settings
    from soniq.discovery import discover_and_import_modules, parse_jobs_modules

    _configure_cli_logging(
        getattr(args, "log_level", None) or os.getenv("SONIQ_LOG_LEVEL", "INFO")
    )

    if not settings.SONIQ_JOBS_MODULES:
        print(
            "Error: SONIQ_JOBS_MODULES is not set. Please configure the path to your job modules.",
            file=sys.stderr,
        )
        sys.exit(1)

    modules = parse_jobs_modules(settings.SONIQ_JOBS_MODULES)
    if len(modules) == 1:
        print(f"Discovering jobs in: {modules[0]}")
    else:
        print("Discovering jobs in:")
        for mod in modules:
            print(f"  {mod}")

    discover_and_import_modules(modules)
    for mod in modules:
        print(f"  - Imported '{mod}'")

    # Resolve Soniq instance from CLI arguments
    try:
        soniq_instance = await resolve_soniq_instance(args)
    except Exception as e:
        print_status(f"Configuration error: {e}", "error")
        return 1

    # Handle queue specification
    if args.queues is None:
        queues = None  # Let run_worker discover all queues
        queue_msg = "all available queues"
    else:
        queues = [q.strip() for q in args.queues.split(",")]
        queue_msg = ", ".join(queues)

    print_status(f"Starting Soniq worker with {args.concurrency} workers", "info")
    print_status(f"Processing queues: {queue_msg}", "info")

    if soniq_instance:
        print_status(
            f"Using instance-based configuration (database: {soniq_instance.settings.database_url})",
            "info",
        )
    else:
        print_status("Using global API configuration", "info")

    try:
        if soniq_instance:
            # Use instance-based API
            await soniq_instance.run_worker(
                concurrency=args.concurrency, queues=queues, run_once=args.run_once
            )
        else:
            # Use global API (which delegates to a Soniq instance internally)
            import soniq

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
        # Clean up instance if used
        if soniq_instance and soniq_instance._is_initialized:
            await soniq_instance.close()

    return 0


async def handle_status_command(args):
    """Handle status command (health + jobs + queues functionality)"""

    try:
        soniq_instance = await resolve_soniq_instance(args)
    except Exception as e:
        print_status(f"Configuration error: {e}", "error")
        return 1

    if soniq_instance is not None:
        print_status(
            f"Using instance-based configuration: {soniq_instance.settings.database_url}",
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

        # 1. Health Check
        try:
            async with app.backend.pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
            if result == 1:
                print_status("Database connection: OK", "success")
            else:
                print_status("Database connection: FAILED", "error")
                return 1
        except Exception as e:
            print_status(f"Health check failed: {e}", "error")
            return 1

        # 2. Queue Statistics
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
                        f"{'Queue':<15} {'Total':<8} {'Queued':<8} {'Done':<8} {'Failed':<8}"
                    )
                    print("-" * 60)
                    for queue in queues:
                        print(
                            f"{queue['queue']:<15} {queue['total_jobs']:<8} {queue['queued']:<8} {queue['done']:<8} {queue['failed']:<8}"
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

        # 3. Worker Summary
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
            # Don't fail the entire status command if worker status fails
            logger.debug(f"Could not get worker summary: {e}")

        # 4. Recent Jobs (if --jobs flag)
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
                            f"{job['id'][:8]:<8} {job_name:<25} {job['status']:<12} {job['queue']:<10}"
                        )
                else:
                    print("  No recent jobs")
            except Exception as e:
                print_status(f"Failed to get recent jobs: {e}", "error")

        return 0
    finally:
        if owns_instance and app._is_initialized:
            await app.close()


async def handle_cli_debug_command(args):
    """Handle CLI debug command - show command registry."""
    from ..registry import get_cli_registry

    print(f"\n{StatusIcon.rocket()} Soniq CLI Debug Information")

    # Command registry status
    registry = get_cli_registry()
    status = registry.get_registry_status()

    print("\nCommand Registry:")
    print(f"  Total commands: {status['total_commands']}")

    if status["categories"]:
        print("  Categories:")
        for category, count in status["categories"].items():
            print(f"    {category}: {count} command{'s' if count != 1 else ''}")

    print("\nRegistered Commands:")
    for category in registry.get_categories():
        commands = registry.get_commands_by_category(category)
        if commands:
            print(f"  {category.upper()}:")
            for cmd in commands:
                aliases_str = (
                    f" (aliases: {', '.join(cmd.aliases)})" if cmd.aliases else ""
                )
                print(f"    - {cmd.name}: {cmd.help}{aliases_str}")

    return 0


async def handle_workers_command(args):
    """Handle workers command (worker monitoring functionality)"""

    try:
        soniq_instance = await resolve_soniq_instance(args)
    except Exception as e:
        print_status(f"Configuration error: {e}", "error")
        return 1

    if soniq_instance is not None:
        print_status(
            f"Using instance-based configuration: {soniq_instance.settings.database_url}",
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

        # Clean up stale workers if requested
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
        if owns_instance and app._is_initialized:
            await app.close()
