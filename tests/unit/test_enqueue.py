"""
Tests for the new Soniq.enqueue (name_or_ref, *, args=dict, ...) shape.

Phase 1 / PR 5: string-name path only. The TaskRef path lands in PR 13.

These tests run against MemoryBackend so they have no Postgres dependency.
"""

import os

import pytest

from tests.db_utils import TEST_DATABASE_URL

os.environ.setdefault("SONIQ_DATABASE_URL", TEST_DATABASE_URL)

from soniq.errors import (  # noqa: E402
    SONIQ_INVALID_TASK_NAME,
    SONIQ_TASK_ARGS_INVALID,
    SONIQ_UNKNOWN_TASK_NAME,
    SoniqError,
)
from soniq.testing import make_app  # noqa: E402


@pytest.fixture
def app():
    """A fresh in-memory Soniq with strict validation (the production default)."""
    return make_app(enqueue_validation="strict")


@pytest.fixture
def lenient_app():
    """In-memory Soniq with enqueue_validation='none' for pure-producer tests."""
    return make_app(enqueue_validation="none")


# ---------------------------------------------------------------------------
# Basic shape: registered task, default mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_writes_row_for_registered_task(app):
    @app.job(name="billing.foo")
    async def foo(order_id: str):
        pass

    job_id = await app.enqueue("billing.foo", args={"order_id": "o1"})
    assert isinstance(job_id, str) and len(job_id) > 0

    rows = await app.list_jobs()
    assert any(r["job_name"] == "billing.foo" for r in rows)


@pytest.mark.asyncio
async def test_enqueue_returns_uuid_string(app):
    @app.job(name="billing.bar")
    async def bar():
        pass

    job_id = await app.enqueue("billing.bar", args={})
    # UUID4 length is 36 characters with hyphens.
    assert len(job_id) == 36
    assert job_id.count("-") == 4


# ---------------------------------------------------------------------------
# Validation modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_mode_raises_for_unregistered_name_and_writes_nothing(app):
    with pytest.raises(SoniqError) as exc_info:
        await app.enqueue("billing.unknown", args={})
    assert exc_info.value.error_code == SONIQ_UNKNOWN_TASK_NAME

    rows = await app.list_jobs()
    # Crucially, no row was written.
    assert not any(r["job_name"] == "billing.unknown" for r in rows)


@pytest.mark.asyncio
async def test_none_mode_writes_row_for_unregistered_name(lenient_app):
    job_id = await lenient_app.enqueue("billing.unknown", args={"x": 1})
    rows = await lenient_app.list_jobs()
    assert any(r["id"] == job_id and r["job_name"] == "billing.unknown" for r in rows)


@pytest.mark.asyncio
async def test_warn_mode_logs_and_writes(caplog):
    import logging

    app = make_app(enqueue_validation="warn")
    with caplog.at_level(logging.WARNING, logger="soniq.app"):
        job_id = await app.enqueue("billing.unknown", args={})
    assert job_id
    rows = await app.list_jobs()
    assert any(r["job_name"] == "billing.unknown" for r in rows)
    assert any("billing.unknown" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Name-pattern validation (always on, regardless of mode)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_name", ["Bad Name", ".leading", "trailing.", "double..dot", "Has.Caps", ""]
)
async def test_invalid_name_format_raises_invalid_task_name(lenient_app, bad_name):
    with pytest.raises(SoniqError) as exc_info:
        await lenient_app.enqueue(bad_name, args={})
    assert exc_info.value.error_code == SONIQ_INVALID_TASK_NAME


@pytest.mark.asyncio
async def test_non_string_first_arg_raises_invalid_task_name(lenient_app):
    with pytest.raises(SoniqError) as exc_info:
        await lenient_app.enqueue(123, args={})  # type: ignore[arg-type]
    assert exc_info.value.error_code == SONIQ_INVALID_TASK_NAME


# ---------------------------------------------------------------------------
# args= is an explicit dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_args_defaults_to_empty_dict(app):
    @app.job(name="billing.empty")
    async def empty():
        pass

    job_id = await app.enqueue("billing.empty")
    rows = await app.list_jobs()
    row = next(r for r in rows if r["id"] == job_id)
    assert row["args"] == {}


