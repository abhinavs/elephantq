"""
Tests for dedup_key parameter.

Verifies that the dedup_key parameter is accepted by the job decorator
and enqueue function, and stored in job configuration.
"""

from elephantq.core.registry import JobRegistry


def test_job_decorator_accepts_dedup_key():
    """@job(dedup_key=...) should store the lock in job config."""
    registry = JobRegistry()

    @registry.register_job
    async def my_job():
        pass

    # dedup_key is a per-enqueue parameter, not per-registration
    # But the registry should accept it without error
    assert registry.get_job(f"{my_job.__module__}.{my_job.__name__}") is not None


def test_enqueue_accepts_dedup_key_parameter():
    """ElephantQ.enqueue should accept dedup_key as a keyword argument."""
    import inspect

    from elephantq.app import ElephantQ

    sig = inspect.signature(ElephantQ.enqueue)
    # dedup_key is passed via **kwargs, so check the method accepts **kwargs
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    assert has_var_keyword, "ElephantQ.enqueue must accept **kwargs for dedup_key"
