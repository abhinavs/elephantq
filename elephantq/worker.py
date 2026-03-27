"""
ElephantQ Worker

Processes jobs from the queue using a StorageBackend.
Handles concurrency, heartbeat, signal handling, and cleanup.
"""

import asyncio
import logging
import time
from typing import Any, List, Optional

from .core.processor import process_job_via_backend
from .core.registry import JobRegistry
from .settings import ElephantQSettings, get_settings

logger = logging.getLogger(__name__)


class Worker:
    """
    Job processing worker.

    Fetches jobs from the backend, executes them, and updates status.
    Supports both run-once (process available jobs and exit) and
    continuous (long-running with LISTEN/NOTIFY) modes.
    """

    def __init__(
        self,
        backend: Any,
        registry: JobRegistry,
        settings: Optional[ElephantQSettings] = None,
    ):
        self._backend = backend
        self._registry = registry
        self._settings = settings or get_settings()

    async def run(
        self,
        concurrency: int = 4,
        run_once: bool = False,
        queues: Optional[List[str]] = None,
    ) -> bool:
        """
        Run the worker.

        Args:
            concurrency: Number of concurrent job processing tasks
            run_once: If True, process available jobs once and exit
            queues: Queue names to process. None means all queues.

        Returns:
            True if any jobs were processed
        """
        queue_info = "all queues" if queues is None else f"queues: {queues}"
        logger.info(
            f"Starting worker - concurrency: {concurrency}, processing: {queue_info}"
        )

        try:
            if run_once:
                return await self.run_once(queues)
            else:
                return await self._run_continuous(concurrency, queues)
        finally:
            logger.info("Worker stopped")

    async def run_once(
        self,
        queues: Optional[List[str]] = None,
        max_jobs: Optional[int] = None,
    ) -> bool:
        """
        Process available jobs once and exit.

        Args:
            queues: Queue names to process
            max_jobs: Max jobs to process. None means no limit.

        Returns:
            True if any jobs were processed
        """
        jobs_processed = 0

        while max_jobs is None or jobs_processed < max_jobs:
            processed = await process_job_via_backend(
                backend=self._backend,
                job_registry=self._registry,
                queues=queues,
            )

            if processed:
                jobs_processed += 1
            else:
                break

        return jobs_processed > 0

    async def _run_continuous(
        self, concurrency: int, queues: Optional[List[str]] = None
    ) -> bool:
        """Run continuous worker with heartbeat and signal handling."""
        from .utils.signals import GracefulSignalHandler

        shutdown_event = asyncio.Event()
        signal_handler = GracefulSignalHandler()
        signal_handler.setup_signal_handlers(shutdown_event)

        # Start heartbeat if backend supports worker tracking
        heartbeat_task = None
        worker_id = None
        if hasattr(self._backend, "register_worker"):
            import os
            import platform
            import uuid

            worker_id = str(uuid.uuid4())
            await self._backend.register_worker(
                worker_id=worker_id,
                hostname=platform.node(),
                pid=os.getpid(),
                queues=queues or [],
                concurrency=concurrency,
            )
            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(worker_id, shutdown_event)
            )

        async def worker_task():
            while not shutdown_event.is_set():
                try:
                    processed = await process_job_via_backend(
                        backend=self._backend,
                        job_registry=self._registry,
                        queues=queues,
                        worker_id=worker_id,
                    )

                    if not processed:
                        # No jobs — poll with timeout
                        try:
                            await asyncio.wait_for(
                                shutdown_event.wait(),
                                timeout=self._settings.notification_timeout,
                            )
                        except asyncio.TimeoutError:
                            pass  # Normal — check for jobs again

                    # Periodic cleanup
                    await self._maybe_cleanup()

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.exception(f"Worker error: {e}")
                    await asyncio.sleep(self._settings.error_retry_delay)

        tasks = [asyncio.create_task(worker_task()) for _ in range(concurrency)]

        try:
            shutdown_task = asyncio.create_task(shutdown_event.wait())
            worker_gather = asyncio.ensure_future(
                asyncio.gather(*tasks, return_exceptions=True)
            )

            done, pending = await asyncio.wait(
                {worker_gather, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if shutdown_task in done:
                logger.info("Graceful shutdown initiated...")
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

            for task in pending:
                task.cancel()

        except KeyboardInterrupt:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            signal_handler.restore_signal_handlers()

            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            if worker_id and hasattr(self._backend, "mark_worker_stopped"):
                try:
                    await self._backend.mark_worker_stopped(worker_id)
                except Exception:
                    pass

        return True

    async def _heartbeat_loop(
        self, worker_id: str, shutdown_event: asyncio.Event
    ) -> None:
        """Send periodic heartbeat updates."""
        interval = self._settings.worker_heartbeat_interval
        while not shutdown_event.is_set():
            try:
                await self._backend.update_heartbeat(worker_id)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e}")
                await asyncio.sleep(interval)

    _last_cleanup = 0.0

    async def _maybe_cleanup(self) -> None:
        """Run periodic cleanup if enough time has passed."""
        current = time.time()
        if current - self._last_cleanup < self._settings.cleanup_interval:
            return

        try:
            await self._backend.delete_expired_jobs()
            await self._backend.cleanup_stale_workers(
                stale_threshold_seconds=int(self._settings.stale_worker_threshold),
            )
            self._last_cleanup = current
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")
            self._last_cleanup = current
