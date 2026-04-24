"""
Minimal demonstration that a job's return value is persisted and retrievable.

Run:
    ELEPHANTQ_DATABASE_URL=postgresql://postgres@localhost/elephantq \\
        python examples/job_returns_value.py
"""

import asyncio
import os

import elephantq


@elephantq.job()
async def compute_summary(a: int, b: int):
    return {"total": a + b, "inputs": [a, b]}


async def main():
    database_url = os.environ.get(
        "ELEPHANTQ_DATABASE_URL", "postgresql://postgres@localhost/elephantq"
    )
    await elephantq.configure(database_url=database_url)

    await elephantq._setup()

    job_id = await elephantq.enqueue(compute_summary, a=7, b=35)
    await elephantq.run_worker(run_once=True)

    result = await elephantq.get_result(job_id)
    print(f"job_id={job_id}")
    print(f"result={result}")
    assert result == {"total": 42, "inputs": [7, 35]}, f"unexpected result: {result}"


if __name__ == "__main__":
    asyncio.run(main())
