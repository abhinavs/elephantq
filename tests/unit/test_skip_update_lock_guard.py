"""
Tests that ELEPHANTQ_SKIP_UPDATE_LOCK is only honored in debug/test mode.
"""

import os

import pytest


def test_skip_lock_ignored_in_production(monkeypatch):
    """ELEPHANTQ_SKIP_UPDATE_LOCK must be ignored when environment=production and debug=False."""
    monkeypatch.setenv("ELEPHANTQ_SKIP_UPDATE_LOCK", "true")

    from elephantq.settings import get_settings

    settings = get_settings(reload=True)
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "environment", "production")

    from elephantq.core.processor import _should_skip_update_lock

    assert _should_skip_update_lock() is False


def test_skip_lock_honored_in_debug(monkeypatch):
    """ELEPHANTQ_SKIP_UPDATE_LOCK must be honored when debug=True."""
    monkeypatch.setenv("ELEPHANTQ_SKIP_UPDATE_LOCK", "true")

    from elephantq.settings import get_settings

    settings = get_settings(reload=True)
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "environment", "production")

    from elephantq.core.processor import _should_skip_update_lock

    assert _should_skip_update_lock() is True


def test_skip_lock_honored_in_testing(monkeypatch):
    """ELEPHANTQ_SKIP_UPDATE_LOCK must be honored when environment=testing."""
    monkeypatch.setenv("ELEPHANTQ_SKIP_UPDATE_LOCK", "true")

    from elephantq.settings import get_settings

    settings = get_settings(reload=True)
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "environment", "testing")

    from elephantq.core.processor import _should_skip_update_lock

    assert _should_skip_update_lock() is True


def test_skip_lock_false_when_env_not_set(monkeypatch):
    """When ELEPHANTQ_SKIP_UPDATE_LOCK is not set, lock is always active."""
    monkeypatch.delenv("ELEPHANTQ_SKIP_UPDATE_LOCK", raising=False)

    from elephantq.core.processor import _should_skip_update_lock

    assert _should_skip_update_lock() is False
