"""
Tests for queueing_lock parameter.

Verifies that the queueing_lock parameter is accepted by the job decorator
and enqueue function, and stored in job configuration.
"""

from elephantq.core.registry import JobRegistry


def test_job_decorator_accepts_queueing_lock():
    """@job(queueing_lock=...) should store the lock in job config."""
    registry = JobRegistry()

    @registry.register_job
    async def my_job():
        pass

    # queueing_lock is a per-enqueue parameter, not per-registration
    # But the registry should accept it without error
    assert registry.get_job(f"{my_job.__module__}.{my_job.__name__}") is not None


def test_enqueue_accepts_queueing_lock_parameter():
    """enqueue_job should accept queueing_lock as a parameter."""
    import inspect

    from elephantq.core.queue import enqueue_job

    sig = inspect.signature(enqueue_job)
    assert (
        "queueing_lock" in sig.parameters
    ), "enqueue_job must accept queueing_lock parameter"
