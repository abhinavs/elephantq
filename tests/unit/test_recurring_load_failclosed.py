"""
load_jobs() must be fail-closed.

If the DB read or any per-row processing raises, the existing in-memory
state must stay untouched and `_loaded` must remain False so the next
attempt retries from scratch. This guarantees the scheduler never runs
against a half-populated dict.
"""

import pytest

from soniq.features.recurring import EnhancedRecurringManager


class _BoomPool:
    """Fake pool whose acquire() raises on use."""

    class _Conn:
        async def __aenter__(self):
            raise RuntimeError("db unavailable")

        async def __aexit__(self, *_):
            return False

    def acquire(self):
        return self._Conn()


@pytest.mark.asyncio
async def test_load_jobs_failure_leaves_state_untouched(monkeypatch):
    manager = EnhancedRecurringManager()

    # Pre-populate state to prove a failed reload doesn't wipe it.
    manager.jobs = {"existing": {"id": "existing"}}
    # _loaded stays False so the manager attempts a real load.

    async def fake_pool(self=None):
        return _BoomPool()

    # The manager now resolves its pool through the bound Soniq app via
    # `EnhancedRecurringManager._pool`. Replace that method on the instance
    # so the load path hits our exploding pool without touching Postgres.
    manager._pool = fake_pool.__get__(manager)

    with pytest.raises(RuntimeError, match="db unavailable"):
        await manager.load_jobs()

    # Pre-existing state preserved; loaded flag still False so we retry.
    assert manager.jobs == {"existing": {"id": "existing"}}
    assert manager._loaded is False
