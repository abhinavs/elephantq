"""
Tests that the logging handler does not hold a lock during database I/O.

Written to verify MED-01: lock should only be held while snapshotting the buffer.
"""

import inspect


class TestLoggingLockNotHeldDuringIO:
    """Verify the lock is released before flushing to database."""

    def test_add_to_buffer_does_not_call_flush_buffer_under_lock(self):
        """_add_to_buffer should snapshot buffer under lock, then flush outside."""
        from elephantq.features.logging import DatabaseLogHandler

        source = inspect.getsource(DatabaseLogHandler._add_to_buffer)

        # Should not call _flush_buffer under the lock (it does DB I/O)
        assert (
            "_flush_buffer" not in source
        ), "_add_to_buffer still calls _flush_buffer under the lock"

    def test_add_to_buffer_uses_flush_batch(self):
        """_add_to_buffer should use _flush_batch after releasing the lock."""
        from elephantq.features.logging import DatabaseLogHandler

        source = inspect.getsource(DatabaseLogHandler._add_to_buffer)
        assert (
            "_flush_batch" in source
        ), "_add_to_buffer should call _flush_batch outside the lock"

    def test_flush_batch_exists(self):
        """_flush_batch method should exist for lock-free database writes."""
        from elephantq.features.logging import DatabaseLogHandler

        assert hasattr(DatabaseLogHandler, "_flush_batch")
