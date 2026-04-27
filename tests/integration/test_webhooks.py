import asyncio

import pytest
from aiohttp import web

import soniq
from soniq.features.webhooks import WebhookEvent


@pytest.mark.asyncio
async def test_webhook_delivery_smoke():
    received = []
    delivered = asyncio.Event()

    async def handler(request):
        payload = await request.json()
        received.append(payload)
        delivered.set()
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_post("/webhook", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}/webhook"

    soniq_app = soniq.get_global_app()
    await soniq_app._ensure_initialized()

    try:
        async with soniq_app.backend._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE TABLE soniq_webhook_deliveries, soniq_webhook_endpoints RESTART IDENTITY CASCADE"
            )

        webhooks = soniq_app.webhooks
        await webhooks.start()
        await webhooks.register(url)

        await webhooks.send_webhook(
            WebhookEvent.JOB_COMPLETED,
            {
                "job_id": "job-123",
                "job_name": "tests.webhook_job",
                "queue": "default",
                "duration_ms": 12.5,
            },
        )

        await asyncio.wait_for(delivered.wait(), timeout=5)
        assert received
        assert received[0]["event"] == "job.completed"
        assert received[0]["data"]["job_id"] == "job-123"
    finally:
        await soniq_app.webhooks.stop()
        await runner.cleanup()
