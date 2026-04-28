"""``soniq metrics`` - print performance / analytics metrics."""

from __future__ import annotations

import json
from dataclasses import asdict

from soniq import Soniq
from soniq.features.metrics import MetricsService

from ._helpers import database_url_argument, resolve_soniq_instance
from .colors import print_status


def add_metrics_cmd(subparsers) -> None:
    parser = subparsers.add_parser(
        "metrics",
        help="Show Soniq performance metrics",
        description="Display performance metrics and analytics",
    )
    parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument("--hours", type=int, default=24, help="Time range in hours")
    parser.add_argument("--export", help="Export metrics to file")
    database_url_argument(parser)
    parser.set_defaults(func=handle_metrics)


async def handle_metrics(args) -> int:
    # Always resolve to an explicit Soniq instance: either from
    # --database-url or, when absent, from a fresh Soniq() that reads
    # SONIQ_DATABASE_URL from the env. The historical "fall back to the
    # global app" branch is gone - it leaked process-global state into a
    # CLI command that already accepts an explicit URL
    # (`docs/contracts/instance_boundary.md`).
    soniq_instance = await resolve_soniq_instance(args)
    if soniq_instance is None:
        soniq_instance = Soniq()
    print_status(
        f"Using Soniq instance: {soniq_instance.settings.database_url}",
        "info",
    )

    service = MetricsService(soniq_instance)
    metrics = await service.get_system_metrics(timeframe_hours=args.hours)
    payload = asdict(metrics)
    if args.format == "json":
        print(json.dumps(payload, indent=2, default=str))
    else:
        print("Soniq Metrics:")
        for key, value in payload.items():
            print(f"  {key}: {value}")
    return 0
