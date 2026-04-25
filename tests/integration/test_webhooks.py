import asyncio

import pytest
from aiohttp import web

import soniq
from soniq.features import webhooks


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

    try:
        await webhooks.start_webhook_system()

        app_for_pool = soniq._get_global_app()
        await app_for_pool._ensure_initialized()
        async with app_for_pool.backend.pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE TABLE soniq_webhook_deliveries, soniq_webhook_endpoints RESTART IDENTITY CASCADE"
            )

        await webhooks.register_webhook(url)

        await webhooks.send_job_completed(
            job_id="job-123",
            job_name="tests.webhook_job",
            queue="default",
            duration_ms=12.5,
        )

        await asyncio.wait_for(delivered.wait(), timeout=5)
        assert received
        assert received[0]["event"] == "job.completed"
        assert received[0]["data"]["job_id"] == "job-123"
    finally:
        await webhooks.stop_webhook_system()
        await runner.cleanup()
