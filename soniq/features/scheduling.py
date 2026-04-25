"""
Advanced scheduling with fluent interface for Soniq.
"""

import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from soniq import enqueue

from .flags import require_feature


class JobScheduleBuilder:
    """Fluent interface for advanced job scheduling"""

    def __init__(self, job_func: Callable[..., Any]):
        self.job_func = job_func
        self._scheduled_at: Optional[datetime] = None
        self._priority: Optional[int] = None
        self._queue: Optional[str] = None
        self._retries: Optional[int] = None
        self._tags: List[str] = []
        self._timeout: Optional[int] = None
        self._condition: Optional[Callable[[], bool]] = None
        self._dry_run: bool = False

    def in_seconds(self, seconds: int) -> "JobScheduleBuilder":
        """Schedule job to run in X seconds"""
        self._scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        return self

    def in_minutes(self, minutes: int) -> "JobScheduleBuilder":
        """Schedule job to run in X minutes"""
        self._scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        return self

    def in_hours(self, hours: int) -> "JobScheduleBuilder":
        """Schedule job to run in X hours"""
        self._scheduled_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        return self

    def in_days(self, days: int) -> "JobScheduleBuilder":
        """Schedule job to run in X days"""
        self._scheduled_at = datetime.now(timezone.utc) + timedelta(days=days)
        return self

    def at_time(self, time_str: str) -> "JobScheduleBuilder":
        """
        Schedule job at specific time.

        Args:
            time_str: ISO format datetime string or HH:MM format for today.
                      HH:MM is interpreted in the machine's local timezone.
                      ISO strings with timezone info are converted to UTC.
                      ISO strings without timezone info are treated as local time.
        """
        try:
            # Try parsing as ISO datetime first
            self._scheduled_at = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except ValueError:
            try:
                # Try parsing as HH:MM for today in local time
                time_part = datetime.strptime(time_str, "%H:%M").time()
                today = datetime.now().date()
                self._scheduled_at = datetime.combine(today, time_part)

                # If the time has already passed today, schedule for tomorrow
                if self._scheduled_at <= datetime.now():
                    self._scheduled_at += timedelta(days=1)
            except ValueError:
                raise ValueError(
                    f"Invalid time format: {time_str}. Use ISO format or HH:MM"
                )

        return self

    def with_priority(self, priority: int) -> "JobScheduleBuilder":
        """Set job priority (lower number = higher priority)"""
        self._priority = priority
        return self

    def in_queue(self, queue: str) -> "JobScheduleBuilder":
        """Set the queue for job execution"""
        self._queue = queue
        return self

    def with_retries(self, retries: int) -> "JobScheduleBuilder":
        """Set maximum retry attempts"""
        self._retries = retries
        return self

    def with_tags(self, *tags: str) -> "JobScheduleBuilder":
        """Add tags for job categorization"""
        self._tags.extend(tags)
        return self

    def with_timeout(self, timeout_seconds: int) -> "JobScheduleBuilder":
        """Set job execution timeout"""
        self._timeout = timeout_seconds
        return self

    def if_condition(self, condition: Callable[[], bool]) -> "JobScheduleBuilder":
        """Add condition that must be true for job to execute"""
        self._condition = condition
        return self

    def dry_run(self) -> "JobScheduleBuilder":
        """Enable dry run mode (preview configuration without scheduling)"""
        self._dry_run = True
        return self

    async def enqueue(self, connection=None, **kwargs) -> Union[str, Dict[str, Any]]:
        """
        Enqueue the job with configured options

        Args:
            connection: Optional database connection to join an existing transaction
            **kwargs: Arguments to pass to the job

        Returns:
            Job ID if scheduled, or configuration dict if dry run
        """
        if self._dry_run:
            return self._get_configuration(**kwargs)

        # Check condition if specified
        if self._condition and not self._condition():
            raise RuntimeError("Job condition not satisfied")

        # Use custom enqueue parameters if specified, otherwise use job defaults
        enqueue_kwargs: Dict[str, Any] = {}
        if self._scheduled_at:
            enqueue_kwargs["scheduled_at"] = self._scheduled_at
        if self._priority is not None:
            enqueue_kwargs["priority"] = self._priority
        if self._queue:
            enqueue_kwargs["queue"] = self._queue

        # Add job arguments
        enqueue_kwargs.update(kwargs)

        # Per-call `with_timeout(...)` is captured in the in-memory metadata
        # below. Enforcement happens at the registry level via
        # `@app.job(timeout=...)`; the processor reads the per-job-meta
        # value, which `JobScheduleBuilder` does not currently override.
        # See the per-call timeout note in scheduling docs.
        if connection is not None:
            enqueue_kwargs["connection"] = connection
        job_id = await enqueue(self.job_func, **enqueue_kwargs)

        # Store additional metadata (tags, timeout, etc.)
        if any([self._tags, self._timeout, self._retries is not None]):
            _scheduler_metadata[job_id] = {
                "tags": self._tags,
                "timeout": self._timeout,
                "max_retries": self._retries,
            }

        return job_id  # type: ignore[no-any-return]

    def _get_configuration(self, **kwargs) -> Dict[str, Any]:
        """Get job configuration for dry run"""
        return {
            "job_function": f"{self.job_func.__module__}.{self.job_func.__name__}",
            "scheduled_at": (
                self._scheduled_at.isoformat() if self._scheduled_at else None
            ),
            "priority": self._priority,
            "queue": self._queue,
            "max_retries": self._retries,
            "tags": self._tags,
            "timeout": self._timeout,
            "condition": "Custom condition" if self._condition else None,
            "arguments": kwargs,
        }


