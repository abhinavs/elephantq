"""Webhook delivery example.

Start a local webhook receiver (any HTTP server) at http://localhost:8080/webhook
and then run this script.
"""

import elephantq
from elephantq.features import webhooks


async def main() -> None:
    await webhooks.start_webhook_system()

    # Register a webhook endpoint
    await webhooks.register_webhook("http://localhost:8080/webhook")

    # Send a test event
    await webhooks.send_job_completed(
        job_id="job-123",
        job_name="examples.webhook_delivery",
        queue="default",
        duration_ms=10.0,
    )

    await webhooks.stop_webhook_system()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
