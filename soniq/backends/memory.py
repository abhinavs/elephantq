"""
In-memory storage backend for Soniq.

Used for unit tests. No persistence, no external dependencies.
Configure with: soniq.configure(backend="memory")
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional


class MemoryBackend:
    """
    In-memory storage backend.

    Stores jobs and workers in Python dicts.
    No persistence — all state is lost when the process exits.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._workers: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    # --- Capabilities ---

    @property
    def supports_push_notify(self) -> bool:
        return False

    @property
    def supports_transactional_enqueue(self) -> bool:
        return False

    @property
    def supports_connection_pool(self) -> bool:
        return False

    @property
    def supports_advisory_locks(self) -> bool:
        return False

    @property
    def supports_migrations(self) -> bool:
        return False

    # --- Lifecycle ---

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

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
        dedup_key: Optional[str] = None,
        scheduled_at: Optional[datetime] = None,
    ) -> Optional[str]:
        async with self._lock:
            # Unique dedup
            if unique and args_hash:
                for existing in self._jobs.values():
                    if (
                        existing["job_name"] == job_name
                        and existing.get("args_hash") == args_hash
                        and existing["status"] == "queued"
                        and existing.get("unique_job")
                    ):
                        return str(existing["id"])

            # Queueing lock dedup
            if dedup_key:
                for existing in self._jobs.values():
                    if (
                        existing.get("dedup_key") == dedup_key
                        and existing["status"] == "queued"
                    ):
                        return str(existing["id"])

            now = datetime.now(timezone.utc)
            self._jobs[job_id] = {
                "id": job_id,
                "job_name": job_name,
                "args": args,
                "args_hash": args_hash,
                "status": "queued",
                "attempts": 0,
                "max_attempts": max_attempts,
                "priority": priority,
                "queue": queue,
                "unique_job": unique,
                "dedup_key": dedup_key,
                "scheduled_at": scheduled_at,
                "expires_at": None,
                "result": None,
                "last_error": None,
                "worker_id": None,
                "created_at": now,
                "updated_at": now,
            }
            return job_id

    # --- Worker dequeue ---

    async def fetch_and_lock_job(
        self,
        *,
        queues: Optional[list[str]] = None,
        worker_id: Optional[str] = None,
    ) -> Optional[dict]:
        async with self._lock:
            now = datetime.now(timezone.utc)
            candidates = []

            for job in self._jobs.values():
                if job["status"] != "queued":
                    continue
                if queues and job["queue"] not in queues:
                    continue
                if job["scheduled_at"] and job["scheduled_at"] > now:
                    continue
                candidates.append(job)

            if not candidates:
                return None

            # Sort by priority (lower = higher priority), then created_at
            candidates.sort(
                key=lambda j: (
                    j["priority"],
                    j["scheduled_at"] or datetime.min.replace(tzinfo=timezone.utc),
                    j["created_at"],
                )
            )

            job = candidates[0]
            job["status"] = "processing"
            job["attempts"] += 1
            job["worker_id"] = worker_id
            job["updated_at"] = datetime.now(timezone.utc)
            return dict(job)

    async def notify_new_job(self, queue: str) -> None:
        pass  # No push notification in memory backend

    async def listen_for_jobs(
        self,
        callback: Any,
        channel: str = "soniq_new_job",
    ) -> None:
        pass  # No push notification

    # --- Job status transitions ---

    async def mark_job_done(
        self,
        job_id: str,
        *,
        result_ttl: Optional[int] = None,
        result: Any = None,
    ) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if result_ttl is not None and result_ttl == 0:
                del self._jobs[job_id]
            else:
                job["status"] = "done"
                job["result"] = result
                job["updated_at"] = datetime.now(timezone.utc)
                if result_ttl is not None and result_ttl > 0:
                    from datetime import timedelta

                    job["expires_at"] = datetime.now(timezone.utc) + timedelta(
                        seconds=result_ttl
                    )

    async def mark_job_failed(
        self,
        job_id: str,
        *,
        attempts: int,
        error: str,
        retry_delay: Optional[float] = None,
    ) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "queued"
            job["attempts"] = attempts
            job["last_error"] = error
            if retry_delay and retry_delay > 0:
                from datetime import timedelta

                job["scheduled_at"] = datetime.now(timezone.utc) + timedelta(
                    seconds=retry_delay
                )
            else:
                job["scheduled_at"] = None
            job["updated_at"] = datetime.now(timezone.utc)

    async def mark_job_dead_letter(
        self,
        job_id: str,
        *,
        attempts: int,
        error: str,
    ) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "dead_letter"
            job["attempts"] = attempts
            job["last_error"] = error
            job["updated_at"] = datetime.now(timezone.utc)

    async def reschedule_job(
        self,
        job_id: str,
        *,
        delay_seconds: float,
        attempts: int,
        reason: Optional[str] = None,
    ) -> None:
        from datetime import timedelta

        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "queued"
            job["attempts"] = attempts
            job["scheduled_at"] = datetime.now(timezone.utc) + timedelta(
                seconds=delay_seconds
            )
            job["last_error"] = f"SNOOZE: {reason}" if reason else "SNOOZE"
            job["updated_at"] = datetime.now(timezone.utc)

    async def cancel_job(self, job_id: str) -> bool:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] != "queued":
                return False
            job["status"] = "cancelled"
            job["updated_at"] = datetime.now(timezone.utc)
            return True

    async def retry_job(self, job_id: str) -> bool:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] not in ("dead_letter", "failed"):
                return False
            job["status"] = "queued"
            job["attempts"] = 0
            job["last_error"] = None
            job["updated_at"] = datetime.now(timezone.utc)
            return True

    async def delete_job(self, job_id: str) -> bool:
        async with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                return True
            return False

    # --- Queries ---

    async def get_job(self, job_id: str) -> Optional[dict]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return self._format_job(job)

    async def list_jobs(
        self,
        *,
        queue: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        results = []
        for job in self._jobs.values():
            if queue and job["queue"] != queue:
                continue
            if status and job["status"] != status:
                continue
            results.append(self._format_job(job))

        # Sort by created_at descending
        results.sort(key=lambda j: j.get("created_at", ""), reverse=True)
        return results[offset : offset + limit]

    async def get_queue_stats(self) -> list[dict]:
        stats: dict[str, dict[str, int]] = {}
        for job in self._jobs.values():
            q = job["queue"]
            if q not in stats:
                stats[q] = {
                    "queue": q,
                    "total": 0,
                    "queued": 0,
                    "processing": 0,
                    "done": 0,
                    "dead_letter": 0,
                    "cancelled": 0,
                }
            stats[q]["total"] += 1
            s = job["status"]
            if s in stats[q]:
                stats[q][s] += 1
        return sorted(stats.values(), key=lambda x: x["queue"])

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
        self._workers[worker_id] = {
            "id": worker_id,
            "hostname": hostname,
            "pid": pid,
            "queues": queues,
            "concurrency": concurrency,
            "status": "active",
            "last_heartbeat": datetime.now(timezone.utc),
            "started_at": datetime.now(timezone.utc),
            "metadata": metadata,
        }

    async def update_heartbeat(
        self,
        worker_id: str,
        metadata: Optional[dict] = None,
    ) -> None:
        worker = self._workers.get(worker_id)
        if worker:
            worker["last_heartbeat"] = datetime.now(timezone.utc)
            if metadata:
                worker["metadata"] = metadata

    async def mark_worker_stopped(self, worker_id: str) -> None:
        worker = self._workers.get(worker_id)
        if worker:
            worker["status"] = "stopped"

    async def cleanup_stale_workers(
        self,
        stale_threshold_seconds: int,
    ) -> int:
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        threshold = now - timedelta(seconds=stale_threshold_seconds)
        stale_ids = []

        for wid, worker in self._workers.items():
            if worker["status"] == "active" and worker["last_heartbeat"] < threshold:
                stale_ids.append(wid)

        for wid in stale_ids:
            self._workers[wid]["status"] = "stopped"

        # Reset processing jobs from stale workers
        for job in self._jobs.values():
            if job["status"] == "processing" and job.get("worker_id") in stale_ids:
                job["status"] = "queued"
                job["worker_id"] = None

        return len(stale_ids)

    # --- Maintenance ---

    async def delete_expired_jobs(self) -> int:
        now = datetime.now(timezone.utc)
        expired = [
            jid
            for jid, job in self._jobs.items()
            if job["status"] == "done"
            and job.get("expires_at")
            and job["expires_at"] < now
        ]
        for jid in expired:
            del self._jobs[jid]
        return len(expired)

    async def reset(self) -> None:
        self._jobs.clear()
        self._workers.clear()

    # --- Helpers ---

    @staticmethod
    def _format_job(job: dict) -> dict:
        """Format a job dict for external consumption.

        `args` is stored as a dict internally and returned as a dict (the
        uniform backend contract). Datetimes are converted to ISO strings to
        match what the Postgres backend returns for list/get paths.
        """
        result = dict(job)
        for key in ("scheduled_at", "created_at", "updated_at", "expires_at"):
            val = result.get(key)
            if isinstance(val, datetime):
                result[key] = val.isoformat()
        return result
