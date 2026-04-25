"""
Unit tests for feature flag gating across optional modules.
"""

import os

import pytest


def _reset_settings_cache():
    import soniq.settings

    soniq.settings._settings = None


def _clear_soniq_env():
    for key in list(os.environ.keys()):
        if key.startswith("SONIQ_"):
            os.environ.pop(key, None)


def _disable_all_feature_flags():
    os.environ["SONIQ_WEBHOOKS_ENABLED"] = "false"
    os.environ["SONIQ_METRICS_ENABLED"] = "false"
    os.environ["SONIQ_LOGGING_ENABLED"] = "false"
    os.environ["SONIQ_DEAD_LETTER_QUEUE_ENABLED"] = "false"
    os.environ["SONIQ_SIGNING_ENABLED"] = "false"
    os.environ["SONIQ_SCHEDULING_ENABLED"] = "false"
    os.environ["SONIQ_DEPENDENCIES_ENABLED"] = "false"
    os.environ["SONIQ_TIMEOUTS_ENABLED"] = "false"


def test_feature_managers_require_flags():
    _clear_soniq_env()
    _disable_all_feature_flags()
    _reset_settings_cache()

    from soniq.features.managers import SoniqFeatures

    features = SoniqFeatures()

    with pytest.raises(RuntimeError, match="Webhooks"):
        _ = features.webhooks
    with pytest.raises(RuntimeError, match="Metrics"):
        _ = features.metrics
    with pytest.raises(RuntimeError, match="Logging"):
        _ = features.logging
    with pytest.raises(RuntimeError, match="Dead letter"):
        _ = features.dead_letter
    with pytest.raises(RuntimeError, match="Signing"):
        _ = features.signing


def test_feature_managers_enabled():
    _clear_soniq_env()
    os.environ["SONIQ_WEBHOOKS_ENABLED"] = "true"
    os.environ["SONIQ_METRICS_ENABLED"] = "true"
    os.environ["SONIQ_LOGGING_ENABLED"] = "true"
    os.environ["SONIQ_DEAD_LETTER_QUEUE_ENABLED"] = "true"
    os.environ["SONIQ_SIGNING_ENABLED"] = "true"
    _reset_settings_cache()

    from soniq.features.managers import SoniqFeatures

    features = SoniqFeatures()

    assert features.webhooks is not None
    assert features.metrics is not None
    assert features.logging is not None
    assert features.dead_letter is not None
    assert features.signing is not None

    # The cron-string DSL in `soniq.schedules` is pure Python with no flag
    # gating - it builds strings. The Scheduler service requires croniter
    # only when a cron schedule is added.
    #
    # Timeouts are enforced inline in the core processor via
    # asyncio.wait_for, gated per-job by the registry's `timeout` or the
    # global `SONIQ_JOB_TIMEOUT` setting. No separate flag.
