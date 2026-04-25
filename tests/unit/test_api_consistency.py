"""
Tests for API consistency between global and instance APIs.
"""

import inspect


def test_list_jobs_default_limit_consistent():
    """
    list_jobs default limit must be the same across global and instance APIs.
    """
    import soniq
    from soniq.app import Soniq

    # Get default limit from global function
    sig_global = inspect.signature(soniq.list_jobs)
    global_default = sig_global.parameters["limit"].default

    # Get default limit from instance method
    sig_instance = inspect.signature(Soniq.list_jobs)
    instance_default = sig_instance.parameters["limit"].default

    assert global_default == instance_default, (
        f"list_jobs default limit inconsistent: "
        f"global={global_default}, instance={instance_default}"
    )


def test_no_features_umbrella():
    """The SoniqFeatures umbrella (and the `features` singleton) is gone.

    Each feature service is now reached via a lazy property on the
    ``Soniq`` instance: ``app.webhooks``, ``app.dead_letter``,
    ``app.scheduler``, ``app.signing``, ``app.logs``,
    ``app.dashboard_data``.
    """
    import soniq.features as feat_pkg

    assert not hasattr(feat_pkg, "SoniqFeatures")
    assert not hasattr(feat_pkg, "EnterpriseFeatures")
    assert not hasattr(feat_pkg, "features")
    assert not hasattr(feat_pkg, "enterprise")
    assert "SoniqFeatures" not in feat_pkg.__all__
    assert "features" not in feat_pkg.__all__
