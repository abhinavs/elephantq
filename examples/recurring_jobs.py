"""Recurring jobs example.

Requires: pip install soniq[scheduling]

Start the scheduler process:
  soniq scheduler
"""

import soniq


# Declarative — schedule is defined at decoration time
@soniq.periodic(cron="0 9 * * *")
async def daily_report():
    print("Generating daily report")


@soniq.periodic(every_minutes=10, queue="maintenance")
async def cleanup():
    print("Running cleanup")


# Programmatic — for dynamic schedules
async def main() -> None:
    from soniq import cron, every

    @soniq.job(name="ad_hoc_task")
    async def ad_hoc_task():
        print("Ad hoc")

    await every(5).minutes().schedule(ad_hoc_task)
    await cron("*/30 * * * *").schedule(ad_hoc_task)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
