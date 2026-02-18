"""
Unit tests for feature flag gating across optional modules.
"""

import os

import pytest


def _reset_settings_cache():
    import elephantq.settings

    elephantq.settings._settings = None


def _clear_elephantq_env():
    for key in list(os.environ.keys()):
        if key.startswith("ELEPHANTQ_"):
            os.environ.pop(key, None)


def _disable_all_feature_flags():
    os.environ["ELEPHANTQ_WEBHOOKS_ENABLED"] = "false"
    os.environ["ELEPHANTQ_METRICS_ENABLED"] = "false"
    os.environ["ELEPHANTQ_LOGGING_ENABLED"] = "false"
    os.environ["ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED"] = "false"
    os.environ["ELEPHANTQ_SIGNING_ENABLED"] = "false"
    os.environ["ELEPHANTQ_SCHEDULING_ENABLED"] = "false"
    os.environ["ELEPHANTQ_DEPENDENCIES_ENABLED"] = "false"
    os.environ["ELEPHANTQ_TIMEOUTS_ENABLED"] = "false"


def test_feature_managers_require_flags():
    _clear_elephantq_env()
    _disable_all_feature_flags()
    _reset_settings_cache()

    from elephantq.features.features import ElephantQFeatures

    features = ElephantQFeatures()

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
    _clear_elephantq_env()
    os.environ["ELEPHANTQ_WEBHOOKS_ENABLED"] = "true"
    os.environ["ELEPHANTQ_METRICS_ENABLED"] = "true"
    os.environ["ELEPHANTQ_LOGGING_ENABLED"] = "true"
    os.environ["ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED"] = "true"
    os.environ["ELEPHANTQ_SIGNING_ENABLED"] = "true"
    _reset_settings_cache()

    from elephantq.features.features import ElephantQFeatures

    features = ElephantQFeatures()

    assert features.webhooks is not None
    assert features.metrics is not None
    assert features.logging is not None
    assert features.dead_letter is not None
    assert features.signing is not None


def test_scheduling_flag_required():
    _clear_elephantq_env()
    _disable_all_feature_flags()
    _reset_settings_cache()

    from elephantq.features import recurring, scheduling

    def noop():
        return None

    with pytest.raises(RuntimeError, match="Advanced scheduling"):
        scheduling.schedule_job(noop)

    with pytest.raises(RuntimeError, match="Recurring scheduler"):
        recurring.daily()


@pytest.mark.asyncio
async def test_dependencies_flag_required():
    _clear_elephantq_env()
    _disable_all_feature_flags()
    _reset_settings_cache()

    from elephantq.features.dependencies import store_job_dependencies

    with pytest.raises(RuntimeError, match="Job dependencies"):
        await store_job_dependencies(
            "00000000-0000-0000-0000-000000000000",
            ["00000000-0000-0000-0000-000000000001"],
        )


@pytest.mark.asyncio
async def test_timeouts_flag_required():
    _clear_elephantq_env()
    _disable_all_feature_flags()
    _reset_settings_cache()

    from elephantq.features.timeout_processor import run_worker_with_timeout

    with pytest.raises(RuntimeError, match="Timeout processing"):
        await run_worker_with_timeout()
