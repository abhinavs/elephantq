"""
Enhanced Recurring Jobs System for ElephantQ.
Streamlined API with fluent interfaces and better integration.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from croniter import croniter

from elephantq import enqueue
from elephantq.core.registry import get_job as get_registered_job
from elephantq.db.context import get_context_pool

from .flags import require_feature


class Priority(Enum):
    """Job priority levels"""

    URGENT = 1
    HIGH = 10
    NORMAL = 50
    LOW = 75
    BACKGROUND = 100


class FluentRecurringScheduler:
    """Enhanced fluent interface for recurring jobs"""

    def __init__(self, schedule_type: str, schedule_value: Union[str, int]):
        self.schedule_type = schedule_type  # 'cron' or 'interval'
        self.schedule_value = schedule_value
        self._priority: int = Priority.NORMAL.value
        self._queue: str = "default"
        self._max_attempts: int = 3
        self._job_kwargs: Dict[str, Any] = {}

    def priority(self, level: Union[Priority, int, str]) -> "FluentRecurringScheduler":
        """Set job priority"""
        if isinstance(level, Priority):
            self._priority = level.value
        elif isinstance(level, int):
            self._priority = level
        elif isinstance(level, str):
            priority_map = {
                "urgent": Priority.URGENT.value,
                "high": Priority.HIGH.value,
                "normal": Priority.NORMAL.value,
                "low": Priority.LOW.value,
                "background": Priority.BACKGROUND.value,
            }
            self._priority = priority_map.get(level.lower(), Priority.NORMAL.value)
        return self

    def queue(self, queue_name: str) -> "FluentRecurringScheduler":
        """Set target queue"""
        self._queue = queue_name
        return self

    def max_attempts(self, attempts: int) -> "FluentRecurringScheduler":
        """Set maximum retry attempts"""
        self._max_attempts = attempts
        return self

    def high_priority(self) -> "FluentRecurringScheduler":
        """Set high priority (convenience method)"""
        return self.priority(Priority.HIGH).queue("urgent")

    def background(self) -> "FluentRecurringScheduler":
        """Set background priority (convenience method)"""
        return self.priority(Priority.BACKGROUND).queue("background")

    def urgent(self) -> "FluentRecurringScheduler":
        """Set urgent priority (convenience method)"""
        return self.priority(Priority.URGENT).queue("urgent")

    async def schedule(self, job_func: Callable[..., Any], **job_kwargs) -> str:
        """Schedule the recurring job"""
        # Merge job kwargs
        final_kwargs = {**self._job_kwargs, **job_kwargs}

        # Add to recurring manager with all configuration
        job_id = await _enhanced_manager.add_recurring_job(
            job_func=job_func,
            schedule_type=self.schedule_type,
            schedule_value=self.schedule_value,
            priority=self._priority,
            queue=self._queue,
            max_attempts=self._max_attempts,
            job_kwargs=final_kwargs,
        )

        return job_id


class TimeIntervalBuilder:
    """Builder for time-based scheduling"""

    def __init__(self, amount: int):
        self.amount = amount

    def seconds(self) -> FluentRecurringScheduler:
        """Every N seconds"""
        return FluentRecurringScheduler("interval", self.amount)

    def minutes(self) -> FluentRecurringScheduler:
        """Every N minutes"""
        return FluentRecurringScheduler("interval", self.amount * 60)

    def hours(self) -> FluentRecurringScheduler:
        """Every N hours"""
        return FluentRecurringScheduler("interval", self.amount * 3600)

    def days(self) -> FluentRecurringScheduler:
        """Every N days"""
        return FluentRecurringScheduler("interval", self.amount * 86400)


class DailyScheduler(FluentRecurringScheduler):
    """Enhanced daily scheduler with time specification"""

    def __init__(self):
        super().__init__("cron", "0 0 * * *")  # Midnight by default

    def at(self, time: str) -> "DailyScheduler":
        """Set specific time (HH:MM format)"""
        try:
            hour, minute = map(int, time.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Invalid time format")
            self.schedule_value = f"{minute} {hour} * * *"
        except (ValueError, AttributeError):
            raise ValueError("Time must be in HH:MM format (24-hour)")
        return self


class WeeklyScheduler(FluentRecurringScheduler):
    """Enhanced weekly scheduler"""

    def __init__(self):
        super().__init__("cron", "0 0 * * 0")  # Sunday midnight by default
        self._day = 0  # Sunday
        self._hour = 0
        self._minute = 0

    def on(self, day: Union[str, int]) -> "WeeklyScheduler":
        """Set day of week"""
        if isinstance(day, str):
            day_map = {
                "sunday": 0,
                "sun": 0,
                "monday": 1,
                "mon": 1,
                "tuesday": 2,
                "tue": 2,
                "wednesday": 3,
                "wed": 3,
                "thursday": 4,
                "thu": 4,
                "friday": 5,
                "fri": 5,
                "saturday": 6,
                "sat": 6,
            }
            self._day = day_map.get(day.lower(), 0)
        else:
            self._day = day % 7

        self._update_cron()
        return self

    def at(self, time: str) -> "WeeklyScheduler":
        """Set specific time"""
        try:
            self._hour, self._minute = map(int, time.split(":"))
            if not (0 <= self._hour <= 23 and 0 <= self._minute <= 59):
                raise ValueError("Invalid time format")
        except (ValueError, AttributeError):
            raise ValueError("Time must be in HH:MM format")

        self._update_cron()
        return self

    def _update_cron(self):
        """Update cron expression"""
        self.schedule_value = f"{self._minute} {self._hour} * * {self._day}"


class MonthlyScheduler(FluentRecurringScheduler):
    """Enhanced monthly scheduler"""

    def __init__(self):
        super().__init__("cron", "0 0 1 * *")  # 1st of month at midnight
        self._day = 1
        self._hour = 0
        self._minute = 0

    def on_day(self, day: int) -> "MonthlyScheduler":
        """Set day of month (1-31)"""
        if not 1 <= day <= 31:
            raise ValueError("Day must be between 1 and 31")
        self._day = day
        self._update_cron()
        return self

    def at(self, time: str) -> "MonthlyScheduler":
        """Set specific time"""
        try:
            self._hour, self._minute = map(int, time.split(":"))
            if not (0 <= self._hour <= 23 and 0 <= self._minute <= 59):
                raise ValueError("Invalid time format")
        except (ValueError, AttributeError):
            raise ValueError("Time must be in HH:MM format")

        self._update_cron()
        return self

    def _update_cron(self):
        """Update cron expression"""
        self.schedule_value = f"{self._minute} {self._hour} {self._day} * *"


class EnhancedRecurringManager:
    """Enhanced recurring job manager with better integration"""

    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    async def load_jobs(self) -> None:
        """Load recurring jobs from the database."""
        if self._loaded:
            return

        pool = await get_context_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, job_name, schedule_type, schedule_value, priority, queue,
                       max_attempts, job_kwargs, status, created_at, last_run, next_run,
                       run_count, last_job_id
                FROM elephantq_recurring_jobs
                """
            )

        for row in rows:
            schedule_value = row["schedule_value"]
            if row["schedule_type"] == "interval":
                try:
                    schedule_value = int(schedule_value)
                except (TypeError, ValueError):
                    continue

            job_meta = get_registered_job(row["job_name"])
            job_func = job_meta["func"] if job_meta else None

            job_record = {
                "id": str(row["id"]),
                "job_name": row["job_name"],
                "job_func": job_func,
                "schedule_type": row["schedule_type"],
                "schedule_value": schedule_value,
                "priority": row["priority"],
                "queue": row["queue"],
                "max_attempts": row["max_attempts"],
                "job_kwargs": row["job_kwargs"] or {},
                "created_at": row["created_at"],
                "last_run": row["last_run"],
                "next_run": row["next_run"],
                "run_count": row["run_count"] or 0,
                "status": row["status"],
                "last_job_id": row["last_job_id"],
            }

            if job_record["next_run"] is None:
                job_record["next_run"] = self._calculate_next_run(
                    job_record["schedule_type"],
                    job_record["schedule_value"],
                    datetime.now(),
                )
                await self._persist_next_run(job_record["id"], job_record["next_run"])

            self.jobs[job_record["id"]] = job_record

        self._loaded = True

    async def add_recurring_job(
        self,
        job_func: Callable[..., Any],
        schedule_type: str,
        schedule_value: Union[str, int],
        priority: int = Priority.NORMAL.value,
        queue: str = "default",
        max_attempts: int = 3,
        job_kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a recurring job with full configuration"""

        job_id = str(uuid.uuid4())
        job_kwargs = job_kwargs or {}
        job_name = f"{job_func.__module__}.{job_func.__name__}"

        try:
            json.dumps(job_kwargs)
        except TypeError as exc:
            raise ValueError("job_kwargs must be JSON-serializable") from exc

        # Create job record
        job_record = {
            "id": job_id,
            "job_name": job_name,
            "job_func": job_func,
            "schedule_type": schedule_type,
            "schedule_value": schedule_value,
            "priority": priority,
            "queue": queue,
            "max_attempts": max_attempts,
            "job_kwargs": job_kwargs,
            "created_at": datetime.now(),
            "last_run": None,
            "next_run": None,
            "run_count": 0,
            "status": "active",
        }

        # Calculate next run time
        if schedule_type == "interval":
            job_record["next_run"] = datetime.now() + timedelta(seconds=schedule_value)
        elif schedule_type == "cron":
            cron = croniter(schedule_value, datetime.now())
            job_record["next_run"] = cron.get_next(datetime)

        await self._persist_job(job_record)

        self.jobs[job_id] = job_record

        # Auto-start scheduler if it's not running
        await _ensure_scheduler_running()

        return job_id

    def remove_job(self, job_id: str) -> bool:
        """Remove a recurring job"""
        if job_id in self.jobs:
            del self.jobs[job_id]
            self._schedule_update(self._delete_job(job_id))
            return True
        return False

    def pause_job(self, job_id: str) -> bool:
        """Pause a recurring job"""
        if job_id in self.jobs:
            self.jobs[job_id]["status"] = "paused"
            self._schedule_update(self._set_status(job_id, "paused"))
            return True
        return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused recurring job"""
        if job_id in self.jobs:
            self.jobs[job_id]["status"] = "active"
            self._schedule_update(self._set_status(job_id, "active"))
            return True
        return False

    def list_jobs(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List recurring jobs, optionally filtered by status"""
        self._ensure_loaded()
        jobs = list(self.jobs.values())
        if status:
            jobs = [job for job in jobs if job["status"] == status]
        return jobs

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get details of a specific recurring job"""
        self._ensure_loaded()
        return self.jobs.get(job_id)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.load_jobs())
            return
        loop.create_task(self.load_jobs())

    def _schedule_update(self, coro: "asyncio.Future") -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return
        loop.create_task(coro)

    async def _persist_job(self, job_record: Dict[str, Any]) -> None:
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO elephantq_recurring_jobs (
                    id, job_name, schedule_type, schedule_value, priority, queue,
                    max_attempts, job_kwargs, status, created_at, last_run, next_run,
                    run_count, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), $10, $11, $12, NOW())
                """,
                uuid.UUID(job_record["id"]),
                job_record["job_name"],
                job_record["schedule_type"],
                str(job_record["schedule_value"]),
                job_record["priority"],
                job_record["queue"],
                job_record["max_attempts"],
                job_record["job_kwargs"],
                job_record["status"],
                job_record["last_run"],
                job_record["next_run"],
                job_record["run_count"],
            )

    async def _persist_next_run(self, job_id: str, next_run: datetime) -> None:
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE elephantq_recurring_jobs
                SET next_run = $1, updated_at = NOW()
                WHERE id = $2
                """,
                next_run,
                uuid.UUID(job_id),
            )

    async def _delete_job(self, job_id: str) -> None:
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM elephantq_recurring_jobs WHERE id = $1",
                uuid.UUID(job_id),
            )

    async def _set_status(self, job_id: str, status: str) -> None:
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE elephantq_recurring_jobs
                SET status = $1, updated_at = NOW()
                WHERE id = $2
                """,
                status,
                uuid.UUID(job_id),
            )

    async def _record_run(
        self,
        job_id: str,
        last_run: datetime,
        next_run: datetime,
        run_count: int,
        last_job_id: Optional[str],
    ) -> None:
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE elephantq_recurring_jobs
                SET last_run = $1,
                    next_run = $2,
                    run_count = $3,
                    last_job_id = $4,
                    updated_at = NOW()
                WHERE id = $5
                """,
                last_run,
                next_run,
                run_count,
                uuid.UUID(last_job_id) if last_job_id else None,
                uuid.UUID(job_id),
            )

    def _calculate_next_run(
        self,
        schedule_type: str,
        schedule_value: Union[str, int],
        current_time: datetime,
    ) -> Optional[datetime]:
        if schedule_type == "interval":
            return current_time + timedelta(seconds=int(schedule_value))
        if schedule_type == "cron":
            cron = croniter(schedule_value, current_time)
            return cron.get_next(datetime)
        return None


