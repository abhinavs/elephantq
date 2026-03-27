"""
Job queue operations - the heart of ElephantQ

This handles everything related to putting jobs in the queue and managing them.
The goal is to make it feel natural and reliable for developers.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Union

import asyncpg
from pydantic import ValidationError

from elephantq.core.registry import JobRegistry
from elephantq.db.context import get_context_pool
from elephantq.db.helpers import rows_affected as _rows_affected
from elephantq.utils.hashing import compute_args_hash


def _validate_job_arguments(job_name: str, job_meta: dict, kwargs: dict) -> None:
    """
    Validate job arguments against the job's Pydantic model.

    Args:
        job_name: Name of the job function
        job_meta: Job metadata from registry
        kwargs: Arguments to validate

    Raises:
        ValueError: If arguments are invalid
    """
    args_model = job_meta.get("args_model")
    if args_model:
        try:
            args_model(**kwargs)  # Validate arguments
        except ValidationError as e:
            raise ValueError(f"Invalid arguments for job {job_name}: {e}") from e


def _normalize_scheduled_time(
    scheduled_at: Optional[Union[datetime, int, float, timedelta]],
) -> Optional[datetime]:
    """
    Normalize scheduled_at to a timezone-aware UTC datetime for database storage.

    Users can pass datetimes in any timezone:
    - Timezone-aware datetimes are converted to UTC automatically.
    - Naive datetimes (no tzinfo) are interpreted as local machine time
      and converted to UTC.
    - timedelta and numeric values are treated as offsets from now.

    Args:
        scheduled_at: datetime, timedelta, or seconds from now (int/float)

    Returns:
        Timezone-aware UTC datetime suitable for TIMESTAMPTZ storage, or None
    """
    if scheduled_at is None:
        return None

    # Handle timedelta values (add to current UTC time)
    if isinstance(scheduled_at, timedelta):
        return datetime.now(timezone.utc) + scheduled_at

    # Handle numeric values (seconds from now)
    if isinstance(scheduled_at, (int, float)):
        return datetime.now(timezone.utc) + timedelta(seconds=scheduled_at)

    if scheduled_at.tzinfo is not None:
        # Timezone-aware: convert to UTC
        return scheduled_at.astimezone(timezone.utc)
    else:
        # Naive datetime: treat as local time, convert to UTC.
        # This is user-friendly — datetime.now() and datetime(2025, 3, 23, 14, 0)
        # are interpreted in the user's local timezone.
        local_dt = scheduled_at.astimezone()  # attach local tz
        return local_dt.astimezone(timezone.utc)


async def _create_job_record(
    conn,
    job_id: str,
    job_name: str,
    job_meta: dict,
    args_json: str,
    args_hash: Optional[str],
    final_priority: int,
    final_queue: str,
    final_unique: bool,
    scheduled_at: Optional[datetime],
) -> Optional[str]:
    """
    Create a new job record in the database.

    For unique jobs, uses INSERT...ON CONFLICT to atomically prevent duplicates.

    Returns:
        The job_id if inserted, or the existing job's ID on conflict (unique jobs).
        Returns the passed job_id for non-unique jobs.
    """
    if final_unique:
        # Atomic upsert: relies on partial unique index idx_elephantq_jobs_unique_queued
        row = await conn.fetchrow(
            """
            INSERT INTO elephantq_jobs (id, job_name, args, args_hash, max_attempts, priority, queue, unique_job, scheduled_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (job_name, args_hash) WHERE status = 'queued' AND unique_job = TRUE
            DO NOTHING
            RETURNING id
            """,
            uuid.UUID(job_id),
            job_name,
            args_json,
            args_hash,
            job_meta["retries"] + 1,
            final_priority,
            final_queue,
            final_unique,
            scheduled_at,
        )
        if row is None:
            # Conflict — fetch the existing job's ID
            existing = await conn.fetchrow(
                """
                SELECT id FROM elephantq_jobs
                WHERE job_name = $1 AND args_hash = $2 AND status = 'queued' AND unique_job = TRUE
                """,
                job_name,
                args_hash,
            )
            return str(existing["id"]) if existing else job_id
        # Inserted successfully — notify workers
        await conn.execute("SELECT pg_notify($1, $2)", "elephantq_new_job", final_queue)
        return str(row["id"])

    await conn.execute(
        """
        INSERT INTO elephantq_jobs (id, job_name, args, args_hash, max_attempts, priority, queue, unique_job, scheduled_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        uuid.UUID(job_id),
        job_name,
        args_json,
        args_hash,
        job_meta["retries"] + 1,
        final_priority,
        final_queue,
        final_unique,
        scheduled_at,
    )

    # Notify workers about the new job for instant processing
    await conn.execute("SELECT pg_notify($1, $2)", "elephantq_new_job", final_queue)
    return job_id


async def enqueue_job(
    pool: asyncpg.Pool,
    job_registry: JobRegistry,
    job_func: Callable[..., Any],
    priority: Optional[int] = None,
    queue: Optional[str] = None,
    scheduled_at: Optional[datetime] = None,
    unique: Optional[bool] = None,
    queueing_lock: Optional[str] = None,
    connection: Optional[asyncpg.Connection] = None,
    **kwargs,
) -> str:
    """
    Instance-based job enqueuing.

    Enqueue a job using specific pool and registry instances.

    Args:
        pool: Database connection pool
        job_registry: Job registry instance
        job_func: The decorated job function to enqueue
        priority: Job priority (lower number = higher priority). If None, uses job default
        queue: Queue name. If None, uses job default
        scheduled_at: When to execute the job. If None, executes immediately
        unique: Override job's unique setting. If True, prevents duplicate queued jobs
        queueing_lock: Custom deduplication key. Only one job with this lock can be queued at a time.
        connection: Optional existing asyncpg connection for transactional enqueue
        **kwargs: Arguments to pass to the job function

    Returns:
        str: The job ID, or existing job ID if unique/locked job already exists

    Raises:
        ValueError: If job is not registered or arguments are invalid
    """
    # Get job metadata from instance registry
    job_name = f"{job_func.__module__}.{job_func.__name__}"
    job_meta = job_registry.get_job(job_name)

    if not job_meta:
        raise ValueError(f"Job {job_name} is not registered in the provided registry")

    # Call the refactored helper functions
    _validate_job_arguments(job_name, job_meta, kwargs)

    # Override job settings with provided parameters
    final_priority = priority if priority is not None else job_meta["priority"]
    final_queue = queue if queue is not None else job_meta["queue"]
    final_unique = unique if unique is not None else job_meta["unique"]
    scheduled_at = _normalize_scheduled_time(scheduled_at)

    args_hash = compute_args_hash(kwargs) if final_unique else None

    async def _enqueue_with_connection(conn: asyncpg.Connection) -> str:
        job_id = str(uuid.uuid4())
        args_json = json.dumps(kwargs, default=str)

        return await _create_job_record(  # type: ignore[return-value]
            conn,
            job_id,
            job_name,
            job_meta,
            args_json,
            args_hash,
            final_priority,
            final_queue,
            final_unique,
            scheduled_at,
        )

    if connection is not None:
        return await _enqueue_with_connection(connection)

    if pool is None:
        raise ValueError("pool is required when no connection is provided")

    async with pool.acquire() as conn:
        return await _enqueue_with_connection(conn)


async def enqueue(
    job_func: Callable[..., Any],
    priority: Optional[int] = None,
    queue: Optional[str] = None,
    scheduled_at: Optional[datetime] = None,
    unique: Optional[bool] = None,
    connection: Optional[asyncpg.Connection] = None,
    **kwargs,
) -> str:
    """
    Global enqueue function using global pool and registry.

    Args:
        job_func: The decorated job function to enqueue
        priority: Job priority (lower number = higher priority). If None, uses job default
        queue: Queue name. If None, uses job default
        scheduled_at: When to execute the job. If None, executes immediately
        unique: Override job's unique setting. If True, prevents duplicate queued jobs
        connection: Optional existing asyncpg connection for transactional enqueue
        **kwargs: Arguments to pass to the job function

    Returns:
        str: The job ID, or existing job ID if unique job already exists

    Raises:
        ValueError: If job is not registered or arguments are invalid
    """
    from elephantq.core.registry import get_global_registry

    # Delegate to instance-based function using global instances
    pool = await get_context_pool()
    registry = get_global_registry()

    return await enqueue_job(
        pool=pool,
        job_registry=registry,
        job_func=job_func,
        priority=priority,
        queue=queue,
        scheduled_at=scheduled_at,
        unique=unique,
        connection=connection,
        **kwargs,
    )


async def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Look up a job and get all its details.

    This is really handy for checking on jobs - you get back everything
    from when it was created to how many times it's been retried.

    Args:
        job_id: The job ID to look up

    Returns:
        Dict with all the job details, or None if the job doesn't exist
    """
    pool = await get_context_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, job_name, args, status, attempts, max_attempts,
                   queue, priority, scheduled_at, last_error,
                   created_at, updated_at
            FROM elephantq_jobs
            WHERE id = $1
        """,
            uuid.UUID(job_id),
        )

        if not row:
            return None

        return {
            "id": str(row["id"]),
            "job_name": row["job_name"],
            "args": json.loads(row["args"]),
            "status": row["status"],
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "queue": row["queue"],
            "priority": row["priority"],
            "scheduled_at": (
                row["scheduled_at"].isoformat() if row["scheduled_at"] else None
            ),
            "last_error": row["last_error"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }


async def cancel_job(job_id: str) -> bool:
    """
    Cancel a job that's waiting in the queue.

    Note: You can only cancel jobs that haven't started running yet.
    Once a worker picks up a job, you'll need to let it finish.

    Args:
        job_id: The job ID to cancel

    Returns:
        True if we cancelled it, False if we couldn't (maybe it doesn't exist or already started)
    """
    pool = await get_context_pool()

    async with pool.acquire() as conn:
        # Only allow cancelling queued jobs
        result = await conn.execute(
            """
            UPDATE elephantq_jobs
            SET status = 'cancelled', updated_at = NOW()
            WHERE id = $1 AND status = 'queued'
        """,
            uuid.UUID(job_id),
        )

        return _rows_affected(result) == 1


async def retry_job(job_id: str) -> bool:
    """
    Retry a failed or dead letter job.

    Args:
        job_id: The job ID to retry

    Returns:
        bool: True if job was queued for retry, False if not found or not retryable
    """
    pool = await get_context_pool()

    async with pool.acquire() as conn:
        # Only allow retrying failed or dead letter jobs
        result = await conn.execute(
            """
            UPDATE elephantq_jobs
            SET status = 'queued', attempts = 0, last_error = NULL, updated_at = NOW()
            WHERE id = $1 AND status IN ('failed', 'dead_letter')
        """,
            uuid.UUID(job_id),
        )

        return _rows_affected(result) == 1


async def delete_job(job_id: str) -> bool:
    """
    Delete a job from the queue.

    Args:
        job_id: The job ID to delete

    Returns:
        bool: True if job was deleted, False if not found
    """
    pool = await get_context_pool()

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM elephantq_jobs WHERE id = $1
        """,
            uuid.UUID(job_id),
        )

        return _rows_affected(result) == 1


async def list_jobs(
    queue: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    List jobs with optional filtering.

    Args:
        queue: Filter by queue name
        status: Filter by status ('queued', 'done', 'failed', 'dead_letter', 'cancelled')
        limit: Maximum number of jobs to return
        offset: Number of jobs to skip

    Returns:
        List of job dictionaries
    """
    pool = await get_context_pool()

    # Build query with optional filters
    conditions: list[str] = []
    params: list[Any] = []
    param_count = 0

    if queue:
        param_count += 1
        conditions.append(f"queue = ${param_count}")
        params.append(queue)

    if status:
        param_count += 1
        conditions.append(f"status = ${param_count}")
        params.append(status)

    where_clause = ""
    if conditions:
        where_clause = f"WHERE {' AND '.join(conditions)}"

    param_count += 1
    limit_param = f"${param_count}"
    params.append(limit)

    param_count += 1
    offset_param = f"${param_count}"
    params.append(offset)

    query = f"""
        SELECT id, job_name, args, status, attempts, max_attempts,
               queue, priority, scheduled_at, last_error,
               created_at, updated_at
        FROM elephantq_jobs
        {where_clause}
        ORDER BY created_at DESC
        LIMIT {limit_param} OFFSET {offset_param}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

        return [
            {
                "id": str(row["id"]),
                "job_name": row["job_name"],
                "args": json.loads(row["args"]),
                "status": row["status"],
                "attempts": row["attempts"],
                "max_attempts": row["max_attempts"],
                "queue": row["queue"],
                "priority": row["priority"],
                "scheduled_at": (
                    row["scheduled_at"].isoformat() if row["scheduled_at"] else None
                ),
                "last_error": row["last_error"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
            }
            for row in rows
        ]


async def get_queue_stats() -> List[Dict[str, Any]]:
    """
    Get statistics for all queues.

    Returns:
        List of dictionaries with queue statistics
    """
    pool = await get_context_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                queue,
                COUNT(*) as total_jobs,
                COUNT(*) FILTER (WHERE status = 'queued') as queued,
                COUNT(*) FILTER (WHERE status = 'done') as done,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COUNT(*) FILTER (WHERE status = 'dead_letter') as dead_letter,
                COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled
            FROM elephantq_jobs
            GROUP BY queue
            ORDER BY queue
        """
        )

        return [
            {
                "queue": row["queue"],
                "total_jobs": row["total_jobs"],
                "queued": row["queued"],
                "done": row["done"],
                "failed": row["failed"],
                "dead_letter": row["dead_letter"],
                "cancelled": row["cancelled"],
            }
            for row in rows
        ]


