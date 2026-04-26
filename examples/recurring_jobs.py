"""Recurring jobs example.

Requires: pip install soniq[scheduling]

Start the scheduler process:
  soniq scheduler
"""

from datetime import timedelta

import soniq
from soniq import cron, daily, every


# Declarative — schedule and registration in one decorator.
@soniq.periodic(cron=daily().at("09:00"), name="reports.daily")
async def daily_report():
    print("Generating daily report")


@soniq.periodic(cron=every(10).minutes(), queue="maintenance", name="cleanup")
async def cleanup():
    print("Running cleanup")


# Sub-minute uses `every=` with a timedelta - cron has no second resolution.
@soniq.periodic(every=timedelta(seconds=30), name="metrics.flush")
async def flush_metrics():
    print("Flushing metrics")


# Plain cron strings still work for cron-literate users.
@soniq.periodic(cron=cron("*/15 * * * *"), name="health.check")
async def health_check():
    print("Health check")


# Imperative form — for dynamic schedules added at runtime.
async def main() -> None:
    @soniq.job(name="ad_hoc_task")
    async def ad_hoc_task():
        print("Ad hoc")

    app = soniq.get_global_app()
    await app.scheduler.add(ad_hoc_task, cron=every(5).minutes())
    await app.scheduler.add(
        ad_hoc_task,
        cron="*/30 * * * *",
        queue="reports",
        priority=10,
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
