"""
Tests for API consistency between global and instance APIs.
"""

import inspect


def test_list_jobs_default_limit_consistent():
    """
    list_jobs default limit must be the same across global and instance APIs.
    """
    import elephantq
    from elephantq.app import ElephantQ

    # Get default limit from global function
    sig_global = inspect.signature(elephantq.list_jobs)
    global_default = sig_global.parameters["limit"].default

    # Get default limit from instance method
    sig_instance = inspect.signature(ElephantQ.list_jobs)
    instance_default = sig_instance.parameters["limit"].default

    assert global_default == instance_default, (
        f"list_jobs default limit inconsistent: "
        f"global={global_default}, instance={instance_default}"
    )


def test_no_enterprise_aliases_in_features():
    """EnterpriseFeatures and enterprise aliases must not exist."""
    from elephantq.features import features as features_mod

    assert not hasattr(
        features_mod, "EnterpriseFeatures"
    ), "EnterpriseFeatures alias should be removed"
    assert not hasattr(features_mod, "enterprise"), "enterprise alias should be removed"

    import elephantq.features as feat_pkg

    assert "EnterpriseFeatures" not in feat_pkg.__all__
    assert "enterprise" not in feat_pkg.__all__
