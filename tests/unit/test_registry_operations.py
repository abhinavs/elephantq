"""
Tests for JobRegistry operations not covered elsewhere.

Covers: get_all_jobs, get_jobs_by_queue, clear, remove_job, list_jobs,
__len__, __contains__.
"""

from soniq.core.registry import JobRegistry


def _make_registry_with_jobs():
    """Helper to create a registry with a few registered jobs."""
    registry = JobRegistry()

    async def task_a():
        pass

    async def task_b():
        pass

    async def task_c():
        pass

    registry.register_job(task_a, queue="emails")
    registry.register_job(task_b, queue="emails")
    registry.register_job(task_c, queue="billing")
    return registry


def test_get_all_jobs_returns_job_names():
    registry = _make_registry_with_jobs()
    names = registry.get_all_jobs()
    assert len(names) == 3
    assert all(isinstance(n, str) for n in names)


def test_get_jobs_by_queue_filters_correctly():
    registry = _make_registry_with_jobs()
    email_jobs = registry.get_jobs_by_queue("emails")
    assert len(email_jobs) == 2
    billing_jobs = registry.get_jobs_by_queue("billing")
    assert len(billing_jobs) == 1
    empty = registry.get_jobs_by_queue("nonexistent")
    assert empty == []


def test_clear_removes_all_jobs():
    registry = _make_registry_with_jobs()
    assert len(registry) > 0
    registry.clear()
    assert len(registry) == 0
    assert registry.get_all_jobs() == []


def test_remove_job_returns_true_for_existing():
    registry = _make_registry_with_jobs()
    names = registry.get_all_jobs()
    assert registry.remove_job(names[0]) is True
    assert len(registry) == 2


def test_remove_job_returns_false_for_missing():
    registry = _make_registry_with_jobs()
    assert registry.remove_job("nonexistent.job") is False


def test_list_jobs_returns_copy_of_configs():
    registry = _make_registry_with_jobs()
    jobs = registry.list_jobs()
    assert isinstance(jobs, dict)
    assert len(jobs) == 3
    # Verify it's a copy, not a reference
    jobs["new_key"] = "value"
    assert "new_key" not in registry.list_jobs()


def test_len_reflects_registered_count():
    registry = JobRegistry()
    assert len(registry) == 0

    async def task():
        pass

    registry.register_job(task)
    assert len(registry) == 1


def test_contains_checks_job_names():
    registry = JobRegistry()

    async def task():
        pass

    wrapped = registry.register_job(task)
    job_name = wrapped._soniq_name
    assert job_name in registry
    assert "nonexistent.task" not in registry


def test_register_job_stores_all_config_fields():
    registry = JobRegistry()

    async def my_job():
        pass

    registry.register_job(
        my_job,
        retries=5,
        priority=50,
        queue="special",
        unique=True,
        retry_delay=[1, 2, 5],
        retry_backoff=True,
        retry_max_delay=30,
        timeout=60,
    )
    name = f"{my_job.__module__}.{my_job.__name__}"
    config = registry.get_job(name)
    assert config["max_retries"] == 5
    assert config["priority"] == 50
    assert config["queue"] == "special"
    assert config["unique"] is True
    assert config["retry_delay"] == [1, 2, 5]
    assert config["retry_backoff"] is True
    assert config["retry_max_delay"] == 30
    assert config["timeout"] == 60


def test_max_retries_overrides_retries():
    registry = JobRegistry()

    async def my_job():
        pass

    registry.register_job(my_job, retries=3, max_retries=10)
    name = f"{my_job.__module__}.{my_job.__name__}"
    assert registry.get_job(name)["max_retries"] == 10


def test_validate_alias_for_args_model():
    from pydantic import BaseModel

    class MyModel(BaseModel):
        x: int

    registry = JobRegistry()

    async def my_job():
        pass

    registry.register_job(my_job, validate=MyModel)
    name = f"{my_job.__module__}.{my_job.__name__}"
    assert registry.get_job(name)["args_model"] is MyModel


# ---------------------------------------------------------------------------
# Mandatory name= behaviour (PR 4 / TODO 1.4 / plan section 15)
#
# These tests assert the new contract: register_job requires an explicit
# `name=` kwarg, validates it against the task_name_pattern, and stores it
# verbatim as the registry key. Tests above this section that call
# register_job(...) without name= are expected to fail until PR 6 migrates
# them; that breakage is accepted per impl_plan_multi.md section 3.
# ---------------------------------------------------------------------------


import os  # noqa: E402

import pytest  # noqa: E402

from tests.db_utils import TEST_DATABASE_URL  # noqa: E402

os.environ.setdefault("SONIQ_DATABASE_URL", TEST_DATABASE_URL)

from soniq.errors import SONIQ_INVALID_TASK_NAME, SoniqError  # noqa: E402


class TestMandatoryName:
    def test_explicit_name_is_used_as_registry_key(self):
        registry = JobRegistry()

        async def some_func():
            pass

        wrapped = registry.register_job(some_func, name="billing.foo")
        assert "billing.foo" in registry
        assert wrapped._soniq_name == "billing.foo"

    def test_explicit_name_does_not_use_module_qualname(self):
        registry = JobRegistry()

        async def some_func():
            pass

        registry.register_job(some_func, name="billing.foo")
        derived = f"{some_func.__module__}.{some_func.__name__}"
        # The derived module-path name must not appear in the registry.
        assert derived not in registry or derived == "billing.foo"

    def test_missing_name_raises(self):
        registry = JobRegistry()

        async def some_func():
            pass

        with pytest.raises(TypeError):
            registry.register_job(some_func)  # type: ignore[call-arg]

    def test_empty_name_raises_invalid_task_name(self):
        registry = JobRegistry()

        async def some_func():
            pass

        with pytest.raises(SoniqError) as exc_info:
            registry.register_job(some_func, name="")
        assert exc_info.value.error_code == SONIQ_INVALID_TASK_NAME

    @pytest.mark.parametrize(
        "bad_name",
        ["Bad Name", "Has.Caps", ".leading", "trailing.", "double..dot", "dash-name"],
    )
    def test_bad_name_format_raises_invalid_task_name(self, bad_name):
        registry = JobRegistry()

        async def some_func():
            pass

        with pytest.raises(SoniqError) as exc_info:
            registry.register_job(some_func, name=bad_name)
        assert exc_info.value.error_code == SONIQ_INVALID_TASK_NAME

    def test_soniq_name_attribute_matches_registry_key(self):
        registry = JobRegistry()

        async def some_func():
            pass

        wrapped = registry.register_job(some_func, name="a.b.c")
        assert wrapped._soniq_name == "a.b.c"
        assert wrapped._soniq_name in registry

    def test_app_job_decorator_requires_name(self):
        """`@app.job(...)` without name= raises at decoration time."""
        from soniq import Soniq

        app = Soniq(database_url=TEST_DATABASE_URL)

        with pytest.raises((SoniqError, TypeError)):

            @app.job()  # type: ignore[call-arg]
            async def f():
                pass

    def test_app_job_decorator_accepts_explicit_name(self):
        from soniq import Soniq

        app = Soniq(database_url=TEST_DATABASE_URL)

        @app.job(name="billing.test.foo")
        async def f():
            pass

        assert f._soniq_name == "billing.test.foo"
        assert "billing.test.foo" in app._job_registry

    def test_module_level_soniq_job_requires_name(self):
        """Same contract for the global ``@soniq.job`` decorator."""
        import soniq

        with pytest.raises((SoniqError, TypeError)):

            @soniq.job()  # type: ignore[call-arg]
            async def f():
                pass
