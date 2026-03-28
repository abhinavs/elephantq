"""
Tests for global API management functions not covered elsewhere.

Covers: cancel_job, retry_job, delete_job, list_jobs, get_job_status,
get_queue_stats, setup, reset via the global convenience API.
"""

from unittest.mock import AsyncMock, patch

import pytest

import elephantq


@pytest.fixture(autouse=True)
def reset_global():
    elephantq._global_app = None
    yield
    elephantq._global_app = None


@pytest.mark.asyncio
async def test_global_get_job_status():
    elephantq.configure(database_url="postgresql://test@localhost/test")
    app = elephantq._get_global_app()
    with patch.object(app, "get_job_status", new_callable=AsyncMock) as mock:
        mock.return_value = {"status": "done", "id": "j1"}
        result = await elephantq.get_job_status("j1")
        mock.assert_called_once_with("j1")
        assert result["status"] == "done"


@pytest.mark.asyncio
async def test_global_cancel_job():
    elephantq.configure(database_url="postgresql://test@localhost/test")
    app = elephantq._get_global_app()
    with patch.object(app, "cancel_job", new_callable=AsyncMock) as mock:
        mock.return_value = True
        result = await elephantq.cancel_job("j1")
        mock.assert_called_once_with("j1")
        assert result is True


@pytest.mark.asyncio
async def test_global_retry_job():
    elephantq.configure(database_url="postgresql://test@localhost/test")
    app = elephantq._get_global_app()
    with patch.object(app, "retry_job", new_callable=AsyncMock) as mock:
        mock.return_value = True
        result = await elephantq.retry_job("j1")
        mock.assert_called_once_with("j1")
        assert result is True


@pytest.mark.asyncio
async def test_global_delete_job():
    elephantq.configure(database_url="postgresql://test@localhost/test")
    app = elephantq._get_global_app()
    with patch.object(app, "delete_job", new_callable=AsyncMock) as mock:
        mock.return_value = True
        result = await elephantq.delete_job("j1")
        mock.assert_called_once_with("j1")
        assert result is True


@pytest.mark.asyncio
async def test_global_list_jobs():
    elephantq.configure(database_url="postgresql://test@localhost/test")
    app = elephantq._get_global_app()
    with patch.object(app, "list_jobs", new_callable=AsyncMock) as mock:
        mock.return_value = [{"id": "j1"}, {"id": "j2"}]
        result = await elephantq.list_jobs(status="done")
        mock.assert_called_once_with(queue=None, status="done", limit=100, offset=0)
        assert len(result) == 2


@pytest.mark.asyncio
async def test_global_get_queue_stats():
    elephantq.configure(database_url="postgresql://test@localhost/test")
    app = elephantq._get_global_app()
    with patch.object(app, "get_queue_stats", new_callable=AsyncMock) as mock:
        mock.return_value = {"queued": 5, "processing": 2}
        result = await elephantq.get_queue_stats()
        mock.assert_called_once()
        assert result["queued"] == 5


@pytest.mark.asyncio
async def test_global_setup():
    elephantq.configure(database_url="postgresql://test@localhost/test")
    app = elephantq._get_global_app()
    with patch.object(app, "_setup", new_callable=AsyncMock) as mock:
        await elephantq._setup()
        mock.assert_called_once()


@pytest.mark.asyncio
async def test_global_reset():
    elephantq.configure(database_url="postgresql://test@localhost/test")
    app = elephantq._get_global_app()
    with patch.object(app, "_reset", new_callable=AsyncMock) as mock:
        await elephantq._reset()
        mock.assert_called_once()
