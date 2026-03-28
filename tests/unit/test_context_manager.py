"""Test async context manager on ElephantQ."""

from elephantq import ElephantQ


async def test_async_context_manager():
    """ElephantQ should work as an async context manager."""
    async with ElephantQ(backend="memory") as app:
        assert app._is_initialized is True
        assert app._is_closed is False
    assert app._is_closed is True


async def test_context_manager_enqueue_and_process():
    """Full round-trip inside async with block."""
    executed = []

    async with ElephantQ(backend="memory") as app:

        @app.job()
        async def greet(name: str):
            executed.append(name)

        await app.enqueue(greet, name="world")
        await app.run_worker(run_once=True)

    assert executed == ["world"]
    assert app._is_closed
