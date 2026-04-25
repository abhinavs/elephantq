"""
Soniq Worker

Processes jobs from the queue using a StorageBackend.
Handles concurrency, heartbeat, signal handling, and cleanup.
"""

import asyncio
import logging
import time
from typing import Any, List, Optional

from ..settings import SoniqSettings, get_settings
from .processor import process_job_via_backend
from .registry import JobRegistry

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
        settings: Optional[SoniqSettings] = None,
        hooks: Optional[dict] = None,
    ):
        self._backend = backend
        self._registry = registry
        self._settings = settings or get_settings()
        self._last_cleanup = 0.0
        self._hooks = hooks or {}

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
                hooks=self._hooks,
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
        from ..utils.signals import GracefulSignalHandler

        shutdown_event = asyncio.Event()
        notification_event = asyncio.Event()
        signal_handler = GracefulSignalHandler()
        signal_handler.setup_signal_handlers(shutdown_event)

        # Set up LISTEN/NOTIFY if backend supports push notifications
        listen_handle = None
        if self._backend.supports_push_notify:

            def on_notification(connection, pid, channel, payload):
                logger.debug(f"Received notification on {channel}: {payload}")
                notification_event.set()

            try:
                listen_handle = await self._backend.listen_for_jobs(on_notification)
            except Exception as e:
                logger.warning(f"Failed to set up LISTEN/NOTIFY: {e}")

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
                        hooks=self._hooks,
                    )

                    if not processed:
                        # No jobs — wait for notification or timeout
                        notification_event.clear()
                        try:
                            # Wait for either shutdown, notification, or timeout
                            wait_tasks = [shutdown_event.wait()]
                            if self._backend.supports_push_notify:
                                wait_tasks.append(notification_event.wait())

                            done, _ = await asyncio.wait(
                                [asyncio.create_task(t) for t in wait_tasks],
                                timeout=self._settings.poll_interval,
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            # Cancel and await pending wait tasks
                            for t in _:
                                t.cancel()
                            await asyncio.gather(*_, return_exceptions=True)
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
                    # Shutdown path: if the DB is already unreachable, the
                    # stale-worker sweep will mark this worker stopped later.
                    logger.debug(
                        "mark_worker_stopped failed for %s during shutdown",
                        worker_id,
                        exc_info=True,
                    )

            # Clean up LISTEN connection
            if listen_handle is not None:
                try:
                    await listen_handle.remove_listener(
                        "soniq_new_job", on_notification
                    )
                except Exception:
                    # Connection may already be broken during shutdown.
                    logger.debug(
                        "remove_listener failed during shutdown", exc_info=True
                    )
                try:
                    if self._backend.supports_connection_pool:
                        await self._backend.pool.release(listen_handle)
                except Exception:
                    logger.debug(
                        "LISTEN connection release failed during shutdown",
                        exc_info=True,
                    )

        return True

    async def _heartbeat_loop(
        self, worker_id: str, shutdown_event: asyncio.Event
    ) -> None:
        """Send periodic heartbeat updates."""
        interval = self._settings.heartbeat_interval
        while not shutdown_event.is_set():
            try:
                await self._backend.update_heartbeat(worker_id)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e}")
                await asyncio.sleep(interval)

    async def _maybe_cleanup(self) -> None:
        """Run periodic cleanup if enough time has passed.

        Uses an advisory-lock leader guard so that, in multi-worker deployments,
        only one worker performs pruning and stale-worker cleanup per tick.
        Backends without advisory-lock support (Memory, SQLite) always run.
        """
        current = time.time()
        if current - self._last_cleanup < self._settings.cleanup_interval:
            return

        from .leadership import with_advisory_lock

        try:
            async with with_advisory_lock(self._backend, "soniq.maintenance") as leader:
                if leader:
                    await self._backend.delete_expired_jobs()
                    await self._backend.cleanup_stale_workers(
                        stale_threshold_seconds=int(self._settings.heartbeat_timeout),
                    )
            self._last_cleanup = current
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")
            self._last_cleanup = current
