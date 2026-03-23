"""
Job processing engine with proper transaction handling
Core functionality only
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Callable, List, Optional, Union

import asyncpg

from elephantq.core.heartbeat import WorkerHeartbeat
from elephantq.core.registry import JobRegistry, get_job
from elephantq.core.retry import compute_retry_delay_seconds

# Basic logging for free edition
logger = logging.getLogger(__name__)


def _should_skip_update_lock() -> bool:
    """
    Check if row-level locking should be skipped.

    Only honored in debug or testing mode to prevent accidental
    duplicate job execution in production.
    """
    env_val = os.environ.get("ELEPHANTQ_SKIP_UPDATE_LOCK", "").lower()
    if env_val not in {"1", "true", "yes", "on"}:
        return False

    from elephantq.settings import get_settings

    settings = get_settings()
    if settings.debug or settings.environment == "testing":
        return True

    logger.warning(
        "ELEPHANTQ_SKIP_UPDATE_LOCK is set but ignored in production mode. "
        "Set ELEPHANTQ_DEBUG=true or ELEPHANTQ_ENVIRONMENT=testing to enable."
    )
    return False


async def _move_job_to_dead_letter(
    conn: asyncpg.Connection, job_id: uuid.UUID, max_attempts: int, error_message: str
) -> None:
    """
    Move a job to dead letter queue due to corruption or permanent failure.

    Args:
        conn: Database connection
        job_id: Job ID to move
        max_attempts: Maximum attempts for the job
        error_message: Error description
    """
    async with conn.transaction():
        await conn.execute(
            """
            UPDATE elephantq_jobs
            SET status = 'dead_letter',
                attempts = $2,
                last_error = $3,
                updated_at = NOW()
            WHERE id = $1
        """,
            job_id,
            max_attempts,
            error_message,
        )
    logger.error(f"Job {job_id} moved to dead letter queue: {error_message}")


async def _fetch_and_lock_job(
    conn: asyncpg.Connection,
    queue: Optional[Union[str, List[str]]],
    heartbeat: Optional["WorkerHeartbeat"] = None,
) -> Optional[dict]:
    """
    Fetch and lock a job from the queue in a transaction.

    Args:
        conn: Database connection
        queue: Queue specification
        heartbeat: Optional worker heartbeat for tracking

    Returns:
        Job record dict or None if no jobs available
    """
    lock_clause = "" if _should_skip_update_lock() else "FOR UPDATE SKIP LOCKED"
    async with conn.transaction():
        # Lock and fetch the next job (ordered by priority then scheduled time)
        if queue is None:
            # Process from ANY queue (no filtering)
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
        elif isinstance(queue, list):
            # Process from multiple specific queues efficiently
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
                queue,
            )
        else:
            # Process from single specific queue
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
                queue,
            )
        if not job_record:
            return None

        # Mark job as processing to prevent other workers from picking it up
        job_id = job_record["id"]
        if heartbeat:
            # Update job with worker tracking
            await conn.execute(
                """
                UPDATE elephantq_jobs
                SET status = 'processing',
                    worker_id = $2,
                    updated_at = NOW()
                WHERE id = $1
            """,
                job_id,
                heartbeat.worker_id,
            )
        else:
            await conn.execute(
                """
                UPDATE elephantq_jobs
                SET status = 'processing',
                    updated_at = NOW()
                WHERE id = $1
            """,
                job_id,
            )

    return dict(job_record)


async def _execute_job_safely(
    job_record: dict, job_meta: dict
) -> tuple[bool, Optional[str]]:
    """
    Execute a job function safely with proper error handling.

    Args:
        job_record: Job record from database
        job_meta: Job metadata from registry

    Returns:
        tuple: (success: bool, error_message: Optional[str])
    """
    # Parse job arguments with corruption handling
    try:
        args_data = json.loads(job_record["args"])
    except Exception as e:
        # Catch both JSONDecodeError and TypeError broadly for corrupted data
        if "json" in str(type(e)).lower() or isinstance(e, (TypeError, ValueError)):
            # This will be handled by the caller
            raise ValueError(f"Corrupted JSON data: {str(e)}") from e
        else:
            # Other exception types - re-raise
            raise

    # Validate arguments if model is specified
    args_model = job_meta.get("args_model")
    if args_model:
        try:
            validated_args = args_model(**args_data).model_dump()
        except (TypeError, ValueError, AttributeError) as validation_error:
            # This will be handled by the caller
            raise ValueError(
                f"Corrupted argument data: {str(validation_error)}"
            ) from validation_error
    else:
        validated_args = args_data

    # Determine timeout: per-job overrides global setting
    from elephantq.settings import get_settings

    timeout = job_meta.get("timeout")
    if timeout is None:
        timeout = get_settings().job_timeout

    # Execute the job function (outside transaction) with optional timeout
    try:
        if timeout:
            await asyncio.wait_for(job_meta["func"](**validated_args), timeout=timeout)
        else:
            await job_meta["func"](**validated_args)
        return True, None
    except asyncio.TimeoutError:
        return False, f"Job timed out after {timeout}s"
    except Exception as e:
        # All job execution errors are treated as retryable failures.
        # Corruption is only detected at the data layer (JSON parse,
        # Pydantic validation) above — never by inspecting error messages.
        return False, str(e)


async def _update_job_status(
    conn: asyncpg.Connection,
    job_record: dict,
    job_meta: dict,
    success: bool,
    error_message: Optional[str],
    duration_ms: float,
) -> None:
    """
    Update job status in database based on execution result.

    Args:
        conn: Database connection
        job_record: Original job record
        success: Whether job execution succeeded
        error_message: Error message if job failed
        duration_ms: Job execution duration in milliseconds
    """
    job_id = job_record["id"]
    attempts = job_record["attempts"]
    max_attempts = job_record["max_attempts"]

    async with conn.transaction():
        if success:
            # Handle job result TTL setting
            from elephantq.settings import get_settings

            settings = get_settings()

            if settings.result_ttl == 0:
                # Delete immediately (TTL = 0)
                await conn.execute(
                    """
                    DELETE FROM elephantq_jobs
                    WHERE id = $1
                """,
                    job_id,
                )
                logger.info(
                    f"Job {job_id} completed successfully in {duration_ms}ms (deleted immediately)"
                )
            else:
                # Keep with status 'done' and set expires_at for TTL cleanup
                await conn.execute(
                    """
                    UPDATE elephantq_jobs
                    SET status = 'done',
                        expires_at = NOW() + ($2 || ' seconds')::INTERVAL,
                        updated_at = NOW()
                    WHERE id = $1
                """,
                    job_id,
                    str(settings.result_ttl),
                )
                logger.info(
                    f"Job {job_id} completed successfully in {duration_ms}ms (expires in {settings.result_ttl}s)"
                )
        else:
            # Job failed - increment attempts
            new_attempts = attempts + 1
            if new_attempts >= max_attempts:
                # Permanently failed - move to dead letter queue
                await conn.execute(
                    """
                    UPDATE elephantq_jobs
                    SET status = 'dead_letter',
                        attempts = $1,
                        last_error = $2,
                        updated_at = NOW()
                    WHERE id = $3
                """,
                    new_attempts,
                    f"Max retries exceeded: {error_message}",
                    job_id,
                )
                logger.error(
                    f"Job {job_id} moved to dead letter queue after {new_attempts} attempts"
                )
            else:
                retry_delay = compute_retry_delay_seconds(
                    attempt=new_attempts,
                    retry_delay=job_meta.get("retry_delay", 0),
                    retry_backoff=job_meta.get("retry_backoff", False),
                    retry_max_delay=job_meta.get("retry_max_delay"),
                )

                # Use scheduled_at to delay retries without blocking workers.
                if retry_delay > 0:
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
                        new_attempts,
                        error_message,
                        str(retry_delay),
                        job_id,
                    )
                    logger.warning(
                        f"Job {job_id} will be retried in {retry_delay:.2f}s (attempt {new_attempts} failed)"
                    )
                else:
                    # Retry immediately
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
                        new_attempts,
                        error_message,
                        job_id,
                    )
                    logger.warning(
                        f"Job {job_id} will be retried immediately (attempt {new_attempts} failed)"
                    )


async def _process_job_common(
    conn: asyncpg.Connection,
    job_lookup: Callable[[str], Optional[dict]],
    queue: Optional[Union[str, List[str]]] = "default",
    heartbeat: Optional["WorkerHeartbeat"] = None,
) -> bool:
    """
    Shared job processing logic for both global and instance-based APIs.

    Executes jobs OUTSIDE of database transactions to prevent long-running jobs
    from holding database locks and causing deadlocks.

    Args:
        conn: Database connection
        job_lookup: Callable that takes a job_name and returns job metadata or None
        queue: Queue specification (None, str, or list of str)
        heartbeat: Optional worker heartbeat tracker

    Returns:
        bool: True if a job was processed, False if no jobs available
    """
    job_record = await _fetch_and_lock_job(conn, queue, heartbeat)
    if not job_record:
        return False

    job_id = job_record["id"]
    job_name = job_record["job_name"]
    max_attempts = job_record["max_attempts"]
    attempts = job_record["attempts"]

    start_time = time.time()
    logger.info(
        f"Processing job {job_id} ({job_name}) - attempt {attempts + 1}/{max_attempts}"
    )

    job_meta = job_lookup(job_name)
    if not job_meta:
        await conn.execute(
            """
            UPDATE elephantq_jobs
            SET status = 'dead_letter',
                attempts = max_attempts,
                last_error = $1,
                updated_at = NOW()
            WHERE id = $2
        """,
            f"Job {job_name} not registered.",
            job_id,
        )
        logger.error(f"Job {job_name} not registered - moved to dead letter queue")
        return True

    try:
        job_success, job_error = await _execute_job_safely(job_record, job_meta)
    except ValueError as corruption_error:
        logger.error(f"Job {job_id} has corrupted data: {corruption_error}")
        await _move_job_to_dead_letter(
            conn, job_id, max_attempts, str(corruption_error)
        )
        return True

    duration_ms = round((time.time() - start_time) * 1000, 2)
    await _update_job_status(
        conn, job_record, job_meta, job_success, job_error, duration_ms
    )

    return True


async def process_jobs(
    conn: asyncpg.Connection,
    queue: Optional[Union[str, List[str]]] = "default",
    heartbeat: Optional["WorkerHeartbeat"] = None,
) -> bool:
    """
    Process a single job from the queue(s) using the global registry.

    Args:
        conn: Database connection
        queue: Queue specification (None, str, or list of str)

    Returns:
        bool: True if a job was processed, False if no jobs available
    """
    return await _process_job_common(conn, get_job, queue, heartbeat)


async def process_jobs_with_registry(
    conn: asyncpg.Connection,
    job_registry: JobRegistry,
    queue: Optional[Union[str, List[str]]] = "default",
    heartbeat: Optional["WorkerHeartbeat"] = None,
) -> bool:
    """
    Instance-based job processing with explicit JobRegistry.

    Args:
        conn: Database connection
        job_registry: JobRegistry instance to use for job lookup
        queue: Queue specification (None, str, or list of str)
        heartbeat: Optional worker heartbeat tracker

    Returns:
        bool: True if a job was processed, False if no jobs available
    """
    return await _process_job_common(conn, job_registry.get_job, queue, heartbeat)
