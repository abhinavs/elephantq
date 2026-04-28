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
    # Deliberate deviation from `cli_app`: metrics never falls back to
    # the process-global app. We always build a fresh, scoped Soniq from
    # --database-url or $SONIQ_DATABASE_URL so this CLI cannot leak
    # process-global state (`docs/contracts/instance_boundary.md`).
    soniq_instance = await resolve_soniq_instance(args)
    owns_instance = soniq_instance is not None
    if soniq_instance is None:
        soniq_instance = Soniq()
        owns_instance = True
    print_status(
        f"Using Soniq instance: {soniq_instance.settings.database_url}",
        "info",
    )

    try:
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
    finally:
        if owns_instance and soniq_instance.is_initialized:
            await soniq_instance.close()
