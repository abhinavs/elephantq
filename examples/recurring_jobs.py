"""Recurring jobs example.

Requires: pip install elephantq[scheduling]

Start the scheduler process:
  elephantq scheduler
"""

import elephantq


# Declarative — schedule is defined at decoration time
@elephantq.periodic(cron="0 9 * * *")
async def daily_report():
    print("Generating daily report")


@elephantq.periodic(every_minutes=10, queue="maintenance")
async def cleanup():
    print("Running cleanup")


# Programmatic — for dynamic schedules
async def main() -> None:
    from elephantq import cron, every

    @elephantq.job()
    async def ad_hoc_task():
        print("Ad hoc")

    await every(5).minutes().schedule(ad_hoc_task)
    await cron("*/30 * * * *").schedule(ad_hoc_task)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
