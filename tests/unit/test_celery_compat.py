"""
Tests for the soniq.celery compatibility layer.

The compat module is a Soniq subclass that exposes ``@app.task`` as an
alias for ``@app.job``. It exists to ease migration from Celery, not as
a permanent surface.
"""

import pytest

from soniq.celery import Soniq as CelerySoniq


@pytest.mark.asyncio
async def test_task_decorator_registers_job_like_job_does():
    app = CelerySoniq(backend="memory")

    @app.task(name="welcome.send")
    async def send_welcome(to: str):
        return f"sent to {to}"

    job_id = await app.enqueue("welcome.send", args={"to": "dev@example.com"})
    assert job_id is not None

    record = await app.get_job(job_id)
    assert record["status"] == "queued"

    await app.close()


@pytest.mark.asyncio
async def test_task_bare_decorator_form_works():
    """@app.task (no parens) must register exactly like @app.job."""
    app = CelerySoniq(backend="memory")

    @app.task
    async def bare_task():
        return "ok"

    # Enqueueing by function reference exercises the same registry the
    # decorator wrote into. We don't assert on the auto-generated name
    # because that's a Soniq internal, not part of the celery-compat API.
    job_id = await app.enqueue(bare_task)
    assert job_id is not None

    await app.close()


@pytest.mark.asyncio
async def test_celery_soniq_is_a_soniq_subclass():
    """A CelerySoniq instance must be a drop-in replacement for Soniq."""
    from soniq import Soniq

    app = CelerySoniq(backend="memory")
    assert isinstance(app, Soniq)
    await app.close()


@pytest.mark.asyncio
async def test_no_delay_or_apply_async_aliases():
    """
    .delay() and .apply_async() are intentionally NOT provided. They would
    hide the await that Soniq's async-native enqueue requires. The
    migration guide instructs users to rewrite those call sites.
    """
    app = CelerySoniq(backend="memory")

    @app.task(name="t")
    async def t():
        return None

    # Decorated function should not have .delay or .apply_async attrs
    assert not hasattr(t, "delay")
    assert not hasattr(t, "apply_async")
    await app.close()
