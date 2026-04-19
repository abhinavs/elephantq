"""
SQLite storage backend for ElephantQ.

Zero-setup local development backend. No server required.
Configure with: elephantq.configure(backend="sqlite")

Limitations:
- Single worker process only (no concurrent dequeue)
- No push notifications (polling only)
- No transactional enqueue with external connections
- Good enough for local dev, prototyping, and simple deployments
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import aiosqlite
except ImportError:
    aiosqlite = None  # type: ignore[assignment]


def _require_aiosqlite() -> None:
    if aiosqlite is None:
        raise ImportError(
            "aiosqlite is required for the SQLite backend. "
            "Install it with: pip install elephantq[sqlite]"
        )


class SQLiteBackend:
    """
    SQLite storage backend for local development.

    Uses WAL mode and busy_timeout for reasonable performance.
    Single-writer — only one worker process per database file.
    """

    def __init__(self, path: str = "elephantq.db") -> None:
        _require_aiosqlite()
        self._path = path
        self._conn: Optional[aiosqlite.Connection] = None

    # --- Capabilities ---

    @property
    def supports_push_notify(self) -> bool:
        return False

    @property
    def supports_transactional_enqueue(self) -> bool:
        return False

    # --- Lifecycle ---

    async def initialize(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._create_tables()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _create_tables(self) -> None:
        assert self._conn is not None
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS elephantq_jobs (
                id TEXT PRIMARY KEY,
                job_name TEXT NOT NULL,
                args TEXT NOT NULL,
                args_hash TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                queue TEXT DEFAULT 'default',
                priority INTEGER DEFAULT 100,
                unique_job INTEGER DEFAULT 0,
                dedup_key TEXT,
                scheduled_at TEXT,
                expires_at TEXT,
                last_error TEXT,
                worker_id TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_eq_jobs_status_priority
                ON elephantq_jobs (status, priority) WHERE status = 'queued';
            CREATE INDEX IF NOT EXISTS idx_eq_jobs_queue_status
                ON elephantq_jobs (queue, status);

            CREATE TABLE IF NOT EXISTS elephantq_workers (
                id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                pid INTEGER NOT NULL,
                queues TEXT DEFAULT '[]',
                concurrency INTEGER DEFAULT 1,
                status TEXT DEFAULT 'active',
                last_heartbeat TEXT,
                started_at TEXT,
                metadata TEXT
            );
            """
        )
        await self._conn.commit()

    # --- Job CRUD ---

    async def create_job(
        self,
        *,
        job_id: str,
        job_name: str,
        args: str,
        args_hash: Optional[str],
        max_attempts: int,
        priority: int,
        queue: str,
        unique: bool,
        dedup_key: Optional[str] = None,
        scheduled_at: Optional[datetime] = None,
    ) -> Optional[str]:
        assert self._conn is not None
        now = _now_iso()

        # Unique dedup
        if unique and args_hash:
            async with self._conn.execute(
                """
                SELECT id FROM elephantq_jobs
                WHERE job_name = ? AND args_hash = ? AND status = 'queued' AND unique_job = 1
                """,
                (job_name, args_hash),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return str(row["id"])

        # Queueing lock dedup
        if dedup_key:
            async with self._conn.execute(
                "SELECT id FROM elephantq_jobs WHERE dedup_key = ? AND status = 'queued'",
                (dedup_key,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return str(row["id"])

        sched = scheduled_at.isoformat() if scheduled_at else None
        await self._conn.execute(
            """
            INSERT INTO elephantq_jobs
                (id, job_name, args, args_hash, max_attempts, priority, queue,
                 unique_job, dedup_key, scheduled_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_name,
                args,
                args_hash,
                max_attempts,
                priority,
                queue,
                1 if unique else 0,
                dedup_key,
                sched,
                now,
                now,
            ),
        )
        await self._conn.commit()
        return job_id

    # --- Worker dequeue ---

    async def fetch_and_lock_job(
        self,
        *,
        queues: Optional[list[str]] = None,
        worker_id: Optional[str] = None,
    ) -> Optional[dict]:
        assert self._conn is not None
        now = _now_iso()

        if queues:
            placeholders = ",".join("?" for _ in queues)
            query = f"""
                SELECT * FROM elephantq_jobs
                WHERE status = 'queued'
                  AND queue IN ({placeholders})
                  AND (scheduled_at IS NULL OR scheduled_at <= ?)
                ORDER BY priority ASC, scheduled_at ASC, created_at ASC
                LIMIT 1
            """
            params: tuple = (*queues, now)
        else:
            query = """
                SELECT * FROM elephantq_jobs
                WHERE status = 'queued'
                  AND (scheduled_at IS NULL OR scheduled_at <= ?)
                ORDER BY priority ASC, scheduled_at ASC, created_at ASC
                LIMIT 1
            """
            params = (now,)

        async with self._conn.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            job_id = row["id"]
            await self._conn.execute(
                "UPDATE elephantq_jobs SET status='processing', attempts=attempts+1, worker_id=?, updated_at=? WHERE id=?",
                (worker_id, _now_iso(), job_id),
            )
            await self._conn.commit()
            result = dict(row)
            result["attempts"] = result["attempts"] + 1
            return result

    async def notify_new_job(self, queue: str) -> None:
        pass  # No push notification

    async def listen_for_jobs(
        self, callback: Any, channel: str = "elephantq_new_job"
    ) -> None:
        pass  # No push notification

    # --- Job status transitions ---

    async def mark_job_done(
        self, job_id: str, *, result_ttl: Optional[int] = None, result: Any = None
    ) -> None:
        assert self._conn is not None
        if result_ttl is not None and result_ttl == 0:
            await self._conn.execute("DELETE FROM elephantq_jobs WHERE id=?", (job_id,))
        else:
            ttl = result_ttl if result_ttl is not None else 3600
            expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
            await self._conn.execute(
                "UPDATE elephantq_jobs SET status='done', expires_at=?, updated_at=? WHERE id=?",
                (expires, _now_iso(), job_id),
            )
        await self._conn.commit()

    async def mark_job_failed(
        self,
        job_id: str,
        *,
        attempts: int,
        error: str,
        retry_delay: Optional[float] = None,
    ) -> None:
        assert self._conn is not None
        if retry_delay and retry_delay > 0:
            sched = (
                datetime.now(timezone.utc) + timedelta(seconds=retry_delay)
            ).isoformat()
            await self._conn.execute(
                "UPDATE elephantq_jobs SET status='queued', attempts=?, last_error=?, scheduled_at=?, updated_at=? WHERE id=?",
                (attempts, error, sched, _now_iso(), job_id),
            )
        else:
            await self._conn.execute(
                "UPDATE elephantq_jobs SET status='queued', attempts=?, last_error=?, scheduled_at=NULL, updated_at=? WHERE id=?",
                (attempts, error, _now_iso(), job_id),
            )
        await self._conn.commit()

    async def mark_job_dead_letter(
        self, job_id: str, *, attempts: int, error: str
    ) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "UPDATE elephantq_jobs SET status='dead_letter', attempts=?, last_error=?, updated_at=? WHERE id=?",
            (attempts, error, _now_iso(), job_id),
        )
        await self._conn.commit()

    async def reschedule_job(
        self,
        job_id: str,
        *,
        delay_seconds: float,
        attempts: int,
        reason: Optional[str] = None,
    ) -> None:
        assert self._conn is not None
        sched = (
            datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        ).isoformat()
        reason_text = f"SNOOZE: {reason}" if reason else "SNOOZE"
        await self._conn.execute(
            "UPDATE elephantq_jobs SET status='queued', attempts=?, scheduled_at=?, last_error=?, updated_at=? WHERE id=?",
            (attempts, sched, reason_text, _now_iso(), job_id),
        )
        await self._conn.commit()

    async def cancel_job(self, job_id: str) -> bool:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "UPDATE elephantq_jobs SET status='cancelled', updated_at=? WHERE id=? AND status='queued'",
            (_now_iso(), job_id),
        )
        await self._conn.commit()
        return bool(cursor.rowcount and cursor.rowcount > 0)

    async def retry_job(self, job_id: str) -> bool:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "UPDATE elephantq_jobs SET status='queued', attempts=0, last_error=NULL, updated_at=? WHERE id=? AND status IN ('dead_letter', 'failed')",
            (_now_iso(), job_id),
        )
        await self._conn.commit()
        return bool(cursor.rowcount and cursor.rowcount > 0)

    async def delete_job(self, job_id: str) -> bool:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "DELETE FROM elephantq_jobs WHERE id=?",
            (job_id,),
        )
        await self._conn.commit()
        return bool(cursor.rowcount and cursor.rowcount > 0)

    # --- Queries ---

    async def get_job(self, job_id: str) -> Optional[dict]:
        assert self._conn is not None
        async with self._conn.execute(
            "SELECT * FROM elephantq_jobs WHERE id=?",
            (job_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return _sqlite_row_to_dict(row)

    async def list_jobs(
        self,
        *,
        queue: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        assert self._conn is not None
        conditions = []
        params: list[Any] = []
        if queue:
            conditions.append("queue=?")
            params.append(queue)
        if status:
            conditions.append("status=?")
            params.append(status)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.extend([limit, offset])

        async with self._conn.execute(
            f"SELECT * FROM elephantq_jobs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ) as cursor:
            rows = await cursor.fetchall()
            return [_sqlite_row_to_dict(r) for r in rows]

    async def get_queue_stats(self) -> list[dict]:
        assert self._conn is not None
        async with self._conn.execute(
            """
            SELECT queue,
                COUNT(*) as total,
                SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) as queued,
                SUM(CASE WHEN status='processing' THEN 1 ELSE 0 END) as processing,
                SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
                SUM(CASE WHEN status='dead_letter' THEN 1 ELSE 0 END) as dead_letter,
                SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) as cancelled
            FROM elephantq_jobs GROUP BY queue ORDER BY queue
            """
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

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
        assert self._conn is not None
        now = _now_iso()
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO elephantq_workers
                (id, hostname, pid, queues, concurrency, status, last_heartbeat, started_at, metadata)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                worker_id,
                hostname,
                pid,
                json.dumps(queues),
                concurrency,
                now,
                now,
                json.dumps(metadata) if metadata else None,
            ),
        )
        await self._conn.commit()

    async def update_heartbeat(
        self, worker_id: str, metadata: Optional[dict] = None
    ) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "UPDATE elephantq_workers SET last_heartbeat=?, metadata=? WHERE id=?",
            (_now_iso(), json.dumps(metadata) if metadata else None, worker_id),
        )
        await self._conn.commit()

    async def mark_worker_stopped(self, worker_id: str) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "UPDATE elephantq_workers SET status='stopped', last_heartbeat=? WHERE id=?",
            (_now_iso(), worker_id),
        )
        await self._conn.commit()

    async def cleanup_stale_workers(self, stale_threshold_seconds: int) -> int:
        assert self._conn is not None
        threshold = (
            datetime.now(timezone.utc) - timedelta(seconds=stale_threshold_seconds)
        ).isoformat()

        async with self._conn.execute(
            "SELECT id FROM elephantq_workers WHERE status='active' AND last_heartbeat < ?",
            (threshold,),
        ) as cursor:
            stale = [row["id"] for row in await cursor.fetchall()]

        if not stale:
            return 0

        placeholders = ",".join("?" for _ in stale)
        await self._conn.execute(
            f"UPDATE elephantq_workers SET status='stopped' WHERE id IN ({placeholders})",
            stale,
        )
        await self._conn.execute(
            f"UPDATE elephantq_jobs SET status='queued', worker_id=NULL, updated_at=? WHERE status='processing' AND worker_id IN ({placeholders})",
            [_now_iso()] + stale,
        )
        await self._conn.commit()
        return len(stale)

    # --- Maintenance ---

    async def delete_expired_jobs(self) -> int:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "DELETE FROM elephantq_jobs WHERE status='done' AND expires_at < ?",
            (_now_iso(),),
        )
        await self._conn.commit()
        return cursor.rowcount or 0  # type: ignore[return-value]

    async def reset(self) -> None:
        assert self._conn is not None
        await self._conn.execute("DELETE FROM elephantq_jobs")
        await self._conn.execute("DELETE FROM elephantq_workers")
        await self._conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sqlite_row_to_dict(row: Any) -> dict:
    """Convert an aiosqlite Row to the standard job dict format."""
    d = dict(row)
    # Parse JSON args
    if isinstance(d.get("args"), str):
        try:
            d["args"] = json.loads(d["args"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d