@pytest.mark.asyncio
async def test_args_must_be_dict(app):
    @app.job(name="billing.foo")
    async def foo():
        pass

    with pytest.raises(TypeError):
        await app.enqueue("billing.foo", args=["x", "y"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Defaults from the registered job_meta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registered_defaults_applied_when_unset(app):
    @app.job(name="billing.priority", priority=20, queue="urgent", unique=True)
    async def priority_job(x: int):
        pass

    job_id = await app.enqueue("billing.priority", args={"x": 1})
    rows = await app.list_jobs()
    row = next(r for r in rows if r["id"] == job_id)
    assert row["priority"] == 20
    assert row["queue"] == "urgent"
    assert row["unique_job"] is True


@pytest.mark.asyncio
async def test_explicit_kwargs_override_registered_defaults(app):
    @app.job(name="billing.override", priority=20, queue="urgent")
    async def override_job():
        pass

    job_id = await app.enqueue(
        "billing.override", args={}, priority=5, queue="critical"
    )
    rows = await app.list_jobs()
    row = next(r for r in rows if r["id"] == job_id)
    assert row["priority"] == 5
    assert row["queue"] == "critical"


@pytest.mark.asyncio
async def test_unregistered_name_uses_system_defaults(lenient_app):
    """Pin the system defaults for the pure-producer (unregistered) path so a
    future refactor cannot silently change the on-the-wire shape."""
    job_id = await lenient_app.enqueue("billing.pure_producer", args={"x": 1})
    rows = await lenient_app.list_jobs()
    row = next(r for r in rows if r["id"] == job_id)
    assert row["priority"] == 100
    assert row["queue"] == "default"
    assert row["unique_job"] is False


# ---------------------------------------------------------------------------
# args_model validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_args_model_invalid_raises_task_args_invalid(app):
    from pydantic import BaseModel

    class InvoiceArgs(BaseModel):
        order_id: str
        customer: str

    @app.job(name="billing.invoice", validate=InvoiceArgs)
    async def invoice(order_id: str, customer: str):
        pass

    with pytest.raises(SoniqError) as exc_info:
        await app.enqueue(
            "billing.invoice", args={"order_id": "o1"}
        )  # missing customer
    assert exc_info.value.error_code == SONIQ_TASK_ARGS_INVALID

    rows = await app.list_jobs()
    assert not any(r["job_name"] == "billing.invoice" for r in rows)


@pytest.mark.asyncio
async def test_args_model_valid_passes(app):
    from pydantic import BaseModel

    class InvoiceArgs(BaseModel):
        order_id: str

    @app.job(name="billing.invoice2", validate=InvoiceArgs)
    async def invoice(order_id: str):
        pass

    job_id = await app.enqueue("billing.invoice2", args={"order_id": "o1"})
    assert job_id


# ---------------------------------------------------------------------------
# Module-level soniq.enqueue routes through the active app
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_module_level_enqueue_routes_to_active_app():
    """Module-level soniq.enqueue routes through the active-app
    contextvar when one is set. Use the memory backend so this test
    does not depend on the Postgres test database schema."""
    import soniq
    from soniq._active import _active_app

    app = make_app(enqueue_validation="none")
    token = _active_app.set(app)
    try:
        job_id = await soniq.enqueue("billing.modlevel", args={"x": 1})
    finally:
        _active_app.reset(token)
    assert isinstance(job_id, str) and len(job_id) == 36
    rows = await app.list_jobs()
    assert any(r["id"] == job_id for r in rows)


# ---------------------------------------------------------------------------
# Transactional enqueue surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transactional_enqueue_unsupported_on_memory_backend(lenient_app):
    """MemoryBackend does not support transactional enqueue; assert the
    helpful error message from the wrapper."""
    with pytest.raises(ValueError, match="Transactional enqueue"):
        await lenient_app.enqueue(
            "billing.tx", args={}, connection=object()  # any non-None
        )


# ---------------------------------------------------------------------------
# Strict-mode registry-table boundary (load-bearing)
#
# This test locks the architectural invariant that the enqueue path NEVER
# consults the (future, phase-3) soniq_task_registry DB table. It mocks a
# backend.list_registered_task_names() that returns the name, and verifies
# that strict-mode enqueue still raises SONIQ_UNKNOWN_TASK_NAME because the
# *in-process* registry is empty. If a future refactor adds a fallback path
# that reads from the DB table, this test fails.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_mode_does_not_consult_backend_registry_table():
    app = make_app(enqueue_validation="strict")
    backend_calls = []

    async def list_registered_task_names_spy():
        backend_calls.append("list_registered_task_names")
        return [{"task_name": "billing.from_db", "worker_id": "w1"}]

    # Initialize so we can patch the backend.
    await app._ensure_initialized()
    app._backend.list_registered_task_names = list_registered_task_names_spy  # type: ignore[attr-defined]

    with pytest.raises(SoniqError) as exc_info:
        await app.enqueue("billing.from_db", args={})

    assert exc_info.value.error_code == SONIQ_UNKNOWN_TASK_NAME
    # The boundary: enqueue must not call the registry-table reader.
    assert backend_calls == []


@pytest.mark.asyncio
async def test_app_module_does_not_import_registry_table_reader():
    """Cheap structural check: nothing in soniq/app.py mentions
    `list_registered_task_names`, so future contributors must edit this
    test (and read the boundary doc) to add a caller."""
    import inspect

    import soniq.app as app_mod

    src = inspect.getsource(app_mod)
    assert "list_registered_task_names" not in src, (
        "soniq/app.py must not reference list_registered_task_names; "
        "the registry table is observability only (plan section 14.4)."
    )


# ---------------------------------------------------------------------------
# TaskRef arm (PR 13 / TODO 2.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_taskref_writes_row_using_ref_name():
    from soniq import task_ref

    app = make_app(enqueue_validation="strict")
    ref = task_ref(name="billing.taskref.foo")

    job_id = await app.enqueue(ref, args={"x": 1})
    rows = await app.list_jobs()
    row = next(r for r in rows if r["id"] == job_id)
    assert row["job_name"] == "billing.taskref.foo"
    assert row["args"] == {"x": 1}


@pytest.mark.asyncio
async def test_enqueue_taskref_skips_strict_registry_check():
    """The TaskRef arm short-circuits SONIQ_ENQUEUE_VALIDATION. Even in
    strict mode a TaskRef enqueue succeeds without registration."""
    from soniq import task_ref

    app = make_app(enqueue_validation="strict")
    ref = task_ref(name="billing.taskref.unregistered")

    # No @app.job for this name. The ref *is* the producer-side
    # declaration, so strict mode does not block.
    job_id = await app.enqueue(ref, args={})
    assert job_id


@pytest.mark.asyncio
async def test_enqueue_taskref_args_model_invalid_raises():
    from pydantic import BaseModel

    from soniq import task_ref

    class FooArgs(BaseModel):
        order_id: str

    app = make_app(enqueue_validation="strict")
    ref = task_ref(name="billing.taskref.invoice", args_model=FooArgs)

    with pytest.raises(SoniqError) as exc_info:
        await app.enqueue(ref, args={"order_id": 12345})  # int, not str
    assert exc_info.value.error_code == SONIQ_TASK_ARGS_INVALID

    rows = await app.list_jobs()
    assert not any(r["job_name"] == "billing.taskref.invoice" for r in rows)


@pytest.mark.asyncio
async def test_enqueue_taskref_args_model_valid_writes():
    from pydantic import BaseModel

    from soniq import task_ref

    class FooArgs(BaseModel):
        order_id: str

    app = make_app(enqueue_validation="strict")
    ref = task_ref(name="billing.taskref.valid", args_model=FooArgs)

    job_id = await app.enqueue(ref, args={"order_id": "o1"})
    assert job_id


@pytest.mark.asyncio
async def test_enqueue_taskref_queue_precedence_chain():
    """Queue precedence: explicit queue= > ref.default_queue > system
    default. Single test pinning all three sub-cases in one place so the
    chain cannot fragment across files (per todo_multi.md 2.2)."""
    from soniq import task_ref

    app = make_app(enqueue_validation="none")

    # Case 1: explicit queue= overrides ref.default_queue.
    ref_with_default = task_ref(name="billing.q.case1", default_queue="billing")
    job_id_1 = await app.enqueue(ref_with_default, args={}, queue="urgent")
    rows = await app.list_jobs()
    row = next(r for r in rows if r["id"] == job_id_1)
    assert row["queue"] == "urgent"

    # Case 2: ref.default_queue used when no explicit queue=.
    ref_with_default_2 = task_ref(name="billing.q.case2", default_queue="billing")
    job_id_2 = await app.enqueue(ref_with_default_2, args={})
    rows = await app.list_jobs()
    row = next(r for r in rows if r["id"] == job_id_2)
    assert row["queue"] == "billing"

    # Case 3: system default when ref has no default_queue and no
    # explicit queue=.
    ref_no_default = task_ref(name="billing.q.case3")
    job_id_3 = await app.enqueue(ref_no_default, args={})
    rows = await app.list_jobs()
    row = next(r for r in rows if r["id"] == job_id_3)
    assert row["queue"] == "default"


@pytest.mark.asyncio
async def test_enqueue_taskref_with_registered_handler_uses_ref_args_model():
    """When both the consumer's @app.job(validate=...) AND the producer's
    TaskRef(args_model=...) are present, the ref's model is the
    producer-side contract. We exercise this by registering a handler
    with a different (looser) model and watching the ref's model fail
    first."""
    from pydantic import BaseModel

    from soniq import task_ref

    class StrictArgs(BaseModel):
        order_id: str

    class LooserArgs(BaseModel):
        order_id: object  # accepts any type

    app = make_app(enqueue_validation="strict")

    @app.job(name="billing.taskref.both", validate=LooserArgs)
    async def handler(order_id):
        pass

    ref = task_ref(name="billing.taskref.both", args_model=StrictArgs)

    # int order_id passes the looser model but fails the strict ref.
    with pytest.raises(SoniqError) as exc_info:
        await app.enqueue(ref, args={"order_id": 123})
    assert exc_info.value.error_code == SONIQ_TASK_ARGS_INVALID
