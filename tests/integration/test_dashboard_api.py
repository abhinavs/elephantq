import pytest

from elephantq.settings import configure, get_settings
from elephantq.dashboard.fastapi_app import FASTAPI_AVAILABLE, create_dashboard_app


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
@pytest.mark.asyncio
async def test_dashboard_api_smoke():
    httpx = pytest.importorskip("httpx")
    configure(dashboard_enabled=True)
    get_settings(reload=True)

    app = create_dashboard_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/stats")
        assert resp.status_code == 200

        resp = await client.get("/api/queues")
        assert resp.status_code == 200

        resp = await client.get("/api/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    configure(dashboard_enabled=False)
    get_settings(reload=True)
