"""
Advanced scheduling with fluent interface for ElephantQ.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Union

from elephantq import enqueue

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
        self._dependencies: List[str] = []
        self._timeout: Optional[int] = None
        self._condition: Optional[Callable[[], bool]] = None
        self._dry_run: bool = False

    def in_seconds(self, seconds: int) -> "JobScheduleBuilder":
        """Schedule job to run in X seconds"""
        self._scheduled_at = datetime.now() + timedelta(seconds=seconds)
        return self

    def in_minutes(self, minutes: int) -> "JobScheduleBuilder":
        """Schedule job to run in X minutes"""
        self._scheduled_at = datetime.now() + timedelta(minutes=minutes)
        return self

    def in_hours(self, hours: int) -> "JobScheduleBuilder":
        """Schedule job to run in X hours"""
        self._scheduled_at = datetime.now() + timedelta(hours=hours)
        return self

    def in_days(self, days: int) -> "JobScheduleBuilder":
        """Schedule job to run in X days"""
        self._scheduled_at = datetime.now() + timedelta(days=days)
        return self

    def at_time(self, time_str: str) -> "JobScheduleBuilder":
        """
        Schedule job at specific time

        Args:
            time_str: ISO format datetime string or HH:MM format for today
        """
        try:
            # Try parsing as ISO datetime first
            self._scheduled_at = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except ValueError:
            try:
                # Try parsing as HH:MM for today
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

    def depends_on(self, *job_ids: str) -> "JobScheduleBuilder":
        """Set job dependencies (jobs that must complete first)"""
        self._dependencies.extend(job_ids)
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

    async def enqueue(self, **kwargs) -> Union[str, Dict[str, Any]]:
        """
        Enqueue the job with configured options

        Returns:
            Job ID if scheduled, or configuration dict if dry run
        """
        if self._dry_run:
            return self._get_configuration(**kwargs)

        # Check condition if specified
        if self._condition and not self._condition():
            raise RuntimeError("Job condition not satisfied")

        # Check dependencies if any are specified
        if self._dependencies:

            # Validate that all dependency job IDs exist and are valid
            valid_deps = []
            for dep_id in self._dependencies:
                try:
                    import uuid

                    uuid.UUID(dep_id)  # Validate UUID format
                    valid_deps.append(dep_id)
                except ValueError:
                    raise ValueError(f"Invalid dependency job ID format: {dep_id}")

            self._dependencies = valid_deps

        # Use custom enqueue parameters if specified, otherwise use job defaults
        enqueue_kwargs = {}
        if self._scheduled_at:
            enqueue_kwargs["scheduled_at"] = self._scheduled_at
        if self._priority is not None:
            enqueue_kwargs["priority"] = self._priority
        if self._queue:
            enqueue_kwargs["queue"] = self._queue

        # Add job arguments
        enqueue_kwargs.update(kwargs)

        job_id = await enqueue(self.job_func, **enqueue_kwargs)

        # Store dependencies in database if any
        if self._dependencies:
            from .dependencies import store_job_dependencies

            await store_job_dependencies(job_id, self._dependencies, self._timeout)

        # Store timeout configuration if specified
        if self._timeout:
            from elephantq.db.context import get_context_pool

            from .timeout_processor import store_job_timeout

            pool = await get_context_pool()
            async with pool.acquire() as conn:
                await store_job_timeout(job_id, self._timeout, conn)

        # Store additional metadata (tags, timeout, etc.)
        if any([self._tags, self._timeout, self._retries is not None]):
            _scheduler_metadata[job_id] = {
                "tags": self._tags,
                "timeout": self._timeout,
                "retries": self._retries,
                "dependencies": self._dependencies,
            }

        return job_id

    def _get_configuration(self, **kwargs) -> Dict[str, Any]:
        """Get job configuration for dry run"""
        return {
            "job_function": f"{self.job_func.__module__}.{self.job_func.__name__}",
            "scheduled_at": (
                self._scheduled_at.isoformat() if self._scheduled_at else None
            ),
            "priority": self._priority,
            "queue": self._queue,
            "retries": self._retries,
            "tags": self._tags,
            "dependencies": self._dependencies,
            "timeout": self._timeout,
            "condition": "Custom condition" if self._condition else None,
            "arguments": kwargs,
        }


# Global metadata storage for scheduler features
_scheduler_metadata: Dict[str, Dict[str, Any]] = {}


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

    def add(self, job_func: Callable[..., Any], **kwargs) -> "BatchScheduler":
        """Add a job to the batch (fluent interface)"""
        self.add_job(job_func, **kwargs)
        return self

    async def enqueue_all(self, batch_priority: Optional[int] = None) -> List[str]:
        """Enqueue all jobs in the batch"""
        job_ids = []

        for i, (builder, kwargs) in enumerate(zip(self.jobs, self.enqueue_kwargs)):
            # Add batch metadata
            builder.with_tags(f"batch:{self.batch_name}", f"batch_item:{i}")

            if batch_priority is not None:
                builder.with_priority(batch_priority)

            job_id = await builder.enqueue(**kwargs)
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
) -> str:
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
async def schedule_high_priority(job_func: Callable[..., Any], **kwargs) -> str:
    """Schedule a high priority job (immediate execution)"""
    return (
        await schedule_job(job_func)
        .with_priority(1)
        .in_queue("urgent")
        .enqueue(**kwargs)
    )


async def schedule_background(job_func: Callable[..., Any], **kwargs) -> str:
    """Schedule a low priority background job (immediate execution)"""
    return (
        await schedule_job(job_func)
        .with_priority(100)
        .in_queue("background")
        .enqueue(**kwargs)
    )


async def schedule_urgent(job_func: Callable[..., Any], **kwargs) -> str:
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


# Example usage and testing
async def example_scheduled_job(message: str = "Hello"):
    """Example job for testing scheduling"""
    print(f"Scheduled job executed: {message}")
    return message


async def demo_advanced_scheduling():
    """Demonstrate advanced scheduling functionality"""
    print("ElephantQ - Advanced Scheduling Demo")
    print("=====================================")

    # Basic fluent interface
    print("\n1. Fluent interface examples:")

    # Schedule in 30 minutes with high priority
    job_id1 = (
        await schedule_job(example_scheduled_job)
        .in_minutes(30)
        .with_priority(5)
        .enqueue(message="High priority job")
    )
    print(f"Scheduled high priority job: {job_id1}")

    # Schedule at specific time tomorrow
    tomorrow_9am = (datetime.now() + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    job_id2 = (
        await schedule_job(example_scheduled_job)
        .at_time(tomorrow_9am.isoformat())
        .enqueue(message="Tomorrow at 9 AM")
    )
    print(f"Scheduled for tomorrow 9 AM: {job_id2}")

    # Conditional scheduling
    job_id3 = (
        await schedule_job(example_scheduled_job)
        .in_hours(2)
        .if_condition(lambda: True)  # Always true for demo
        .with_tags("conditional", "demo")
        .enqueue(message="Conditional job")
    )
    print(f"Scheduled conditional job: {job_id3}")

    # Batch scheduling
    print("\n2. Batch scheduling:")
    batch = create_batch()

    batch.add_job(example_scheduled_job).in_minutes(5).with_priority(10).with_tags(
        "batch1"
    )
    batch.add_job(example_scheduled_job).in_minutes(10).with_priority(20).with_tags(
        "batch2"
    )
    batch.add_job(example_scheduled_job).in_minutes(15).with_priority(30).with_tags(
        "batch3"
    )

    batch_job_ids = await batch.enqueue_all()
    print(f"Batch scheduled: {batch_job_ids}")

    # Dry run example
    print("\n3. Dry run preview:")
    config = (
        await schedule_job(example_scheduled_job)
        .in_days(1)
        .with_priority(1)
        .dry_run()
        .enqueue(message="Dry run job")
    )
    print(f"Dry run configuration: {config}")

    # Convenience functions
    print("\n4. Convenience functions:")
    urgent_job = await schedule_high_priority(
        example_scheduled_job, message="Urgent task"
    )
    background_job = await schedule_background(
        example_scheduled_job, message="Background task"
    )

    print(f"Urgent job: {urgent_job}")
    print(f"Background job: {background_job}")

    print("\nAdvanced scheduling demo completed!")


if __name__ == "__main__":
    import asyncio

    asyncio.run(demo_advanced_scheduling())
