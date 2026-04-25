"""
Pluggable storage backends for Soniq.

StorageBackend defines the interface. Production-tier implementations:
- PostgresBackend (production)
- SQLiteBackend (local dev, zero setup)

The in-memory backend (`MemoryBackend`) lives under `soniq.testing` to
make its scope obvious at the import site - it is for tests, examples,
and quick scripts only.
"""

from datetime import datetime
from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class ListenerHandle(Protocol):
    """Opaque handle returned by ``listen_for_jobs``.

    Backends own the underlying transport (asyncpg connection,
    in-process callback registry, etc.) and expose only ``close()`` so
    callers cannot reach in and leak the connection. The worker shutdown
    path calls ``await handle.close()``; backends without push-notify
    return a no-op handle.
    """

    async def close(self) -> None:
        """Tear down the listener and release any held resources."""
        ...


@runtime_checkable
class StorageBackend(Protocol):
    """
    Interface for all storage operations Soniq needs.

    Every method is async. Backends handle their own connection
    management internally — callers never see connections or pools.

    Transactional enqueue is NOT part of this interface.
    It is a PostgreSQL-specific capability exposed directly on
    PostgresBackend. See PostgresBackend.create_job_transactional().
    """

    # --- Capabilities ---

    @property
    def supports_push_notify(self) -> bool:
        """Whether this backend supports push notifications (LISTEN/NOTIFY)."""
        ...

    @property
    def supports_transactional_enqueue(self) -> bool:
        """Whether this backend supports transactional enqueue via connection=."""
        ...

    @property
    def supports_connection_pool(self) -> bool:
        """Whether this backend exposes an asyncpg-style connection pool.

        True for Postgres; False for SQLite and Memory. Callers that need
        raw pool access (worker shutdown listener release, advanced
        integration paths) gate on this rather than `hasattr(backend, 'pool')`.
        """
        ...

    @property
    def supports_advisory_locks(self) -> bool:
        """Whether this backend supports Postgres-style advisory locks.

        True only for Postgres. Leadership election (`with_advisory_lock`)
        falls back to always-leader when this is False.
        """
        ...

    @property
    def supports_migrations(self) -> bool:
        """Whether this backend uses the file-based migration runner.

        True for Postgres. SQLite creates its schema inside `initialize()`
        with ad-hoc DDL. Memory has no schema at all.
        """
        ...

    # --- Lifecycle ---

    async def initialize(self) -> None:
        """Create tables, pools, or other resources."""
        ...

    async def close(self) -> None:
        """Release all resources."""
        ...

    # --- Job CRUD ---

    async def create_job(
        self,
        *,
        job_id: str,
        job_name: str,
        args: dict,
        args_hash: Optional[str],
        max_attempts: int,
        priority: int,
        queue: str,
        unique: bool,
        dedup_key: Optional[str],
        scheduled_at: Optional[datetime],
    ) -> Optional[str]:
        """
        Insert a job. Return job_id on success.

        `args` is the unserialized job kwargs dict. Backends are responsible
        for any on-wire serialization they need; callers work with dicts.

        If unique=True and a duplicate queued job exists, return existing ID.
        If dedup_key is set and a locked queued job exists, return existing ID.
        """
        ...

    # --- Worker dequeue ---

    async def fetch_and_lock_job(
        self,
        *,
        queues: Optional[list[str]],
        worker_id: Optional[str],
    ) -> Optional[dict]:
        """
        Atomically find the next eligible job, lock it, mark as 'processing'.
        Return job record dict or None.

        Must guarantee at-most-once claim per call across concurrent workers.
        """
        ...

    async def notify_new_job(self, queue: str) -> None:
        """
        Signal that a new job is available.

        Postgres: pg_notify. SQLite/Memory: no-op (polling only).
        """
        ...

    async def listen_for_jobs(
        self,
        callback: Any,
        channel: str = "soniq_new_job",
    ) -> "ListenerHandle":
        """
        Start listening for job notifications.

        Returns a ``ListenerHandle`` whose ``close()`` tears down both
        the subscription and any held connection. Backends without push
        notification return a no-op handle.
        """
        ...

    # --- Job status transitions ---

    async def mark_job_done(
        self,
        job_id: str,
        *,
        result_ttl: Optional[int] = None,
        result: Any = None,
    ) -> None:
        """Mark job as done. If result_ttl=0, delete immediately."""
        ...

    async def mark_job_failed(
        self,
        job_id: str,
        *,
        attempts: int,
        error: str,
        retry_delay: Optional[float] = None,
    ) -> None:
        """
        Mark job as failed.

        If retry_delay is set, reschedule to queued with delay.
        If retry_delay is None, reschedule immediately.
        """
        ...

    async def mark_job_dead_letter(
        self,
        job_id: str,
        *,
        attempts: int,
        error: str,
    ) -> None:
        """Move job to dead_letter status."""
        ...

    async def reschedule_job(
        self,
        job_id: str,
        *,
        delay_seconds: float,
        attempts: int,
        reason: Optional[str] = None,
    ) -> None:
        """
        Snooze a running job: set status back to 'queued', scheduled_at
        forward by delay_seconds, and attempts to the supplied value
        (callers typically pass the pre-claim count so the snooze does not
        consume a retry slot). Used by the Snooze return type.
        """
        ...

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued job. Return True if cancelled."""
        ...

    async def retry_job(self, job_id: str) -> bool:
        """Reset a dead_letter/failed job to queued. Return True if reset."""
        ...

    async def delete_job(self, job_id: str) -> bool:
        """Delete a job entirely. Return True if deleted."""
        ...

    # --- Queries ---

    async def get_job(self, job_id: str) -> Optional[dict]:
        """Fetch a single job by ID."""
        ...

    async def list_jobs(
        self,
        *,
        queue: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List jobs with optional filters."""
        ...

    async def get_queue_stats(self) -> list[dict]:
        """Aggregate job counts grouped by queue and status."""
        ...

    # --- Worker tracking ---

    async def register_worker(
        self,
        *,
        worker_id: str,
        hostname: str,
        pid: int,
        queues: list[str],
        concurrency: int,
        metadata: Optional[dict] = None,
    ) -> None:
        """Register or update a worker record."""
        ...

    async def update_heartbeat(
        self,
        worker_id: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Touch the worker's heartbeat timestamp."""
        ...

    async def mark_worker_stopped(self, worker_id: str) -> None:
        """Mark a worker as stopped."""
        ...

    async def cleanup_stale_workers(
        self,
        stale_threshold_seconds: int,
    ) -> int:
        """
        Find workers with expired heartbeats.
        Mark them stopped. Reset their processing jobs to queued.
        Return count of cleaned workers.
        """
        ...

    # --- Maintenance ---

    async def delete_expired_jobs(self) -> int:
        """Delete done jobs past their expires_at. Return count."""
        ...

    async def reset(self) -> None:
        """
        Delete all jobs and workers. Used in test fixtures.

        Memory: clear dicts. Postgres: TRUNCATE. SQLite: DELETE FROM.
        """
        ...
