"""
Tests for elephantq.features.webhooks

Covers webhook delivery retry logic, response body size capping, and
delivery queue backpressure. These tests verify that the WebhookDispatcher
handles failures gracefully, avoids unbounded memory usage from large
responses, and enforces queue limits to prevent OOM under load.
"""

import inspect
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dispatcher():
    registry = MagicMock(spec=WebhookRegistry)
    return WebhookDispatcher(registry=registry)


# ---------------------------------------------------------------------------
# Retry behaviour (TEST-01 / FIX-01)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Response body size cap (HIGH-04)
# ---------------------------------------------------------------------------


class TestWebhookResponseCap:
    """Verify webhook response body reads are bounded."""

    def test_no_unbounded_response_text(self):
        """_process_delivery should not use await response.text() unbounded."""
        source = inspect.getsource(WebhookDispatcher._process_delivery)
        # response.text() reads the entire body with no limit
        assert "response.text()" not in source, (
            "Webhook response body is read with unbounded response.text(). "
            "Must use response.content.read(N) with a size cap."
        )

    def test_response_read_has_size_limit(self):
        """_process_delivery should use response.content.read with a size limit."""
        source = inspect.getsource(WebhookDispatcher._process_delivery)
        assert "content.read(" in source, (
            "Webhook response body should use response.content.read(N) with a cap"
        )


# ---------------------------------------------------------------------------
# Delivery queue backpressure (MED-05)
# ---------------------------------------------------------------------------


class TestWebhookBackpressure:
    def test_delivery_queue_has_maxsize(self):
        """Webhook delivery queue should have maxsize set."""
        source = inspect.getsource(WebhookDispatcher.__init__)
        assert "maxsize" in source, "delivery_queue must have maxsize for backpressure"
