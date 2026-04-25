"""
Tests for multi-scheduler safety.

When multiple scheduler processes check the same recurring job simultaneously,
only one should fire it per period. The atomic claim is now bundled with the
enqueue and bookkeeping inside a single Postgres transaction; this test only
verifies the public-shape contract that `_execute_job` exists and is async.
The actual claim/enqueue atomicity is exercised against a live database in
the integration suite (`tests/integration/test_leader_election.py`).
"""

import inspect


def test_execute_job_is_async_method_on_scheduler():
    from soniq.features.recurring import EnhancedRecurringScheduler

    scheduler = EnhancedRecurringScheduler()
    assert hasattr(scheduler, "_execute_job"), (
        "EnhancedRecurringScheduler must have _execute_job for the atomic "
        "claim+enqueue+record path."
    )
    assert inspect.iscoroutinefunction(
        scheduler._execute_job
    ), "_execute_job must be async."
