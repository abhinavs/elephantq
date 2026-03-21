"""
TEST-01: Verify WebhookDispatcher._process_delivery() correctly computes
next_retry_at on delivery failure.

Must fail before FIX-01 (asyncio.timedelta → timedelta) and pass after.
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ELEPHANTQ_WEBHOOKS_ENABLED", "true")

from elephantq.features.webhooks import (  # noqa: E402
    WebhookDelivery,
    WebhookDispatcher,
    WebhookEndpoint,
    WebhookRegistry,
)


@pytest.fixture
def dispatcher():
    registry = MagicMock(spec=WebhookRegistry)
    return WebhookDispatcher(registry=registry)


@pytest.mark.asyncio
async def test_delivery_failure_sets_next_retry_at(dispatcher):
    """When a webhook delivery fails with retries remaining,
    next_retry_at should be set to a future datetime using timedelta."""

    endpoint = MagicMock(spec=WebhookEndpoint)
    endpoint.url = "https://hooks.example.com/test"
    endpoint.plaintext_secret = None
    endpoint.headers = {}
    endpoint.id = "ep-1"
    endpoint.active = True
    endpoint.timeout_seconds = 5

    delivery = MagicMock(spec=WebhookDelivery)
    delivery.id = "del-1"
    delivery.attempts = 0
    delivery.max_attempts = 3
    delivery.status = "pending"
    delivery.endpoint_id = "ep-1"
    delivery.payload = {"event": "job.failed"}
    delivery.event = "job.failed"
    delivery.next_retry_at = None
    delivery.response_status = None
    delivery.response_body = None
    delivery.last_error = None
    delivery.delivered_at = None

    # Make the registry return our endpoint
    dispatcher.registry.get_endpoint = AsyncMock(return_value=endpoint)
    dispatcher._save_delivery_record = AsyncMock()

    # Mock aiohttp to raise on send so delivery fails
    mock_response = AsyncMock()
    mock_response.status = 500
    mock_response.text = AsyncMock(return_value="Internal Server Error")
    mock_response.request_info = MagicMock()
    mock_response.history = ()

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        # This line will fail with AttributeError: module 'asyncio' has no
        # attribute 'timedelta' before FIX-01
        await dispatcher._process_delivery(delivery)

    # After a failed delivery with retries remaining, next_retry_at should be set
    assert delivery.next_retry_at is not None
    assert isinstance(delivery.next_retry_at, datetime)
    assert delivery.status == "pending"
