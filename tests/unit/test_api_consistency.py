"""
Tests for API consistency between global and instance APIs.
"""

import inspect


def test_list_jobs_default_limit_consistent():
    """
    list_jobs default limit must be the same across all entry points.
    """
    from elephantq.core.queue import list_jobs as global_list_jobs
    from elephantq.client import ElephantQ

    # Get default limit from global function
    sig_global = inspect.signature(global_list_jobs)
    global_default = sig_global.parameters["limit"].default

    # Get default limit from instance method
    sig_instance = inspect.signature(ElephantQ.list_jobs)
    instance_default = sig_instance.parameters["limit"].default

    assert global_default == instance_default, (
        f"list_jobs default limit inconsistent: "
        f"global={global_default}, instance={instance_default}"
    )
