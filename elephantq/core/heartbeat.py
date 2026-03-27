"""
Worker heartbeat utilities for production PostgreSQL deployments.

Standalone functions used by the CLI for worker monitoring and stale cleanup.
The Worker class handles its own heartbeat via the backend interface.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import asyncpg

logger = logging.getLogger(__name__)


async def cleanup_stale_workers(
    pool: asyncpg.Pool, stale_threshold_seconds: Optional[float] = None
) -> int:
    """
    Clean up workers that haven't sent heartbeats within the threshold.

    Args:
        pool: Database connection pool
        stale_threshold_seconds: Consider workers stale after this many seconds

    Returns:
        Number of stale workers cleaned up
    """
    if stale_threshold_seconds is None:
        from elephantq.settings import get_settings

        stale_threshold_seconds = get_settings().heartbeat_timeout

    try:
        async with pool.acquire() as conn:
            stale_worker_ids = await conn.fetch(
                """
                UPDATE elephantq_workers
                SET status = 'stopped'
                WHERE status = 'active'
                AND last_heartbeat < NOW() - ($1 || ' seconds')::INTERVAL
                RETURNING id
                """,
                str(stale_threshold_seconds),
            )

            cleaned_count = len(stale_worker_ids)

            if cleaned_count > 0:
                worker_ids = [row["id"] for row in stale_worker_ids]
                await conn.execute(
                    """
                    UPDATE elephantq_jobs
                    SET status = 'queued', worker_id = NULL, updated_at = NOW()
                    WHERE status = 'processing'
                      AND worker_id = ANY($1::uuid[])
                    """,
                    worker_ids,
                )
                logger.warning(f"Marked {cleaned_count} stale workers as stopped")

            return cleaned_count

    except asyncpg.exceptions.InterfaceError as e:
        if "pool is closing" in str(e):
            return 0
        logger.error(f"Failed to cleanup stale workers: {e}")
        return 0
    except Exception as e:
        logger.error(f"Failed to cleanup stale workers: {e}")
        return 0


async def get_worker_status(pool: asyncpg.Pool) -> Dict[str, Any]:
    """
    Get current worker status for monitoring.

    Returns:
        Dictionary with worker statistics and status information
    """
    try:
        async with pool.acquire() as conn:
            status_counts = await conn.fetch(
                "SELECT status, COUNT(*) as count FROM elephantq_workers GROUP BY status"
            )

            active_workers = await conn.fetch(
                """
                SELECT id, hostname, pid, queues, concurrency, last_heartbeat, started_at, metadata
                FROM elephantq_workers
                WHERE status = 'active'
                ORDER BY last_heartbeat DESC
                """
            )

            stale_workers = await conn.fetch(
                """
                SELECT id, hostname, pid, last_heartbeat
                FROM elephantq_workers
                WHERE status = 'active'
                AND last_heartbeat < NOW() - INTERVAL '300 seconds'
                """
            )

            return {
                "status_counts": {row["status"]: row["count"] for row in status_counts},
                "active_workers": [
                    {
                        "id": str(row["id"]),
                        "hostname": row["hostname"],
                        "pid": row["pid"],
                        "queues": row["queues"] or [],
                        "concurrency": row["concurrency"],
                        "last_heartbeat": row["last_heartbeat"].isoformat(),
                        "started_at": row["started_at"].isoformat(),
                        "uptime_seconds": (
                            datetime.now(timezone.utc)
                            - (
                                row["started_at"].replace(tzinfo=timezone.utc)
                                if row["started_at"].tzinfo is None
                                else row["started_at"]
                            )
                        ).total_seconds(),
                        "metadata": row["metadata"],
                    }
                    for row in active_workers
                ],
                "stale_workers": [
                    {
                        "id": str(row["id"]),
                        "hostname": row["hostname"],
                        "pid": row["pid"],
                        "last_heartbeat": row["last_heartbeat"].isoformat(),
                    }
                    for row in stale_workers
                ],
                "total_concurrency": sum(w["concurrency"] for w in active_workers),
                "health": "healthy" if not stale_workers else "degraded",
            }

    except Exception as e:
        logger.error(f"Failed to get worker status: {e}")
        return {"error": str(e), "health": "unknown"}
