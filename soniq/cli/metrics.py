"""``soniq metrics`` - print performance / analytics metrics."""

from __future__ import annotations

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
    soniq_instance = await resolve_soniq_instance(args)
    if soniq_instance is not None:
        print_status(
            "Using instance-based configuration: "
            f"{soniq_instance.settings.database_url}",
            "info",
        )
    else:
        print_status("Using global API configuration", "info")

    from dataclasses import asdict

    from soniq.features.metrics import get_system_metrics

    metrics = await get_system_metrics(timeframe_hours=args.hours)
    payload = asdict(metrics)
    if args.format == "json":
        import json

        print(json.dumps(payload, indent=2, default=str))
    else:
        print("Soniq Metrics:")
        for key, value in payload.items():
            print(f"  {key}: {value}")
    return 0
