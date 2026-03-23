"""
Tests that the webhook delivery queue has a max size for backpressure.

Written to verify MED-05: unbounded queue can cause OOM.
"""

import inspect

import pytest


class TestWebhookBackpressure:
    def test_delivery_queue_has_maxsize(self):
        """Webhook delivery queue should have maxsize set."""
        from elephantq.features.webhooks import WebhookDispatcher

        source = inspect.getsource(WebhookDispatcher.__init__)
        assert "maxsize" in source, "delivery_queue must have maxsize for backpressure"
