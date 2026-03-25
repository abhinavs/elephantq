"""Recurring jobs example.

Requires: pip install elephantq[scheduling]

Start the scheduler process:
  elephantq scheduler
"""

import asyncio

import elephantq
from elephantq.features.recurring import cron, every


@elephantq.job()
async def daily_report():
    print("Generating daily report")


async def main() -> None:
    await every(10).minutes().schedule(daily_report)
    await cron("0 9 * * *").schedule(daily_report)


if __name__ == "__main__":
    asyncio.run(main())