class _BoundedDict(OrderedDict):
    """OrderedDict that evicts the oldest entry when capacity is exceeded."""

    def __init__(self, max_size: int = 10_000, *args, **kwargs):
        self.max_size = max_size
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        while len(self) > self.max_size:
            self.popitem(last=False)


# Global metadata storage for scheduler features (bounded to prevent memory leaks)
_scheduler_metadata: _BoundedDict = _BoundedDict(max_size=10_000)


class BatchScheduler:
    """Batch scheduler for multiple jobs"""

    def __init__(self, batch_name: Optional[str] = None):
        self.batch_name = batch_name or f"batch_{uuid.uuid4().hex[:8]}"
        self.jobs: List[JobScheduleBuilder] = []
        self.enqueue_kwargs: List[Dict[str, Any]] = []

    def add_job(self, job_func: Callable[..., Any], **kwargs) -> JobScheduleBuilder:
        """Add a job to the batch"""
        builder = JobScheduleBuilder(job_func)
        self.jobs.append(builder)
        self.enqueue_kwargs.append(kwargs)
        return builder

    def add(self, job_func: Callable[..., Any], **kwargs) -> JobScheduleBuilder:
        """Add a job to the batch (fluent interface)"""
        return self.add_job(job_func, **kwargs)

    async def enqueue_all(
        self, batch_priority: Optional[int] = None
    ) -> List[Union[str, Dict[str, Any]]]:
        """Enqueue all jobs in the batch using a single pooled connection.

        All inserts run in one transaction so the batch is atomic and we
        hold exactly one connection for the full batch instead of
        acquiring/releasing per job.
        """
        from soniq.db.context import get_context_pool

        for i, builder in enumerate(self.jobs):
            builder.with_tags(f"batch:{self.batch_name}", f"batch_item:{i}")
            if batch_priority is not None:
                builder.with_priority(batch_priority)

        pool = await get_context_pool()
        job_ids: List[Union[str, Dict[str, Any]]] = []
        async with pool.acquire() as conn:
            async with conn.transaction():
                for builder, kwargs in zip(self.jobs, self.enqueue_kwargs):
                    job_id = await builder.enqueue(connection=conn, **kwargs)
                    job_ids.append(job_id)

        return job_ids

    def get_batch_info(self) -> Dict[str, Any]:
        """Get information about the batch"""
        return {
            "batch_name": self.batch_name,
            "job_count": len(self.jobs),
            "jobs": [
                {
                    "function": f"{job.job_func.__module__}.{job.job_func.__name__}",
                    "scheduled_at": (
                        job._scheduled_at.isoformat() if job._scheduled_at else None
                    ),
                    "priority": job._priority,
                    "queue": job._queue,
                }
                for job in self.jobs
            ],
        }


