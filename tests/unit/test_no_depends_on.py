"""
Verify that depends_on / job dependencies feature has been removed.

It was experimental and unimplemented in the worker — shipping
a feature that doesn't work erodes trust.
"""


def test_no_dependencies_module():
    """elephantq.features.dependencies should not exist."""
    import importlib

    with __import__("pytest").raises(ImportError):
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
