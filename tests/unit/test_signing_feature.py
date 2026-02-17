"""
Unit tests for the signing feature flag and accessors.
"""

import os

import pytest


def _reset_settings_cache():
    import elephantq.settings

    elephantq.settings._settings = None


def test_signing_manager_requires_flag():
    os.environ.pop("ELEPHANTQ_SIGNING_ENABLED", None)
    _reset_settings_cache()

    import elephantq

    with pytest.raises(ValueError, match="Signing"):
        _ = elephantq.features.signing


def test_signing_manager_enabled():
    os.environ["ELEPHANTQ_SIGNING_ENABLED"] = "true"
    _reset_settings_cache()

    import elephantq

    manager = elephantq.features.signing
    assert manager is not None
