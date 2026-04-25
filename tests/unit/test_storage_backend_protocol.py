"""
Tests for the StorageBackend protocol definition.

Verifies the protocol exists, is runtime-checkable, and defines
the correct method signatures.
"""

import inspect


def test_storage_backend_importable():
    from soniq.backends import StorageBackend

    assert StorageBackend is not None


def test_storage_backend_is_runtime_checkable():
    from soniq.backends import StorageBackend

    # runtime_checkable protocols support isinstance checks
    assert hasattr(StorageBackend, "__protocol_attrs__") or hasattr(
        StorageBackend, "__abstractmethods__"
    )


def test_storage_backend_has_lifecycle_methods():
    from soniq.backends import StorageBackend

    members = _get_protocol_methods(StorageBackend)
    assert "initialize" in members
    assert "close" in members


def test_storage_backend_has_job_crud_methods():
    from soniq.backends import StorageBackend

    members = _get_protocol_methods(StorageBackend)
    assert "create_job" in members
    assert "get_job" in members
    assert "list_jobs" in members
    assert "cancel_job" in members
    assert "retry_job" in members
    assert "delete_job" in members
    assert "get_queue_stats" in members


def test_storage_backend_has_dequeue_methods():
    from soniq.backends import StorageBackend

    members = _get_protocol_methods(StorageBackend)
    assert "fetch_and_lock_job" in members
    assert "notify_new_job" in members
    assert "listen_for_jobs" in members


def test_storage_backend_has_status_transition_methods():
    from soniq.backends import StorageBackend

    members = _get_protocol_methods(StorageBackend)
    assert "mark_job_done" in members
    assert "mark_job_failed" in members
    assert "mark_job_dead_letter" in members


def test_storage_backend_has_worker_tracking_methods():
    from soniq.backends import StorageBackend

    members = _get_protocol_methods(StorageBackend)
    assert "register_worker" in members
    assert "update_heartbeat" in members
    assert "mark_worker_stopped" in members
    assert "cleanup_stale_workers" in members


def test_storage_backend_has_maintenance_methods():
    from soniq.backends import StorageBackend

    members = _get_protocol_methods(StorageBackend)
    assert "delete_expired_jobs" in members
    assert "reset" in members


def test_storage_backend_has_capability_properties():
    from soniq.backends import StorageBackend

    members = dir(StorageBackend)
    assert "supports_push_notify" in members
    assert "supports_transactional_enqueue" in members


def test_create_job_accepts_dedup_key():
    from soniq.backends import StorageBackend

    sig = inspect.signature(StorageBackend.create_job)
    assert "dedup_key" in sig.parameters


def test_structural_typing_works():
    """An object with the right methods should satisfy the protocol
    without inheriting from StorageBackend."""
    from soniq.backends import StorageBackend

    # Minimal stub — just enough to prove structural typing works
    class MinimalStub:
        supports_push_notify = False
        supports_transactional_enqueue = False

        async def initialize(self): ...
        async def close(self): ...
        async def create_job(self, **kw): ...
        async def fetch_and_lock_job(self, **kw): ...
        async def notify_new_job(self, queue): ...
        async def listen_for_jobs(self, callback, channel=""): ...
        async def mark_job_done(self, job_id, **kw): ...
        async def mark_job_failed(self, job_id, **kw): ...
        async def mark_job_dead_letter(self, job_id, **kw): ...
        async def reschedule_job(self, job_id, **kw): ...
        async def cancel_job(self, job_id): ...
        async def retry_job(self, job_id): ...
        async def delete_job(self, job_id): ...
        async def get_job(self, job_id): ...
        async def list_jobs(self, **kw): ...
        async def get_queue_stats(self): ...
        async def register_worker(self, **kw): ...
        async def update_heartbeat(self, worker_id, metadata=None): ...
        async def mark_worker_stopped(self, worker_id): ...
        async def cleanup_stale_workers(self, stale_threshold_seconds): ...
        async def delete_expired_jobs(self): ...
        async def reset(self): ...

    stub = MinimalStub()
    assert isinstance(stub, StorageBackend)


def _get_protocol_methods(cls):
    """Get method/property names defined on a Protocol class."""
    return [
        name
        for name in dir(cls)
        if not name.startswith("_")
        and (
            callable(getattr(cls, name, None))
            or isinstance(getattr(type(cls), name, None), property)
        )
    ]
