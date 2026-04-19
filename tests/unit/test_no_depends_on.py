"""
Verify that depends_on / job dependencies feature has been removed.

It was experimental and unimplemented in the worker - shipping
a feature that doesn't work erodes trust.
"""

import importlib

import pytest


def test_no_dependencies_module():
    """elephantq.features.dependencies should not exist."""
    with pytest.raises(ImportError):
        importlib.import_module("elephantq.features.dependencies")


def test_no_dependencies_in_features_init():
    """dependencies should not be exported from elephantq.features."""
    import elephantq.features as feat

    assert "dependencies" not in feat.__all__


def test_no_dependencies_enabled_setting():
    """dependencies_enabled should not be a setting."""
    from elephantq.settings import ElephantQSettings

    assert (
        not hasattr(ElephantQSettings.model_fields, "dependencies_enabled")
        or "dependencies_enabled" not in ElephantQSettings.model_fields
    )


def test_elephantq_has_no_depends_on_attribute():
    """The package must not expose a depends_on symbol at the top level."""
    import elephantq

    assert not hasattr(elephantq, "depends_on")


def test_from_elephantq_import_depends_on_raises():
    """Direct import of depends_on must fail with ImportError."""
    with pytest.raises(ImportError):
        exec("from elephantq import depends_on", {"__name__": "_probe"})


def test_depends_on_not_in_elephantq_all():
    """depends_on must not appear in elephantq.__all__."""
    import elephantq

    assert "depends_on" not in elephantq.__all__