class EnhancedRecurringScheduler:
    """Enhanced background scheduler with better performance"""

    def __init__(self, check_interval: int = 30):
        self.check_interval = check_interval
        self.running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the scheduler"""
        if self.running:
            return

        self.running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        print(
            f"Enhanced recurring scheduler started (check interval: {self.check_interval}s)"
        )

    async def stop(self):
        """Stop the scheduler"""
        if not self.running:
            return

        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        print("Enhanced recurring scheduler stopped")

    async def _scheduler_loop(self):
        """Main scheduler loop with improved error handling"""
        while self.running:
            try:
                await self._process_due_jobs()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Scheduler error: {e}")
                await asyncio.sleep(min(self.check_interval, 60))  # Backoff

    async def _process_due_jobs(self):
        """Process jobs that are due to run"""
        current_time = datetime.now()

        for job_id, job in _enhanced_manager.jobs.items():
            if job["status"] != "active":
                continue
            if job.get("job_func") is None:
                job_meta = get_registered_job(job.get("job_name", ""))
                if job_meta:
                    job["job_func"] = job_meta["func"]
                else:
                    continue

            try:
                if self._is_job_due(job, current_time):
                    await self._execute_job(job_id, job, current_time)
            except Exception as e:
                print(f"Error executing recurring job {job_id}: {e}")

    def _is_job_due(self, job: Dict[str, Any], current_time: datetime) -> bool:
        """Check if a job is due to run"""
        next_run = job.get("next_run")
        if not next_run:
            return False

        return current_time >= next_run

    async def _execute_job(
        self, job_id: str, job: Dict[str, Any], current_time: datetime
    ):
        """Execute a due job"""
        try:
            # Enqueue the job with all configured parameters
            actual_job_id = await enqueue(
                job["job_func"],
                priority=job["priority"],
                queue=job["queue"],
                max_attempts=job["max_attempts"],
                **job["job_kwargs"],
            )

            # Update job statistics
            _enhanced_manager.jobs[job_id].update(
                {
                    "last_run": current_time,
                    "run_count": job["run_count"] + 1,
                    "last_job_id": actual_job_id,
                }
            )

            # Calculate next run time
            next_run = _enhanced_manager._calculate_next_run(
                job["schedule_type"], job["schedule_value"], current_time
            )
            if next_run is None:
                return

            _enhanced_manager.jobs[job_id]["next_run"] = next_run
            await _enhanced_manager._record_run(
                job_id=job_id,
                last_run=current_time,
                next_run=next_run,
                run_count=_enhanced_manager.jobs[job_id]["run_count"],
                last_job_id=actual_job_id,
            )

            print(
                f"Recurring job {job_id} enqueued as {actual_job_id}, next run: {next_run}"
            )

        except Exception as e:
            print(f"Failed to execute recurring job {job_id}: {e}")
            # Don't update next_run on error - will retry


# Global instances
_enhanced_manager = EnhancedRecurringManager()
_enhanced_scheduler = EnhancedRecurringScheduler()


async def _ensure_scheduler_running():
    """Ensure the scheduler is running"""
    await _enhanced_manager.load_jobs()
    if not _enhanced_scheduler.running:
        await _enhanced_scheduler.start()


# ============================================================================
# IMPROVED PUBLIC API - Clean and Fluent
# ============================================================================


def every(amount: int) -> TimeIntervalBuilder:
    """
    Schedule jobs at regular intervals

    Examples:
        await every(5).minutes().schedule(cleanup_task)
        await every(2).hours().background().schedule(backup_task)
        await every(1).days().at("09:00").schedule(daily_report)
    """
    require_feature("scheduling_enabled", "Recurring scheduler")
    return TimeIntervalBuilder(amount)


def hourly() -> FluentRecurringScheduler:
    """Schedule job every hour"""
    return FluentRecurringScheduler("interval", 3600)


def daily() -> DailyScheduler:
    """
    Schedule job daily

    Examples:
        await daily().schedule(midnight_task)                    # Midnight
        await daily().at("09:00").schedule(morning_report)       # 9 AM daily
        await daily().at("15:30").high_priority().schedule(task) # 3:30 PM, high priority
    """
    require_feature("scheduling_enabled", "Recurring scheduler")
    return DailyScheduler()


def weekly() -> WeeklyScheduler:
    """
    Schedule job weekly

    Examples:
        await weekly().schedule(sunday_task)                           # Sunday midnight
        await weekly().on("monday").at("09:00").schedule(weekly_report) # Monday 9 AM
        await weekly().on(1).at("18:00").background().schedule(task)   # Monday 6 PM, background
    """
    require_feature("scheduling_enabled", "Recurring scheduler")
    return WeeklyScheduler()


def monthly() -> MonthlyScheduler:
    """
    Schedule job monthly

    Examples:
        await monthly().schedule(month_end_task)                        # 1st midnight
        await monthly().on_day(15).at("12:00").schedule(mid_month)      # 15th at noon
        await monthly().on_day(1).at("09:00").urgent().schedule(task)  # 1st at 9 AM, urgent
    """
    require_feature("scheduling_enabled", "Recurring scheduler")
    return MonthlyScheduler()


def cron(expression: str) -> FluentRecurringScheduler:
    """
    Schedule job using cron expression

    Examples:
        await cron("*/15 * * * *").schedule(every_15_min)         # Every 15 minutes
        await cron("0 9 * * 1-5").high_priority().schedule(task) # Weekdays 9 AM, high priority
    """
    return FluentRecurringScheduler("cron", expression)


# Priority convenience functions
async def high_priority() -> FluentRecurringScheduler:
    """Create high priority job (convenience method)"""
    scheduler = FluentRecurringScheduler("interval", 0)  # Will be overridden
    return scheduler.high_priority()


async def background() -> FluentRecurringScheduler:
    """Create background priority job (convenience method)"""
    scheduler = FluentRecurringScheduler("interval", 0)  # Will be overridden
    return scheduler.background()


async def urgent() -> FluentRecurringScheduler:
    """Create urgent priority job (convenience method)"""
    scheduler = FluentRecurringScheduler("interval", 0)  # Will be overridden
    return scheduler.urgent()


# Management functions
async def start_recurring_scheduler(check_interval: int = 30):
    """Start the global recurring job scheduler"""
    global _enhanced_scheduler
    _enhanced_scheduler.check_interval = check_interval
    await _enhanced_scheduler.start()


async def stop_recurring_scheduler():
    """Stop the global recurring job scheduler"""
    await _enhanced_scheduler.stop()


def get_recurring_manager() -> EnhancedRecurringManager:
    """Get the global recurring job manager"""
    return _enhanced_manager


def get_recurring_scheduler() -> EnhancedRecurringScheduler:
    """Get the global recurring job scheduler"""
    return _enhanced_scheduler


def list_recurring_jobs(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all recurring jobs"""
    return _enhanced_manager.list_jobs(status=status)


