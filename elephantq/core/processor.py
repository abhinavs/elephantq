"""
Job processing engine.

The backend-aware path: process_job_via_backend() is the only active
processing function. It fetches, executes, and updates jobs through
the StorageBackend abstraction.
"""

import asyncio
import inspect
import json
import logging
import os
import time
from typing import Any, List, Optional

from elephantq.core.registry import JobRegistry
from elephantq.core.retry import compute_retry_delay_seconds

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
    # Args may be a JSON string (Memory/SQLite) or already parsed dict (Postgres JSONB)
    raw_args = job_record["args"]
    if isinstance(raw_args, dict):
        args_data = raw_args
    elif isinstance(raw_args, str):
        try:
            args_data = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise ValueError(f"Corrupted JSON data: {str(e)}") from e
    else:
        raise ValueError(f"Corrupted JSON data: unexpected type {type(raw_args)}")

    # Validate arguments if model is specified
    args_model = job_meta.get("args_model")
    if args_model:
        try:
            validated_args = args_model(**args_data).model_dump()
        except (TypeError, ValueError, AttributeError) as validation_error:
            raise ValueError(
                f"Corrupted argument data: {str(validation_error)}"
            ) from validation_error
    else:
        validated_args = args_data

    # Inject JobContext if the function signature has it
    from elephantq.job import JobContext

    func = job_meta["func"]
    sig = inspect.signature(func)
    for param_name, param in sig.parameters.items():
        if param.annotation is JobContext:
            validated_args[param_name] = JobContext(
                job_id=str(job_record["id"]),
                job_name=job_record["job_name"],
                attempt=job_record["attempts"],
                max_attempts=job_record["max_attempts"],
                queue=job_record.get("queue", "default"),
                worker_id=str(job_record.get("worker_id", "")),
                scheduled_at=job_record.get("scheduled_at"),
                created_at=job_record.get("created_at"),
            )
            break

    # Determine timeout: per-job overrides global setting
    from elephantq.settings import get_settings

    timeout = job_meta.get("timeout")
    if timeout is None:
        timeout = get_settings().job_timeout

    # Execute the job function (outside transaction) with optional timeout
    try:
        if timeout:
            await asyncio.wait_for(func(**validated_args), timeout=timeout)
        else:
            await func(**validated_args)
        return True, None
    except asyncio.TimeoutError:
        return False, f"Job timed out after {timeout}s"
    except Exception as e:
        return False, str(e)


async def process_job_via_backend(
    backend: Any,
    job_registry: JobRegistry,
    queues: Optional[List[str]] = None,
    worker_id: Optional[str] = None,
) -> bool:
    """
    Process a single job using a StorageBackend.

    This is the primary processing path. It fetches, executes, and
    updates jobs through the backend abstraction.

    Args:
        backend: StorageBackend instance
        job_registry: JobRegistry for job lookup
        queues: Queue names to process from
        worker_id: Worker ID for tracking

    Returns:
        True if a job was processed, False if no jobs available
    """
    from elephantq.settings import get_settings

    job_record = await backend.fetch_and_lock_job(
        queues=queues,
        worker_id=worker_id,
    )
    if not job_record:
        return False

    job_id = str(job_record["id"])
    job_name = job_record["job_name"]
    max_attempts = job_record["max_attempts"]
    attempts = job_record["attempts"]

    start_time = time.time()
    logger.info(
        f"Processing job {job_id} ({job_name}) - attempt {attempts + 1}/{max_attempts}"
    )

    job_meta = job_registry.get_job(job_name)
    if not job_meta:
        await backend.mark_job_dead_letter(
            job_id,
            attempts=max_attempts,
            error=f"Job {job_name} not registered.",
        )
        logger.error(f"Job {job_name} not registered - moved to dead letter queue")
        return True

    try:
        job_success, job_error = await _execute_job_safely(job_record, job_meta)
    except ValueError as corruption_error:
        logger.error(f"Job {job_id} has corrupted data: {corruption_error}")
        await backend.mark_job_dead_letter(
            job_id,
            attempts=max_attempts,
            error=str(corruption_error),
        )
        return True

    duration_ms = round((time.time() - start_time) * 1000, 2)

    if job_success:
        settings = get_settings()
        await backend.mark_job_done(job_id, result_ttl=settings.result_ttl)
        logger.info(f"Job {job_id} completed in {duration_ms}ms")
    else:
        new_attempts = attempts + 1
        if new_attempts >= max_attempts:
            await backend.mark_job_dead_letter(
                job_id,
                attempts=new_attempts,
                error=f"Max retries exceeded: {job_error}",
            )
            logger.error(
                f"Job {job_id} moved to dead letter after {new_attempts} attempts"
            )
        else:
            retry_delay = compute_retry_delay_seconds(
                attempt=new_attempts,
                retry_delay=job_meta.get("retry_delay", 0),
                retry_backoff=job_meta.get("retry_backoff", False),
                retry_max_delay=job_meta.get("retry_max_delay"),
            )
            await backend.mark_job_failed(
                job_id,
                attempts=new_attempts,
                error=str(job_error),
                retry_delay=retry_delay if retry_delay > 0 else None,
            )
            logger.warning(
                f"Job {job_id} failed (attempt {new_attempts}), "
                + (
                    f"retrying in {retry_delay:.1f}s"
                    if retry_delay > 0
                    else "retrying immediately"
                )
            )

    return True
