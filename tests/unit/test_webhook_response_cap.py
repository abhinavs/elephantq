"""
Tests that webhook response body reads are capped.

Written to verify HIGH-04: response body must be bounded to prevent OOM.
"""

import inspect

import pytest


class TestWebhookResponseCap:
    """Verify webhook response body reads are bounded."""

    def test_no_unbounded_response_text(self):
        """_process_delivery should not use await response.text() unbounded."""
        from elephantq.features.webhooks import WebhookDispatcher

        source = inspect.getsource(WebhookDispatcher._process_delivery)
        # response.text() reads the entire body with no limit
        assert "response.text()" not in source, (
            "Webhook response body is read with unbounded response.text(). "
            "Must use response.content.read(N) with a size cap."
        )

    def test_response_read_has_size_limit(self):
        """_process_delivery should use response.content.read with a size limit."""
        from elephantq.features.webhooks import WebhookDispatcher

        source = inspect.getsource(WebhookDispatcher._process_delivery)
        assert "content.read(" in source, (
            "Webhook response body should use response.content.read(N) with a cap"
        )