async def schedule(
    job_func: Callable[..., Any],
    when: Optional[Union[datetime, timedelta, int, float]] = None,
    *,
    run_at: Optional[datetime] = None,
    run_in: Optional[Union[int, float, timedelta]] = None,
    **kwargs,
) -> str:
    """
    Schedule a job to run at a specific time or after a delay.

    Args:
        job_func: The job function to schedule
        when: When to run the job (positional argument). Can be:
            - datetime: Run at specific time
            - timedelta: Run after delay from now
            - int/float: Run after N seconds from now
        run_at: Schedule job at specific datetime (keyword argument)
        run_in: Schedule job after delay (keyword argument)
        **kwargs: Arguments to pass to the job function

    Returns:
        str: The job ID

    Examples:
        # Schedule at specific datetime (positional)
        await schedule(my_job, datetime(2025, 1, 15, 9, 0))

        # Schedule in 30 seconds (positional)
        await schedule(my_job, 30)

        # Schedule in 2 hours using timedelta (positional)
        await schedule(my_job, timedelta(hours=2))

        # Using keyword arguments
        await schedule(my_job, run_at=datetime(2025, 1, 15, 9, 0))
        await schedule(my_job, run_in=30)
    """
    # Handle positional 'when' parameter
    if when is not None:
        if run_at is not None or run_in is not None:
            raise ValueError("Cannot use 'when' parameter with 'run_at' or 'run_in'")

        if isinstance(when, datetime):
            scheduled_time = when
        elif isinstance(when, (int, float)):
            scheduled_time = datetime.now(timezone.utc) + timedelta(seconds=when)
        elif isinstance(when, timedelta):
            scheduled_time = datetime.now(timezone.utc) + when
        else:
            raise ValueError(
                f"Invalid 'when' parameter: {type(when)}. Must be datetime, timedelta, or int/float"
            )
    else:
        # Use keyword arguments
        if run_at is not None and run_in is not None:
            raise ValueError("Cannot specify both 'run_at' and 'run_in' - use only one")

        if run_at is None and run_in is None:
            raise ValueError("Must specify either 'when', 'run_at', or 'run_in'")

        if run_at is not None:
            scheduled_time = run_at
        else:
            if isinstance(run_in, (int, float)):
                scheduled_time = datetime.now(timezone.utc) + timedelta(seconds=run_in)
            elif isinstance(run_in, timedelta):
                scheduled_time = datetime.now(timezone.utc) + run_in
            else:
                raise ValueError(
                    f"Invalid 'run_in' parameter: {type(run_in)}. Must be int/float (seconds) or timedelta"
                )

    return await enqueue(job_func, scheduled_at=scheduled_time, **kwargs)
