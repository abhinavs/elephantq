import asyncio
import json

import pytest
from aiohttp import web

from elephantq.db.connection import get_pool
from elephantq.features import webhooks


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

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE TABLE elephantq_webhook_deliveries, elephantq_webhook_endpoints RESTART IDENTITY CASCADE"
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
