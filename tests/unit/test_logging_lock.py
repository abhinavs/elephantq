"""
Tests that the logging handler does not block on database I/O during emit().

The 0.0.2 design replaces the old lock+buffer with a bounded asyncio.Queue
plus a single consumer task. emit() pushes to the queue (non-blocking) and
returns; the consumer batches and flushes. These tests pin the contract:
emit() is fire-and-forget, queue overflow degrades to a stderr warning
instead of unbounded task spawning, and a single consumer drives all writes.
"""

import asyncio
import inspect

import pytest


class TestEmitIsNonBlocking:
    """emit() must not perform DB I/O on the calling thread/loop."""

    def test_emit_does_not_call_flush_directly(self):
        from soniq.features.logging import DatabaseLogHandler

        source = inspect.getsource(DatabaseLogHandler.emit)
        # The body of emit should never touch the database.
        assert "_flush_batch" not in source
        assert "executemany" not in source
        assert "get_pool" not in source

    def test_emit_uses_queue_put_nowait(self):
        from soniq.features.logging import DatabaseLogHandler

        source = inspect.getsource(DatabaseLogHandler.emit)
        # Must use the non-blocking queue API; never block on emit.
        assert "put_nowait" in source

    def test_consumer_task_is_lazy(self):
        from soniq.features.logging import DatabaseLogHandler

        source = inspect.getsource(DatabaseLogHandler._ensure_consumer)
        # Consumer is started inside _ensure_consumer and gated on a running
        # event loop; tolerate "no loop" without crashing.
        assert "create_task" in source
        assert "RuntimeError" in source


class TestSingleConsumer:
    """Only one consumer task should drain the queue per handler."""

    @pytest.mark.asyncio
    async def test_repeated_emits_share_one_consumer_task(self):
        from soniq.features.logging import DatabaseLogHandler

        handler = DatabaseLogHandler()

        record = _make_record()
        handler.emit(record)
        first = handler._consumer_task
        handler.emit(record)
        second = handler._consumer_task
        assert first is second, "emit() spawned a second consumer task"

        # Drain the queue and shut the consumer down cleanly so the test
        # leaves no background work pending.
        await handler.close()


class TestQueueOverflow:
    """A full queue should drop records and warn once, not spawn tasks."""

    def test_queue_full_triggers_one_shot_warning(self, capsys):
        from soniq.features.logging import DatabaseLogHandler

        handler = DatabaseLogHandler(queue_max=1)
        # Fill queue without a running loop so consumer never starts.
        record = _make_record()
        try:
            handler._queue.put_nowait("seed")
        except asyncio.QueueFull:
            pass

        handler.emit(record)
        handler.emit(record)
        captured = capsys.readouterr()
        # Exactly one warning across the two overflow emits.
        assert captured.err.count("log queue is full") == 1


def _make_record():
    import logging

    return logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hi",
        args=None,
        exc_info=None,
    )
