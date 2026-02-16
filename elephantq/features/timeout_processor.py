"""
Enhanced job processor with timeout support for ElephantQ.
Extends base processor functionality with execution timeouts.
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional, Dict, Any

import asyncpg

from elephantq.core.registry import get_job
from elephantq.core.processor import process_jobs as base_process_jobs
from elephantq.core.retry import compute_retry_delay_seconds
from .flags import require_feature

logger = logging.getLogger(__name__)


class JobTimeoutError(Exception):
    """Raised when job execution exceeds timeout"""
    pass


async def get_job_timeout(job_id: str, conn: asyncpg.Connection) -> Optional[int]:
    """
    Get timeout value for a job from scheduling metadata
    
    Args:
        job_id: Job ID to check timeout for
        conn: Database connection
    
    Returns:
        Timeout in seconds, or None if no timeout set
    """
    # Check if scheduling metadata table exists and has timeout info
    try:
        timeout_data = await conn.fetchrow("""
            SELECT timeout_seconds FROM elephantq_pro_job_timeouts 
            WHERE job_id = $1
        """, job_id)
        
        if timeout_data:
            return timeout_data['timeout_seconds']
    except asyncpg.UndefinedTableError:
        # Table doesn't exist yet - will be created when needed
        pass
    
    return None


async def store_job_timeout(job_id: str, timeout_seconds: int, conn: asyncpg.Connection) -> bool:
    """
    Store timeout configuration for a job
    
    Args:
        job_id: Job ID
        timeout_seconds: Timeout in seconds
        conn: Database connection
    
    Returns:
        True if stored successfully
    """
    try:
        # Create timeout metadata table if it doesn't exist
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS elephantq_pro_job_timeouts (
                job_id UUID PRIMARY KEY REFERENCES elephantq_jobs(id) ON DELETE CASCADE,
                timeout_seconds INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Store timeout configuration
        await conn.execute("""
            INSERT INTO elephantq_pro_job_timeouts (job_id, timeout_seconds)
            VALUES ($1, $2)
            ON CONFLICT (job_id) DO UPDATE SET 
                timeout_seconds = EXCLUDED.timeout_seconds,
                updated_at = NOW()
        """, job_id, timeout_seconds)
        
        return True
    except Exception as e:
        logger.error(f"Failed to store job timeout: {e}")
        return False


async def execute_job_with_timeout(job_func, args: Dict[str, Any], timeout_seconds: int) -> Any:
    """
    Execute job function with timeout enforcement
    
    Args:
        job_func: Job function to execute
        args: Arguments to pass to job function
        timeout_seconds: Maximum execution time in seconds
    
    Returns:
        Job function result
        
    Raises:
        JobTimeoutError: If job exceeds timeout
        Exception: Any exception raised by the job function
    """
    try:
        # Execute job function with timeout
        result = await asyncio.wait_for(
            job_func(**args), 
            timeout=timeout_seconds
        )
        return result
    
    except asyncio.TimeoutError:
        raise JobTimeoutError(f"Job execution exceeded {timeout_seconds} seconds timeout")
    
    except Exception as e:
        # Re-raise other exceptions as-is
        raise e


async def process_jobs_with_timeout(conn: asyncpg.Connection, queue: str = "default") -> bool:
    """
    Enhanced job processor with timeout support for optional features.
    
    Args:
        conn: Database connection
        queue: Queue name to process jobs from
        
    Returns:
        bool: True if a job was processed, False if no jobs available
    """
    # Use a transaction to ensure atomicity
    skip_update_lock = os.environ.get("ELEPHANTQ_SKIP_UPDATE_LOCK", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    lock_clause = "" if skip_update_lock else "FOR UPDATE SKIP LOCKED"

    async with conn.transaction():
        # Lock and fetch the next job (ordered by priority then scheduled time)
        job_record = await conn.fetchrow(f"""
            SELECT * FROM elephantq_jobs
            WHERE status = 'queued' 
            AND queue = $1
            AND (scheduled_at IS NULL OR scheduled_at <= NOW())
            ORDER BY priority ASC, scheduled_at ASC NULLS FIRST, created_at ASC
            {lock_clause}
            LIMIT 1
        """, queue)
        
        if not job_record:
            return False

        job_id = job_record['id']
        job_name = job_record['job_name']
        args_data = json.loads(job_record['args'])
        attempts = job_record['attempts']
        max_attempts = job_record['max_attempts']
        
        # Check for job timeout configuration
        timeout_seconds = await get_job_timeout(str(job_id), conn)
        
        # Basic logging with timeout info
        start_time = time.time()
        timeout_info = f" (timeout: {timeout_seconds}s)" if timeout_seconds else ""
        logger.info(f"Processing job {job_id} ({job_name}) - attempt {attempts + 1}/{max_attempts}{timeout_info}")

        job_meta = get_job(job_name)
        if not job_meta:
            await conn.execute("""
                UPDATE elephantq_jobs
                SET status = 'dead_letter', 
                    attempts = max_attempts,
                    last_error = $1, 
                    updated_at = NOW()
                WHERE id = $2
            """, f"Job {job_name} not registered.", job_id)
            logger.error(f"Job {job_name} not registered - moved to dead letter queue")
            return True

        try:
            # Validate arguments if model is specified
            args_model = job_meta.get("args_model")
            if args_model:
                validated_args = args_model(**args_data).model_dump()
            else:
                validated_args = args_data

            # Execute the job function with timeout if configured
            if timeout_seconds:
                await execute_job_with_timeout(
                    job_meta['func'], 
                    validated_args, 
                    timeout_seconds
                )
            else:
                # No timeout - execute normally
                await job_meta['func'](**validated_args)
            
            # Calculate duration
            duration_ms = round((time.time() - start_time) * 1000, 2)
            
            # Mark as successful
            await conn.execute("""
                UPDATE elephantq_jobs
                SET status = 'done', 
                    updated_at = NOW()
                WHERE id = $1
            """, job_id)
            
            logger.info(f"Job {job_id} completed successfully in {duration_ms}ms")
            
            # Update any dependent jobs if dependency system is available
            try:
                from .dependencies import update_dependent_jobs
                await update_dependent_jobs(str(job_id))
            except ImportError:
                # Dependencies system not available, skip
                pass
            
            return True
            
        except JobTimeoutError as e:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.warning(f"Job {job_id} timed out after {duration_ms}ms: {str(e)}")
            
            new_attempts = attempts + 1
            if new_attempts >= max_attempts:
                # Permanently failed due to timeout
                await conn.execute("""
                    UPDATE elephantq_jobs
                    SET status = 'dead_letter', 
                        last_error = $1, 
                        attempts = $2, 
                        updated_at = NOW()
                    WHERE id = $3
                """, f"Job timed out: {str(e)}", new_attempts, job_id)
                logger.error(f"Job {job_id} moved to dead letter queue after timing out {new_attempts} times")
            else:
                retry_delay = compute_retry_delay_seconds(
                    attempt=new_attempts,
                    retry_delay=job_meta.get("retry_delay", 0),
                    retry_backoff=job_meta.get("retry_backoff", False),
                    retry_max_delay=job_meta.get("retry_max_delay"),
                )
                if retry_delay > 0:
                    await conn.execute(
                        """
                        UPDATE elephantq_jobs
                        SET status = 'queued', 
                            last_error = $1, 
                            attempts = $2, 
                            scheduled_at = NOW() + ($3 || ' seconds')::INTERVAL,
                            updated_at = NOW()
                        WHERE id = $4
                    """,
                        f"Job timed out: {str(e)}",
                        new_attempts,
                        str(retry_delay),
                        job_id,
                    )
                    logger.warning(
                        f"Job {job_id} will be retried in {retry_delay:.2f}s after timeout (attempt {new_attempts})"
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE elephantq_jobs
                        SET status = 'queued', 
                            last_error = $1, 
                            attempts = $2, 
                            scheduled_at = NULL,
                            updated_at = NOW()
                        WHERE id = $3
                    """,
                        f"Job timed out: {str(e)}",
                        new_attempts,
                        job_id,
                    )
                    logger.warning(
                        f"Job {job_id} will be retried immediately after timeout (attempt {new_attempts})"
                    )
            
            return True
            
        except Exception as e:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.exception(f"Job {job_id} execution failed in {duration_ms}ms")
            
            new_attempts = attempts + 1
            if new_attempts >= max_attempts:
                # Permanently failed - move to dead letter queue
                await conn.execute("""
                    UPDATE elephantq_jobs
                    SET status = 'dead_letter', 
                        last_error = $1, 
                        attempts = $2, 
                        updated_at = NOW()
                    WHERE id = $3
                """, f"Max retries exceeded: {str(e)}", new_attempts, job_id)
                logger.error(f"Job {job_id} moved to dead letter queue after {new_attempts} attempts")
            else:
                retry_delay = compute_retry_delay_seconds(
                    attempt=new_attempts,
                    retry_delay=job_meta.get("retry_delay", 0),
                    retry_backoff=job_meta.get("retry_backoff", False),
                    retry_max_delay=job_meta.get("retry_max_delay"),
                )
                if retry_delay > 0:
                    await conn.execute(
                        """
                        UPDATE elephantq_jobs
                        SET status = 'queued', 
                            last_error = $1, 
                            attempts = $2, 
                            scheduled_at = NOW() + ($3 || ' seconds')::INTERVAL,
                            updated_at = NOW()
                        WHERE id = $4
                    """,
                        str(e),
                        new_attempts,
                        str(retry_delay),
                        job_id,
                    )
                    logger.warning(
                        f"Job {job_id} will be retried in {retry_delay:.2f}s (attempt {new_attempts})"
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE elephantq_jobs
                        SET status = 'queued', 
                            last_error = $1, 
                            attempts = $2, 
                            scheduled_at = NULL,
                            updated_at = NOW()
                        WHERE id = $3
                    """,
                        str(e),
                        new_attempts,
                        job_id,
                    )
                    logger.warning(
                        f"Job {job_id} will be retried immediately (attempt {new_attempts})"
                    )
            
            return True


async def run_worker_with_timeout(concurrency: int = 4, run_once: bool = False, database_url: Optional[str] = None, queues: list[str] = None):
    """
    Run the job worker process with timeout support.
    
    Args:
        concurrency: Number of concurrent job processors
        run_once: If True, process available jobs once and exit
        database_url: Database URL to connect to
        queues: List of queue names to process. If None, processes 'default' queue
    """
    require_feature("timeouts_enabled", "Timeout processing")
    from elephantq.settings import ELEPHANTQ_DATABASE_URL
    from elephantq.db.connection import create_pool
    
    db_url = database_url or ELEPHANTQ_DATABASE_URL
    try:
        pool = await create_pool(db_url)
    except Exception as e:
        logger.error(f"Failed to create database pool: {e}")
        raise
    
    # Default to processing the 'default' queue
    if queues is None:
        queues = ["default"]
    
    logger.info(f"Starting ElephantQ worker with timeout support - concurrency: {concurrency}, queues: {queues}")
    
    try:
        if run_once:
            # Process jobs once from all queues
            if pool:
                async with pool.acquire() as conn:
                    for queue in queues:
                        await process_jobs_with_timeout(conn, queue)
            else:
                logger.warning("No database pool available for run_once processing")
        else:
            # Continuous processing with LISTEN/NOTIFY
            async def worker():
                # Each worker needs its own connection for LISTEN/NOTIFY
                listen_conn = await pool.acquire()
                notification_event = asyncio.Event()
                
                def notification_callback(connection, pid, channel, payload):
                    logger.debug(f"Received notification on {channel}: {payload}")
                    notification_event.set()
                
                try:
                    # Set up LISTEN for job notifications
                    await listen_conn.add_listener("elephantq_new_job", notification_callback)
                    
                    while True:
                        try:
                            # Process jobs from all queues first
                            any_processed = False
                            
                            # Use separate connection for job processing to avoid blocking LISTEN
                            async with pool.acquire() as job_conn:
                                for queue in queues:
                                    processed = await process_jobs_with_timeout(job_conn, queue)
                                    if processed:
                                        any_processed = True
                            
                            if not any_processed:
                                # No jobs available, wait for NOTIFY with timeout
                                try:
                                    # Wait for notification with 5 second timeout
                                    await asyncio.wait_for(notification_event.wait(), timeout=5.0)
                                    notification_event.clear()  # Reset for next notification
                                    logger.debug("Received job notification")
                                except asyncio.TimeoutError:
                                    # Timeout is normal - allows periodic checks for scheduled jobs
                                    logger.debug("No notifications, checking for scheduled jobs")
                                    pass
                                    
                        except Exception as e:
                            logger.exception(f"Worker error: {e}")
                            await asyncio.sleep(5)  # Error occurred, wait before retrying
                            
                finally:
                    await listen_conn.remove_listener("elephantq_new_job", notification_callback)
                    await pool.release(listen_conn)
            
            # Start multiple worker tasks for concurrency
            tasks = [asyncio.create_task(worker()) for _ in range(concurrency)]
            
            try:
                await asyncio.gather(*tasks)
            except KeyboardInterrupt:
                logger.info("Shutting down timeout workers...")
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if pool:
            await pool.close()
        logger.info("ElephantQ timeout worker stopped")


def enable_timeout_processing():
    """
    Enable timeout processing by monkey-patching the base process_jobs function.
    This allows timeout features to work with existing worker infrastructure.
    """
    require_feature("timeouts_enabled", "Timeout processing")
    # Replace the base process_jobs function with the timeout-enabled version
    import elephantq.core.processor
    elephantq.core.processor.process_jobs = process_jobs_with_timeout
    
    logger.info("ElephantQ timeout processing enabled")


def disable_timeout_processing():
    """
    Disable timeout processing and restore base functionality.
    """
    require_feature("timeouts_enabled", "Timeout processing")
    # Restore the base process_jobs function
    import elephantq.core.processor
    elephantq.core.processor.process_jobs = base_process_jobs
    
    logger.info("ElephantQ timeout processing disabled")


class TimeoutConfiguration:
    """Configuration manager for job timeouts"""
    
    @staticmethod
    async def set_global_timeout(timeout_seconds: int, database_url: Optional[str] = None):
        """
        Set a global default timeout for all jobs
        
        Args:
            timeout_seconds: Default timeout in seconds
            database_url: Database URL to connect to
        """
        require_feature("timeouts_enabled", "Timeout processing")
        from elephantq.settings import ELEPHANTQ_DATABASE_URL
        from elephantq.db.connection import create_pool
        
        db_url = database_url or ELEPHANTQ_DATABASE_URL
        pool = await create_pool(db_url)
        
        try:
            async with pool.acquire() as conn:
                # Create global timeout configuration table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS elephantq_pro_global_config (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                
                # Store global timeout
                await conn.execute("""
                    INSERT INTO elephantq_pro_global_config (key, value)
                    VALUES ('default_timeout_seconds', $1)
                    ON CONFLICT (key) DO UPDATE SET 
                        value = EXCLUDED.value,
                        updated_at = NOW()
                """, str(timeout_seconds))
                
                logger.info(f"Set global job timeout to {timeout_seconds} seconds")
        finally:
            await pool.close()
    
    @staticmethod
    async def get_global_timeout(database_url: Optional[str] = None) -> Optional[int]:
        """
        Get the global default timeout
        
        Args:
            database_url: Database URL to connect to
            
        Returns:
            Global timeout in seconds, or None if not set
        """
        require_feature("timeouts_enabled", "Timeout processing")
        from elephantq.settings import ELEPHANTQ_DATABASE_URL
        from elephantq.db.connection import create_pool
        
        db_url = database_url or ELEPHANTQ_DATABASE_URL
        pool = await create_pool(db_url)
        
        try:
            async with pool.acquire() as conn:
                try:
                    result = await conn.fetchrow("""
                        SELECT value FROM elephantq_pro_global_config 
                        WHERE key = 'default_timeout_seconds'
                    """)
                    
                    if result:
                        return int(result['value'])
                except asyncpg.UndefinedTableError:
                    # Table doesn't exist
                    pass
                
                return None
        finally:
            await pool.close()
    
    @staticmethod
    async def remove_global_timeout(database_url: Optional[str] = None):
        """
        Remove global timeout configuration
        
        Args:
            database_url: Database URL to connect to
        """
        from elephantq.settings import ELEPHANTQ_DATABASE_URL
        from elephantq.db.connection import create_pool
        
        db_url = database_url or ELEPHANTQ_DATABASE_URL
        pool = await create_pool(db_url)
        
        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                    DELETE FROM elephantq_pro_global_config 
                    WHERE key = 'default_timeout_seconds'
                """)
                
                logger.info("Removed global job timeout")
        finally:
            await pool.close()


# Global timeout processing state
_timeout_processing_enabled = False


def is_timeout_processing_enabled() -> bool:
    """Check if timeout processing is currently enabled"""
    require_feature("timeouts_enabled", "Timeout processing")
    return _timeout_processing_enabled


def toggle_timeout_processing(enabled: bool = True):
    """
    Toggle timeout processing on/off
    
    Args:
        enabled: True to enable timeout processing, False to disable
    """
    require_feature("timeouts_enabled", "Timeout processing")
    global _timeout_processing_enabled
    
    if enabled and not _timeout_processing_enabled:
        enable_timeout_processing()
        _timeout_processing_enabled = True
    elif not enabled and _timeout_processing_enabled:
        disable_timeout_processing()
        _timeout_processing_enabled = False