def get_recurring_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get details of a specific recurring job"""
    return _enhanced_manager.get_job(job_id)


async def remove_recurring_job(job_id: str) -> bool:
    """Remove a recurring job"""
    return _enhanced_manager.remove_job(job_id)


async def pause_recurring_job(job_id: str) -> bool:
    """Pause a recurring job"""
    return _enhanced_manager.pause_job(job_id)


async def resume_recurring_job(job_id: str) -> bool:
    """Resume a paused recurring job"""
    return _enhanced_manager.resume_job(job_id)


def get_scheduler_status() -> Dict[str, Any]:
    """Get detailed scheduler status"""
    return {
        "running": _enhanced_scheduler.running,
        "check_interval": _enhanced_scheduler.check_interval,
        "active_jobs": len(
            [j for j in _enhanced_manager.jobs.values() if j["status"] == "active"]
        ),
        "paused_jobs": len(
            [j for j in _enhanced_manager.jobs.values() if j["status"] == "paused"]
        ),
        "total_jobs": len(_enhanced_manager.jobs),
    }


# ============================================================================
# DECORATOR SUPPORT
# ============================================================================


def recurring(schedule_expr: str, **config):
    """
    Decorator for recurring jobs

    Examples:
        @recurring("*/15 * * * *")  # Every 15 minutes
        async def health_check():
            pass

        @recurring("1h", priority="high", queue="urgent")  # Every hour, high priority
        async def urgent_cleanup():
            pass
    """

    def decorator(func):
        # Determine schedule type and create appropriate scheduler
        if " " in schedule_expr and len(schedule_expr.split()) == 5:
            # Cron expression
            scheduler = cron(schedule_expr)
        else:
            # Try to parse as interval
            try:
                if schedule_expr.endswith(("s", "m", "h", "d")):
                    unit = schedule_expr[-1]
                    amount = int(schedule_expr[:-1])

                    unit_map = {
                        "s": "seconds",
                        "m": "minutes",
                        "h": "hours",
                        "d": "days",
                    }
                    scheduler = getattr(every(amount), unit_map[unit])()
                else:
                    raise ValueError("Invalid schedule expression")
            except (ValueError, AttributeError):
                # Fallback to cron
                scheduler = cron(schedule_expr)

        # Apply configuration
        if "priority" in config:
            scheduler = scheduler.priority(config["priority"])
        if "queue" in config:
            scheduler = scheduler.queue(config["queue"])
        if "max_attempts" in config:
            scheduler = scheduler.max_attempts(config["max_attempts"])

        # Store configuration for later scheduling
        func._recurring_config = {"scheduler": scheduler, "config": config}

        return func

    return decorator


async def schedule_decorated_jobs():
    """Schedule all functions decorated with @recurring"""
    import gc

    scheduled_count = 0
    for obj in gc.get_objects():
        if hasattr(obj, "_recurring_config"):
            config = obj._recurring_config
            job_id = await config["scheduler"].schedule(obj)
            print(f"Scheduled decorated job {obj.__name__} as {job_id}")
            scheduled_count += 1

    return scheduled_count
