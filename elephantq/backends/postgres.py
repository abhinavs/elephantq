"""
PostgreSQL storage backend for ElephantQ.

Uses asyncpg for all database operations. Supports:
- FOR UPDATE SKIP LOCKED for concurrent dequeue
- pg_notify / LISTEN for push notifications
- Transactional enqueue via caller-provided connection
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

import asyncpg

from ..db.connection import _init_connection

logger = logging.getLogger(__name__)


def _rows_affected(result: str) -> int:
    """Parse asyncpg command result like 'UPDATE 1' → 1."""
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


def _row_to_dict(row: asyncpg.Record) -> dict:
    """Convert asyncpg Record to a plain dict with string IDs and ISO timestamps."""
    d: dict[str, Any] = {}
    for key in row.keys():
        val = row[key]
        if isinstance(val, uuid.UUID):
            d[key] = str(val)
        elif isinstance(val, datetime):
            d[key] = val.isoformat()
        else:
            d[key] = val
    return d


def _job_row_to_dict(row: asyncpg.Record) -> dict:
    """Convert a job row to the standard dict format."""
    return {
        "id": str(row["id"]),
        "job_name": row["job_name"],
        "args": (
            json.loads(row["args"]) if isinstance(row["args"], str) else row["args"]
        ),
        "status": row["status"],
        "attempts": row["attempts"],
        "max_attempts": row["max_attempts"],
        "queue": row["queue"],
        "priority": row["priority"],
        "scheduled_at": (
            row["scheduled_at"].isoformat() if row["scheduled_at"] else None
        ),
        "last_error": row["last_error"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


class PostgresBackend:
    """
    PostgreSQL storage backend.

    Production-grade backend with full concurrency support via
    FOR UPDATE SKIP LOCKED, push notifications via pg_notify,
    and transactional enqueue via caller connection.
    """

    def __init__(
        self,
        database_url: str,
        pool_min_size: int = 5,
        pool_max_size: int = 20,
    ):
        self._url = database_url
        self._pool_min = pool_min_size
        self._pool_max = pool_max_size
        self._pool: Optional[asyncpg.Pool] = None

    # --- Capabilities ---

    @property
    def supports_push_notify(self) -> bool:
        return True

    @property
    def supports_transactional_enqueue(self) -> bool:
        return True

    # --- Lifecycle ---

    async def initialize(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._url,
                min_size=self._pool_min,
                max_size=self._pool_max,
                init=_init_connection,
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        """Access the underlying pool. Used by features and migrations."""
        if self._pool is None:
            raise RuntimeError(
                "PostgresBackend not initialized. Call initialize() first."
            )
        return self._pool

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
        queueing_lock: Optional[str] = None,
        scheduled_at: Optional[datetime] = None,
    ) -> Optional[str]:
        async with self.pool.acquire() as conn:
            return await self._create_job_on_conn(
                conn,
                job_id=job_id,
                job_name=job_name,
                args=args,
                args_hash=args_hash,
                max_attempts=max_attempts,
                priority=priority,
                queue=queue,
                unique=unique,
                queueing_lock=queueing_lock,
                scheduled_at=scheduled_at,
            )

    async def create_job_transactional(
        self,
        *,
        connection: asyncpg.Connection,
        job_id: str,
        job_name: str,
        args: str,
        args_hash: Optional[str],
        max_attempts: int,
        priority: int,
        queue: str,
        unique: bool,
        queueing_lock: Optional[str] = None,
        scheduled_at: Optional[datetime] = None,
    ) -> Optional[str]:
        """Enqueue within a caller-provided transaction. PostgreSQL only."""
        return await self._create_job_on_conn(
            connection,
            job_id=job_id,
            job_name=job_name,
            args=args,
            args_hash=args_hash,
            max_attempts=max_attempts,
            priority=priority,
            queue=queue,
            unique=unique,
            queueing_lock=queueing_lock,
            scheduled_at=scheduled_at,
        )

    async def _create_job_on_conn(
        self,
        conn: asyncpg.Connection,
        *,
        job_id: str,
        job_name: str,
        args: str,
        args_hash: Optional[str],
        max_attempts: int,
        priority: int,
        queue: str,
        unique: bool,
        queueing_lock: Optional[str],
        scheduled_at: Optional[datetime],
    ) -> Optional[str]:
        """Shared implementation for both regular and transactional enqueue."""
        uid = uuid.UUID(job_id)

        if unique:
            row = await conn.fetchrow(
                """
                INSERT INTO elephantq_jobs
                    (id, job_name, args, args_hash, max_attempts, priority, queue, unique_job, scheduled_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (job_name, args_hash)
                    WHERE status = 'queued' AND unique_job = TRUE
                DO NOTHING
                RETURNING id
                """,
                uid,
                job_name,
                args,
                args_hash,
                max_attempts,
                priority,
                queue,
                True,
                scheduled_at,
            )
            if row is None:
                existing = await conn.fetchrow(
                    """
                    SELECT id FROM elephantq_jobs
                    WHERE job_name = $1 AND args_hash = $2
                      AND status = 'queued' AND unique_job = TRUE
                    """,
                    job_name,
                    args_hash,
                )
                return str(existing["id"]) if existing else job_id
            await conn.execute(
                "SELECT pg_notify($1, $2)",
                "elephantq_new_job",
                queue,
            )
            return str(row["id"])

        await conn.execute(
            """
            INSERT INTO elephantq_jobs
                (id, job_name, args, args_hash, max_attempts, priority, queue, unique_job, scheduled_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            uid,
            job_name,
            args,
            args_hash,
            max_attempts,
            priority,
            queue,
            unique,
            scheduled_at,
        )
        await conn.execute(
            "SELECT pg_notify($1, $2)",
            "elephantq_new_job",
            queue,
        )
        return job_id

    async def notify_new_job(self, queue: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT pg_notify($1, $2)",
                "elephantq_new_job",
                queue,
            )

    async def listen_for_jobs(
        self,
        callback: Any,
        channel: str = "elephantq_new_job",
    ) -> asyncpg.Connection:
        """Start listening. Returns the LISTEN connection (caller must release)."""
        conn = await self.pool.acquire()
        await conn.add_listener(channel, callback)
        return conn

    # --- Worker dequeue ---

    async def fetch_and_lock_job(
        self,
        *,
        queues: Optional[list[str]] = None,
        worker_id: Optional[str] = None,
    ) -> Optional[dict]:
        from ..core.processor import _should_skip_update_lock

        skip_lock = _should_skip_update_lock()

        lock_clause = "" if skip_lock else "FOR UPDATE SKIP LOCKED"

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if queues is None:
                    job_record = await conn.fetchrow(
                        f"""
                        SELECT * FROM elephantq_jobs
                        WHERE status = 'queued'
                          AND (scheduled_at IS NULL OR scheduled_at <= NOW())
                        ORDER BY priority ASC, scheduled_at ASC NULLS FIRST, created_at ASC
                        {lock_clause}
                        LIMIT 1
                        """
                    )
                elif len(queues) == 1:
                    job_record = await conn.fetchrow(
                        f"""
                        SELECT * FROM elephantq_jobs
                        WHERE status = 'queued'
                          AND queue = $1
                          AND (scheduled_at IS NULL OR scheduled_at <= NOW())
                        ORDER BY priority ASC, scheduled_at ASC NULLS FIRST, created_at ASC
                        {lock_clause}
                        LIMIT 1
                        """,
                        queues[0],
                    )
                else:
                    job_record = await conn.fetchrow(
                        f"""
                        SELECT * FROM elephantq_jobs
                        WHERE status = 'queued'
                          AND queue = ANY($1)
                          AND (scheduled_at IS NULL OR scheduled_at <= NOW())
                        ORDER BY priority ASC, scheduled_at ASC NULLS FIRST, created_at ASC
                        {lock_clause}
                        LIMIT 1
                        """,
                        queues,
                    )

                if not job_record:
                    return None

                job_id = job_record["id"]
                if worker_id:
                    await conn.execute(
                        """
                        UPDATE elephantq_jobs
                        SET status = 'processing', worker_id = $2, updated_at = NOW()
                        WHERE id = $1
                        """,
                        job_id,
                        uuid.UUID(worker_id),
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE elephantq_jobs
                        SET status = 'processing', updated_at = NOW()
                        WHERE id = $1
                        """,
                        job_id,
                    )

            return dict(job_record)

    # --- Job status transitions ---

    async def mark_job_done(
        self,
        job_id: str,
        *,
        result_ttl: Optional[int] = None,
    ) -> None:
        uid = uuid.UUID(job_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if result_ttl is not None and result_ttl == 0:
                    await conn.execute(
                        "DELETE FROM elephantq_jobs WHERE id = $1",
                        uid,
                    )
                else:
                    ttl = result_ttl if result_ttl is not None else 3600
                    await conn.execute(
                        """
                        UPDATE elephantq_jobs
                        SET status = 'done',
                            expires_at = NOW() + ($2 || ' seconds')::INTERVAL,
                            updated_at = NOW()
                        WHERE id = $1
                        """,
                        uid,
                        str(ttl),
                    )

    async def mark_job_failed(
        self,
        job_id: str,
        *,
        attempts: int,
        error: str,
        retry_delay: Optional[float] = None,
    ) -> None:
        uid = uuid.UUID(job_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if retry_delay and retry_delay > 0:
                    await conn.execute(
                        """
                        UPDATE elephantq_jobs
                        SET status = 'queued',
                            attempts = $1,
                            last_error = $2,
                            scheduled_at = NOW() + ($3 || ' seconds')::INTERVAL,
                            updated_at = NOW()
                        WHERE id = $4
                        """,
                        attempts,
                        error,
                        str(retry_delay),
                        uid,
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE elephantq_jobs
                        SET status = 'queued',
                            attempts = $1,
                            last_error = $2,
                            scheduled_at = NULL,
                            updated_at = NOW()
                        WHERE id = $3
                        """,
                        attempts,
                        error,
                        uid,
                    )

    async def mark_job_dead_letter(
        self,
        job_id: str,
        *,
        attempts: int,
        error: str,
    ) -> None:
        uid = uuid.UUID(job_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE elephantq_jobs
                    SET status = 'dead_letter',
                        attempts = $1,
                        last_error = $2,
                        updated_at = NOW()
                    WHERE id = $3
                    """,
                    attempts,
                    error,
                    uid,
                )

    async def cancel_job(self, job_id: str) -> bool:
        uid = uuid.UUID(job_id)
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE elephantq_jobs
                SET status = 'cancelled', updated_at = NOW()
                WHERE id = $1 AND status = 'queued'
                """,
                uid,
            )
            return _rows_affected(result) == 1

    async def retry_job(self, job_id: str) -> bool:
        uid = uuid.UUID(job_id)
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE elephantq_jobs
                SET status = 'queued', attempts = 0, last_error = NULL, updated_at = NOW()
                WHERE id = $1 AND status IN ('dead_letter', 'failed')
                """,
                uid,
            )
            return _rows_affected(result) == 1

    async def delete_job(self, job_id: str) -> bool:
        uid = uuid.UUID(job_id)
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM elephantq_jobs WHERE id = $1",
                uid,
            )
            return _rows_affected(result) == 1

    # --- Queries ---

    async def get_job(self, job_id: str) -> Optional[dict]:
        uid = uuid.UUID(job_id)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, job_name, args, status, attempts, max_attempts,
                       queue, priority, scheduled_at, last_error,
                       created_at, updated_at
                FROM elephantq_jobs
                WHERE id = $1
                """,
                uid,
            )
            if not row:
                return None
            return _job_row_to_dict(row)

    async def list_jobs(
        self,
        *,
        queue: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        conditions: list[str] = []
        params: list[Any] = []
        param_count = 0

        if queue is not None:
            param_count += 1
            conditions.append(f"queue = ${param_count}")
            params.append(queue)

        if status is not None:
            param_count += 1
            conditions.append(f"status = ${param_count}")
            params.append(status)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        param_count += 1
        params.append(limit)
        limit_param = f"${param_count}"

        param_count += 1
        params.append(offset)
        offset_param = f"${param_count}"

        query = f"""
            SELECT id, job_name, args, status, attempts, max_attempts,
                   queue, priority, scheduled_at, last_error,
                   created_at, updated_at
            FROM elephantq_jobs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT {limit_param} OFFSET {offset_param}
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [_job_row_to_dict(row) for row in rows]

    async def get_queue_stats(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    queue,
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status = 'queued') as queued,
                    COUNT(*) FILTER (WHERE status = 'processing') as processing,
                    COUNT(*) FILTER (WHERE status = 'done') as done,
                    COUNT(*) FILTER (WHERE status = 'dead_letter') as dead_letter,
                    COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled
                FROM elephantq_jobs
                GROUP BY queue
                ORDER BY queue
                """
            )
            return [dict(row) for row in rows]

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
        uid = uuid.UUID(worker_id)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO elephantq_workers
                    (id, hostname, pid, queues, concurrency, status, started_at, metadata)
                VALUES ($1, $2, $3, $4, $5, 'active', NOW(), $6)
                ON CONFLICT (hostname, pid)
                DO UPDATE SET
                    id = EXCLUDED.id,
                    queues = EXCLUDED.queues,
                    concurrency = EXCLUDED.concurrency,
                    status = 'active',
                    last_heartbeat = NOW(),
                    started_at = NOW(),
                    metadata = EXCLUDED.metadata
                """,
                uid,
                hostname,
                pid,
                queues,
                concurrency,
                json.dumps(metadata) if metadata else None,
            )

    async def update_heartbeat(
        self,
        worker_id: str,
        metadata: Optional[dict] = None,
    ) -> None:
        uid = uuid.UUID(worker_id)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE elephantq_workers
                SET last_heartbeat = NOW(), metadata = $2
                WHERE id = $1
                """,
                uid,
                json.dumps(metadata) if metadata else None,
            )

    async def mark_worker_stopped(self, worker_id: str) -> None:
        uid = uuid.UUID(worker_id)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE elephantq_workers
                SET status = 'stopped', last_heartbeat = NOW()
                WHERE id = $1
                """,
                uid,
            )

    async def cleanup_stale_workers(
        self,
        stale_threshold_seconds: int,
    ) -> int:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                stale_rows = await conn.fetch(
                    """
                    UPDATE elephantq_workers
                    SET status = 'stopped'
                    WHERE status = 'active'
                      AND last_heartbeat < NOW() - ($1 || ' seconds')::INTERVAL
                    RETURNING id
                    """,
                    str(stale_threshold_seconds),
                )

                if not stale_rows:
                    return 0

                stale_ids = [row["id"] for row in stale_rows]
                await conn.execute(
                    """
                    UPDATE elephantq_jobs
                    SET status = 'queued', worker_id = NULL, updated_at = NOW()
                    WHERE status = 'processing'
                      AND worker_id = ANY($1::uuid[])
                    """,
                    stale_ids,
                )

                return len(stale_ids)

    # --- Maintenance ---

    async def delete_expired_jobs(self) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM elephantq_jobs WHERE status = 'done' AND expires_at < NOW()"
            )
            return _rows_affected(result)

    async def reset(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("TRUNCATE elephantq_jobs CASCADE")
            await conn.execute("TRUNCATE elephantq_workers CASCADE")
