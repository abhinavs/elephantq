"""
Tests for managers.py feature manager facade.

Covers: manager instantiation with feature flags, method delegation pattern.
"""

import os

import pytest

import soniq.settings as settings_module


@pytest.fixture(autouse=True)
def _enable_features(monkeypatch):
    monkeypatch.setenv("SONIQ_WEBHOOKS_ENABLED", "true")
    monkeypatch.setenv("SONIQ_METRICS_ENABLED", "true")
    monkeypatch.setenv("SONIQ_LOGGING_ENABLED", "true")
    monkeypatch.setenv("SONIQ_DEAD_LETTER_QUEUE_ENABLED", "true")
    monkeypatch.setenv("SONIQ_SIGNING_ENABLED", "true")
    settings_module._settings = None
    yield
    settings_module._settings = None


class TestWebhookManager:
    @pytest.mark.skipif(
        not os.environ.get("SONIQ_WEBHOOKS_ENABLED"),
        reason="webhooks not enabled",
    )
    def test_instantiation(self):
        pytest.importorskip("aiohttp")
        from soniq.features.managers import WebhookManager

        mgr = WebhookManager()
        assert mgr._mod is not None


class TestMetricsCollector:
    def test_instantiation(self):
        from soniq.features.managers import MetricsCollector

        mgr = MetricsCollector()
        assert mgr._mod is not None


class TestLoggingManager:
    def test_instantiation(self):
        pytest.importorskip("structlog")
        from soniq.features.managers import LoggingManager

        mgr = LoggingManager()
        assert mgr._mod is not None


class TestDeadLetterManager:
    def test_instantiation(self):
        from soniq.features.managers import DeadLetterManager

        mgr = DeadLetterManager()
        assert mgr._mod is not None


class TestSigningManager:
    def test_instantiation(self):
        pytest.importorskip("cryptography")
        from soniq.features.managers import SigningManager

        mgr = SigningManager()
        assert mgr._mod is not None

    def test_encrypt_decrypt_delegation(self):
        pytest.importorskip("cryptography")
        from soniq.features.managers import SigningManager

        mgr = SigningManager()
        encrypted = mgr.encrypt_secret("test-secret")
        assert encrypted != "test-secret"
        decrypted = mgr.decrypt_secret(encrypted)
        assert decrypted == "test-secret"

    def test_get_manager(self):
        pytest.importorskip("cryptography")
        from soniq.features.managers import SigningManager
        from soniq.features.signing import SecretManager

        mgr = SigningManager()
        secret_mgr = mgr.get_manager()
        assert isinstance(secret_mgr, SecretManager)


class TestSoniqFeatures:
    def test_lazy_init(self):
        from soniq.features.managers import SoniqFeatures

        features = SoniqFeatures()
        assert features._webhooks is None
        assert features._metrics is None
        assert features._signing is None


class TestFeatureDisabled:
    def test_manager_raises_when_feature_disabled(self, monkeypatch):
        monkeypatch.setenv("SONIQ_METRICS_ENABLED", "false")
        settings_module._settings = None

        from soniq.features.managers import MetricsCollector

        with pytest.raises(RuntimeError):
            MetricsCollector()