def schedule_job(job_func: Callable[..., Any]) -> JobScheduleBuilder:
    """
    Create a fluent job scheduler for the given function

    Examples:
        await schedule_job(my_task).in_minutes(30).with_priority(5).enqueue(arg="value")
        await schedule_job(report).at_time("2024-12-25T09:00:00").enqueue()
        await schedule_job(cleanup).in_hours(2).if_condition(lambda: True).enqueue()
    """
    require_feature("scheduling_enabled", "Advanced scheduling")
    return JobScheduleBuilder(job_func)


async def schedule(
    job_func: Callable[..., Any], when: Union[datetime, int, float, timedelta], **kwargs
) -> Union[str, Dict[str, Any]]:
    """
    Unified scheduling function supporting multiple time formats

    Args:
        job_func: Function to schedule
        when: When to execute the job - supports:
            - datetime: specific time
            - int/float: seconds from now
            - timedelta: time offset from now
        **kwargs: Arguments to pass to the job
    """
    require_feature("scheduling_enabled", "Advanced scheduling")
    if isinstance(when, datetime):
        return await schedule_job(job_func).at_time(when.isoformat()).enqueue(**kwargs)
    elif isinstance(when, (int, float)):
        return await schedule_job(job_func).in_seconds(int(when)).enqueue(**kwargs)
    elif isinstance(when, timedelta):
        return (
            await schedule_job(job_func)
            .in_seconds(int(when.total_seconds()))
            .enqueue(**kwargs)
        )
    else:
        raise TypeError(
            f"Unsupported schedule type: {type(when)}. Use datetime, int/float seconds, or timedelta"
        )


def create_batch() -> BatchScheduler:
    """Create a batch scheduler for multiple jobs"""
    require_feature("scheduling_enabled", "Advanced scheduling")
    return BatchScheduler()


# Priority-based scheduling convenience functions
async def schedule_high_priority(
    job_func: Callable[..., Any], **kwargs
) -> Union[str, Dict[str, Any]]:
    """Schedule a high priority job (immediate execution)"""
    return (
        await schedule_job(job_func)
        .with_priority(1)
        .in_queue("urgent")
        .enqueue(**kwargs)
    )


async def schedule_background(
    job_func: Callable[..., Any], **kwargs
) -> Union[str, Dict[str, Any]]:
    """Schedule a low priority background job (immediate execution)"""
    return (
        await schedule_job(job_func)
        .with_priority(100)
        .in_queue("background")
        .enqueue(**kwargs)
    )


async def schedule_urgent(
    job_func: Callable[..., Any], **kwargs
) -> Union[str, Dict[str, Any]]:
    """Schedule an urgent priority job (immediate execution)"""
    return (
        await schedule_job(job_func)
        .with_priority(1)
        .in_queue("urgent")
        .enqueue(**kwargs)
    )


# NOTE: For recurring jobs (daily, weekly, etc.), use the recurring module:
# - await daily().at("09:00").schedule(job_func)
# - await weekly().on("monday").at("09:00").schedule(job_func)
# - await every(5).minutes().schedule(job_func)


def get_job_metadata(job_id: str) -> Optional[Dict[str, Any]]:
    """Get additional metadata for a scheduled job"""
    return _scheduler_metadata.get(job_id)


def clear_job_metadata(job_id: str) -> bool:
    """Clear metadata for a job"""
    if job_id in _scheduler_metadata:
        del _scheduler_metadata[job_id]
        return True
    return False


# Decorator for easy scheduling setup
def scheduled(schedule_type: str, **schedule_kwargs):
    """
    Decorator to pre-configure job scheduling

    Examples:
        @scheduled("daily", time="09:00", priority=10)
        async def daily_report():
            pass

        @scheduled("delay", minutes=30, queue="background")
        async def cleanup_task():
            pass
    """

    def decorator(func):
        func._schedule_config = {"type": schedule_type, "kwargs": schedule_kwargs}
        return func

    return decorator
