"""Instance-based API example.

Shows ElephantQ used as an application object instead of the global API.
Run with: python examples/instance_api.py
"""

import asyncio

from elephantq import ElephantQ, JobContext

app = ElephantQ(database_url="postgresql://localhost/myapp")


@app.job(queue="notifications", retries=2)
async def send_notification(user_id: int, message: str, ctx: JobContext):
    print(f"[job {ctx.job_id}, attempt {ctx.attempt}] notify user {user_id}: {message}")


@app.job(queue="reports")
async def generate_report(report_type: str):
    print(f"Generating {report_type} report")


async def main():
    # Enqueue a couple of jobs
    job_id = await app.enqueue(send_notification, user_id=42, message="Welcome aboard")
    print(f"Enqueued notification: {job_id}")

    await app.enqueue(generate_report, report_type="monthly")

    # Process all queued jobs and exit
    await app.run_worker(run_once=True, queues=["notifications", "reports"])

    await app.close()


if __name__ == "__main__":
    asyncio.run(main())
