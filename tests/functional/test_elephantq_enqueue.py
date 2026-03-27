"""
Test that ElephantQ.enqueue() works with MemoryBackend.

This verifies that enqueue goes through the backend abstraction,
not through raw asyncpg SQL.
"""

import pytest

from elephantq import ElephantQ


@pytest.fixture
async def app():
    app = ElephantQ(backend="memory")
    await app._ensure_initialized()
    yield app
    await app.close()


async def test_enqueue_with_memory_backend(app):
    """Enqueue a job using MemoryBackend — should not crash."""
    executed = []

    @app.job()
    async def greet(name: str):
        executed.append(name)

    job_id = await app.enqueue(greet, name="world")
    assert isinstance(job_id, str)
    assert len(job_id) > 0


async def test_enqueue_and_process_round_trip(app):
    """Enqueue, process with run_worker(run_once=True), verify execution."""
    executed = []

    @app.job()
    async def greet(name: str):
        executed.append(name)

    job_id = await app.enqueue(greet, name="world")
    assert isinstance(job_id, str)

    await app.run_worker(run_once=True)
    assert executed == ["world"]
