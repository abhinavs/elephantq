"""
Unit tests for the signing feature module.
"""

import os

import pytest


def test_signing_module_importable():
    """The signing module should be importable regardless of feature flags."""
    from elephantq.features import signing

    assert signing is not None


def test_secret_manager_requires_cryptography():
    """SecretManager should require the cryptography package."""
    from elephantq.features.signing import SecretManager, _require_cryptography

    # cryptography is installed in dev, so this should work
    _require_cryptography()
    manager = SecretManager()
    assert manager is not None


def test_signing_manager_enabled():
    os.environ["ELEPHANTQ_SIGNING_ENABLED"] = "true"

    import elephantq

    manager = elephantq.features.signing
    assert manager is not None
