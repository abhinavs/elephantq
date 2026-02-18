"""
Dead Letter Queue Management.
Management of permanently failed jobs, resurrection, bulk operations.
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from elephantq.core.registry import get_job
from elephantq.db.context import get_context_pool

logger = logging.getLogger(__name__)


class DeadLetterReason(str, Enum):
    """Reasons for jobs ending up in dead letter queue"""

    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"
    PERMANENT_FAILURE = "permanent_failure"
    JOB_NOT_FOUND = "job_not_found"
    INVALID_ARGUMENTS = "invalid_arguments"
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    MANUAL_MOVE = "manual_move"


@dataclass
class DeadLetterJob:
    """Dead letter job record"""

    id: str
    job_name: str
    args: Dict[str, Any]
    queue: str
    priority: int
    max_attempts: int
    attempts: int
    last_error: str
    dead_letter_reason: str
    original_created_at: datetime
    moved_to_dead_letter_at: datetime
    resurrection_count: int = 0
    last_resurrection_at: Optional[datetime] = None
    tags: Optional[Dict[str, str]] = None

    @classmethod
    def from_job_record(
        cls, job_record: Dict[str, Any], reason: DeadLetterReason
    ) -> "DeadLetterJob":
        """Create dead letter job from regular job record"""
        return cls(
            id=str(job_record["id"]),
            job_name=job_record["job_name"],
            args=(
                json.loads(job_record["args"])
                if isinstance(job_record["args"], str)
                else job_record["args"]
            ),
            queue=job_record["queue"],
            priority=job_record["priority"],
            max_attempts=job_record["max_attempts"],
            attempts=job_record["attempts"],
            last_error=job_record["last_error"] or "",
            dead_letter_reason=reason.value,
            original_created_at=job_record["created_at"],
            moved_to_dead_letter_at=datetime.now(timezone.utc),
        )


@dataclass
class DeadLetterStats:
    """Dead letter queue statistics"""

    total_count: int
    by_job_name: Dict[str, int]
    by_queue: Dict[str, int]
    by_reason: Dict[str, int]
    by_date: Dict[str, int]
    oldest_job_age_hours: float
    resurrection_success_rate: float


class DeadLetterFilter:
    """Filter for dead letter queue queries"""

    def __init__(self):
        self.job_names: Optional[List[str]] = None
        self.queues: Optional[List[str]] = None
        self.reasons: Optional[List[str]] = None
        self.date_from: Optional[datetime] = None
        self.date_to: Optional[datetime] = None
        self.tags: Optional[Dict[str, str]] = None
        self.has_been_resurrected: Optional[bool] = None
        self.limit: int = 1000
        self.offset: int = 0

    def to_sql_conditions(self) -> Tuple[List[str], List[Any]]:
        """Convert filter to SQL WHERE conditions and parameters"""
        conditions = []
        params = []
        param_count = 0

        if self.job_names:
            param_count += 1
            conditions.append(f"job_name = ANY(${param_count})")
            params.append(self.job_names)

        if self.queues:
            param_count += 1
            conditions.append(f"queue = ANY(${param_count})")
            params.append(self.queues)

        if self.reasons:
            param_count += 1
            conditions.append(f"dead_letter_reason = ANY(${param_count})")
            params.append(self.reasons)

        if self.date_from:
            param_count += 1
            conditions.append(f"moved_to_dead_letter_at >= ${param_count}")
            params.append(self.date_from)

        if self.date_to:
            param_count += 1
            conditions.append(f"moved_to_dead_letter_at <= ${param_count}")
            params.append(self.date_to)

        if self.has_been_resurrected is not None:
            if self.has_been_resurrected:
                conditions.append("resurrection_count > 0")
            else:
                conditions.append("resurrection_count = 0")

        if self.tags:
            for key, value in self.tags.items():
                param_count += 2
                conditions.append(f"tags ->> ${param_count - 1} = ${param_count}")
                params.extend([key, value])

        return conditions, params


class DeadLetterManager:
    """Manager for dead letter queue operations"""

    def __init__(self):
        self.table_name = "elephantq_dead_letter_jobs"

    async def setup_database(self):
        """Create dead letter table if it doesn't exist"""
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id UUID PRIMARY KEY,
                    job_name TEXT NOT NULL,
                    args JSONB NOT NULL,
                    queue TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    attempts INTEGER NOT NULL,
                    last_error TEXT,
                    dead_letter_reason TEXT NOT NULL,
                    original_created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    moved_to_dead_letter_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    resurrection_count INTEGER DEFAULT 0,
                    last_resurrection_at TIMESTAMP WITH TIME ZONE,
                    tags JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_job_name ON {self.table_name}(job_name);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_queue ON {self.table_name}(queue);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_reason ON {self.table_name}(dead_letter_reason);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_moved_at ON {self.table_name}(moved_to_dead_letter_at);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_resurrection ON {self.table_name}(resurrection_count);
            """
            )

    async def move_job_to_dead_letter(
        self,
        job_id: str,
        reason: DeadLetterReason,
        tags: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Move a job to the dead letter queue"""
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Get the job record
                job_record = await conn.fetchrow(
                    """
                    SELECT * FROM elephantq_jobs WHERE id = $1
                """,
                    uuid.UUID(job_id),
                )

                if not job_record:
                    logger.warning(f"Job {job_id} not found for dead letter move")
                    return False

                # Create dead letter record
                dead_letter_job = DeadLetterJob.from_job_record(
                    dict(job_record), reason
                )
                if tags:
                    dead_letter_job.tags = tags

                # Insert into dead letter table
                await conn.execute(
                    f"""
                    INSERT INTO {self.table_name} (
                        id, job_name, args, queue, priority, max_attempts, attempts,
                        last_error, dead_letter_reason, original_created_at,
                        moved_to_dead_letter_at, tags
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                    uuid.UUID(dead_letter_job.id),
                    dead_letter_job.job_name,
                    json.dumps(dead_letter_job.args),
                    dead_letter_job.queue,
                    dead_letter_job.priority,
                    dead_letter_job.max_attempts,
                    dead_letter_job.attempts,
                    dead_letter_job.last_error,
                    dead_letter_job.dead_letter_reason,
                    dead_letter_job.original_created_at,
                    dead_letter_job.moved_to_dead_letter_at,
                    json.dumps(dead_letter_job.tags) if dead_letter_job.tags else None,
                )

                # Update original job status
                await conn.execute(
                    """
                    UPDATE elephantq_jobs 
                    SET status = 'dead_letter', updated_at = NOW()
                    WHERE id = $1
                """,
                    uuid.UUID(job_id),
                )

                logger.info(f"Moved job {job_id} to dead letter queue: {reason.value}")
                return True

    async def resurrect_job(
        self,
        dead_letter_id: str,
        reset_attempts: bool = True,
        new_max_attempts: Optional[int] = None,
        new_priority: Optional[int] = None,
        new_queue: Optional[str] = None,
    ) -> Optional[str]:
        """Resurrect a job from the dead letter queue"""
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Get dead letter job
                dead_job = await conn.fetchrow(
                    f"""
                    SELECT * FROM {self.table_name} WHERE id = $1
                """,
                    uuid.UUID(dead_letter_id),
                )

                if not dead_job:
                    logger.warning(f"Dead letter job {dead_letter_id} not found")
                    return None

                # Check if job function is still registered
                job_meta = get_job(dead_job["job_name"])
                if not job_meta:
                    logger.error(
                        f"Cannot resurrect job {dead_letter_id}: job {dead_job['job_name']} not registered"
                    )
                    return None

                # Create new job ID
                new_job_id = str(uuid.uuid4())

                # Prepare job parameters
                attempts = 0 if reset_attempts else dead_job["attempts"]
                max_attempts = new_max_attempts or dead_job["max_attempts"]
                priority = new_priority or dead_job["priority"]
                queue = new_queue or dead_job["queue"]

                # Insert new job
                await conn.execute(
                    """
                    INSERT INTO elephantq_jobs (
                        id, job_name, args, max_attempts, priority, queue, 
                        attempts, status, scheduled_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'queued', NOW())
                """,
                    uuid.UUID(new_job_id),
                    dead_job["job_name"],
                    dead_job["args"],
                    max_attempts,
                    priority,
                    queue,
                    attempts,
                )

                # Update dead letter record
                await conn.execute(
                    f"""
                    UPDATE {self.table_name}
                    SET resurrection_count = resurrection_count + 1,
                        last_resurrection_at = NOW()
                    WHERE id = $1
                """,
                    uuid.UUID(dead_letter_id),
                )

                logger.info(f"Resurrected job {dead_letter_id} as {new_job_id}")
                return new_job_id

    async def bulk_resurrect(
        self,
        filter_criteria: DeadLetterFilter,
        reset_attempts: bool = True,
        new_max_attempts: Optional[int] = None,
    ) -> List[str]:
        """Resurrect multiple jobs matching filter criteria"""
        # Get matching dead letter jobs
        dead_jobs = await self.list_dead_letter_jobs(filter_criteria)

        resurrected_jobs = []
        for dead_job in dead_jobs:
            try:
                new_job_id = await self.resurrect_job(
                    dead_job.id,
                    reset_attempts=reset_attempts,
                    new_max_attempts=new_max_attempts,
                )
                if new_job_id:
                    resurrected_jobs.append(new_job_id)
            except Exception as e:
                logger.error(f"Failed to resurrect job {dead_job.id}: {e}")

        logger.info(f"Bulk resurrected {len(resurrected_jobs)} jobs")
        return resurrected_jobs

    async def delete_dead_letter_job(self, dead_letter_id: str) -> bool:
        """Permanently delete a dead letter job"""
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                DELETE FROM {self.table_name} WHERE id = $1
            """,
                uuid.UUID(dead_letter_id),
            )

            deleted = result.split()[-1] == "1"
            if deleted:
                logger.info(f"Permanently deleted dead letter job {dead_letter_id}")
            return deleted

    async def bulk_delete(self, filter_criteria: DeadLetterFilter) -> int:
        """Delete multiple dead letter jobs matching filter criteria"""
        conditions, params = filter_criteria.to_sql_conditions()

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        pool = await get_context_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                DELETE FROM {self.table_name} {where_clause}
            """,
                *params,
            )

            deleted_count = int(result.split()[-1])
            logger.info(f"Bulk deleted {deleted_count} dead letter jobs")
            return deleted_count

    async def list_dead_letter_jobs(
        self, filter_criteria: Optional[DeadLetterFilter] = None
    ) -> List[DeadLetterJob]:
        """List dead letter jobs with optional filtering"""
        if filter_criteria is None:
            filter_criteria = DeadLetterFilter()

        conditions, params = filter_criteria.to_sql_conditions()

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Add limit and offset
        limit_clause = f"LIMIT {filter_criteria.limit} OFFSET {filter_criteria.offset}"

        pool = await get_context_pool()
        async with pool.acquire() as conn:
            records = await conn.fetch(
                f"""
                SELECT * FROM {self.table_name}
                {where_clause}
                ORDER BY moved_to_dead_letter_at DESC
                {limit_clause}
            """,
                *params,
            )

            dead_jobs = []
            for record in records:
                dead_job = DeadLetterJob(
                    id=str(record["id"]),
                    job_name=record["job_name"],
                    args=json.loads(record["args"]),
                    queue=record["queue"],
                    priority=record["priority"],
                    max_attempts=record["max_attempts"],
                    attempts=record["attempts"],
                    last_error=record["last_error"] or "",
                    dead_letter_reason=record["dead_letter_reason"],
                    original_created_at=record["original_created_at"],
                    moved_to_dead_letter_at=record["moved_to_dead_letter_at"],
                    resurrection_count=record["resurrection_count"],
                    last_resurrection_at=record["last_resurrection_at"],
                    tags=json.loads(record["tags"]) if record["tags"] else None,
                )
                dead_jobs.append(dead_job)

            return dead_jobs

    async def get_dead_letter_job(self, dead_letter_id: str) -> Optional[DeadLetterJob]:
        """Get a specific dead letter job by ID"""
        filter_criteria = DeadLetterFilter()
        filter_criteria.limit = 1

        pool = await get_context_pool()
        async with pool.acquire() as conn:
            record = await conn.fetchrow(
                f"""
                SELECT * FROM {self.table_name} WHERE id = $1
            """,
                uuid.UUID(dead_letter_id),
            )

            if not record:
                return None

            return DeadLetterJob(
                id=str(record["id"]),
                job_name=record["job_name"],
                args=json.loads(record["args"]),
                queue=record["queue"],
                priority=record["priority"],
                max_attempts=record["max_attempts"],
                attempts=record["attempts"],
                last_error=record["last_error"] or "",
                dead_letter_reason=record["dead_letter_reason"],
                original_created_at=record["original_created_at"],
                moved_to_dead_letter_at=record["moved_to_dead_letter_at"],
                resurrection_count=record["resurrection_count"],
                last_resurrection_at=record["last_resurrection_at"],
                tags=json.loads(record["tags"]) if record["tags"] else None,
            )

    async def get_dead_letter_stats(
        self, hours: Optional[int] = None
    ) -> DeadLetterStats:
        """Get dead letter queue statistics"""
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            # Base query conditions
            time_condition = ""
            params = []
            if hours:
                time_condition = (
                    "WHERE moved_to_dead_letter_at >= NOW() - INTERVAL '%s hours'"
                )
                params.append(hours)

            # Total count
            total_count = await conn.fetchval(
                f"""
                SELECT COUNT(*) FROM {self.table_name} {time_condition}
            """,
                *params,
            )

            # By job name
            by_job_name = await conn.fetch(
                f"""
                SELECT job_name, COUNT(*) as count
                FROM {self.table_name} {time_condition}
                GROUP BY job_name
                ORDER BY count DESC
            """,
                *params,
            )

            # By queue
            by_queue = await conn.fetch(
                f"""
                SELECT queue, COUNT(*) as count
                FROM {self.table_name} {time_condition}
                GROUP BY queue
                ORDER BY count DESC
            """,
                *params,
            )

            # By reason
            by_reason = await conn.fetch(
                f"""
                SELECT dead_letter_reason, COUNT(*) as count
                FROM {self.table_name} {time_condition}
                GROUP BY dead_letter_reason
                ORDER BY count DESC
            """,
                *params,
            )

            # By date (last 7 days)
            by_date = await conn.fetch(
                f"""
                SELECT 
                    DATE(moved_to_dead_letter_at) as date,
                    COUNT(*) as count
                FROM {self.table_name}
                WHERE moved_to_dead_letter_at >= NOW() - INTERVAL '7 days'
                GROUP BY date
                ORDER BY date DESC
            """
            )

            # Oldest job age
            oldest_job = await conn.fetchval(
                f"""
                SELECT MIN(moved_to_dead_letter_at) FROM {self.table_name} {time_condition}
            """,
                *params,
            )

            oldest_age_hours = 0.0
            if oldest_job:
                now = datetime.now(timezone.utc)
                if oldest_job.tzinfo is None:
                    oldest_job = oldest_job.replace(tzinfo=timezone.utc)
                else:
                    oldest_job = oldest_job.astimezone(timezone.utc)
                oldest_age_hours = (now - oldest_job).total_seconds() / 3600

            # Resurrection success rate
            resurrection_stats = await conn.fetchrow(
                f"""
                SELECT 
                    COUNT(*) as total_resurrections,
                    SUM(CASE WHEN resurrection_count > 0 THEN 1 ELSE 0 END) as successful_resurrections
                FROM {self.table_name} {time_condition}
            """,
                *params,
            )

            resurrection_success_rate = 0.0
            if resurrection_stats["total_resurrections"] > 0:
                resurrection_success_rate = (
                    resurrection_stats["successful_resurrections"]
                    / resurrection_stats["total_resurrections"]
                    * 100
                )

            return DeadLetterStats(
                total_count=total_count,
                by_job_name={row["job_name"]: row["count"] for row in by_job_name},
                by_queue={row["queue"]: row["count"] for row in by_queue},
                by_reason={
                    row["dead_letter_reason"]: row["count"] for row in by_reason
                },
                by_date={str(row["date"]): row["count"] for row in by_date},
                oldest_job_age_hours=oldest_age_hours,
                resurrection_success_rate=resurrection_success_rate,
            )

    async def cleanup_old_dead_letter_jobs(self, days: int = 30) -> int:
        """Clean up dead letter jobs older than specified days"""
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                DELETE FROM {self.table_name}
                WHERE moved_to_dead_letter_at < NOW() - INTERVAL '{days} days'
            """
            )

            deleted_count = int(result.split()[-1])
            logger.info(
                f"Cleaned up {deleted_count} dead letter jobs older than {days} days"
            )
            return deleted_count

    async def add_tags_to_job(self, dead_letter_id: str, tags: Dict[str, str]) -> bool:
        """Add tags to a dead letter job"""
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            # Get current tags
            current_tags = await conn.fetchval(
                f"""
                SELECT tags FROM {self.table_name} WHERE id = $1
            """,
                uuid.UUID(dead_letter_id),
            )

            if current_tags:
                current_tags = json.loads(current_tags)
                current_tags.update(tags)
            else:
                current_tags = tags

            # Update tags
            result = await conn.execute(
                f"""
                UPDATE {self.table_name}
                SET tags = $1
                WHERE id = $2
            """,
                json.dumps(current_tags),
                uuid.UUID(dead_letter_id),
            )

            return result.split()[-1] == "1"

    async def export_dead_letter_jobs(
        self, filter_criteria: Optional[DeadLetterFilter] = None, format: str = "json"
    ) -> str:
        """Export dead letter jobs to file"""
        jobs = await self.list_dead_letter_jobs(filter_criteria)

        if format.lower() == "json":
            import json

            data = [asdict(job) for job in jobs]
            filename = (
                f"dead_letter_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )

            with open(filename, "w") as f:
                json.dump(data, f, indent=2, default=str)

            logger.info(f"Exported {len(jobs)} dead letter jobs to {filename}")
            return filename

        elif format.lower() == "csv":
            import csv

            filename = (
                f"dead_letter_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )

            if jobs:
                with open(filename, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=asdict(jobs[0]).keys())
                    writer.writeheader()
                    for job in jobs:
                        row = asdict(job)
                        # Convert complex fields to strings
                        row["args"] = json.dumps(row["args"])
                        if row["tags"]:
                            row["tags"] = json.dumps(row["tags"])
                        writer.writerow(row)

            logger.info(f"Exported {len(jobs)} dead letter jobs to {filename}")
            return filename

        else:
            raise ValueError(f"Unsupported export format: {format}")


# Global manager instance
_dead_letter_manager = DeadLetterManager()


# Public API
async def setup_dead_letter_queue():
    """Setup dead letter queue database tables"""
    await _dead_letter_manager.setup_database()


async def move_job_to_dead_letter(
    job_id: str, reason: DeadLetterReason, tags: Optional[Dict[str, str]] = None
) -> bool:
    """Move a job to the dead letter queue"""
    return await _dead_letter_manager.move_job_to_dead_letter(job_id, reason, tags)


async def resurrect_job(
    dead_letter_id: str,
    reset_attempts: bool = True,
    new_max_attempts: Optional[int] = None,
    new_priority: Optional[int] = None,
    new_queue: Optional[str] = None,
) -> Optional[str]:
    """Resurrect a job from the dead letter queue"""
    return await _dead_letter_manager.resurrect_job(
        dead_letter_id, reset_attempts, new_max_attempts, new_priority, new_queue
    )


async def bulk_resurrect_jobs(
    filter_criteria: DeadLetterFilter,
    reset_attempts: bool = True,
    new_max_attempts: Optional[int] = None,
) -> List[str]:
    """Resurrect multiple jobs matching filter criteria"""
    return await _dead_letter_manager.bulk_resurrect(
        filter_criteria, reset_attempts, new_max_attempts
    )


async def delete_dead_letter_job(dead_letter_id: str) -> bool:
    """Permanently delete a dead letter job"""
    return await _dead_letter_manager.delete_dead_letter_job(dead_letter_id)


async def bulk_delete_dead_letter_jobs(filter_criteria: DeadLetterFilter) -> int:
    """Delete multiple dead letter jobs matching filter criteria"""
    return await _dead_letter_manager.bulk_delete(filter_criteria)


async def list_dead_letter_jobs(
    filter_criteria: Optional[DeadLetterFilter] = None,
) -> List[DeadLetterJob]:
    """List dead letter jobs with optional filtering"""
    return await _dead_letter_manager.list_dead_letter_jobs(filter_criteria)


async def get_dead_letter_job(dead_letter_id: str) -> Optional[DeadLetterJob]:
    """Get a specific dead letter job by ID"""
    return await _dead_letter_manager.get_dead_letter_job(dead_letter_id)


async def get_dead_letter_stats(hours: Optional[int] = None) -> DeadLetterStats:
    """Get dead letter queue statistics"""
    return await _dead_letter_manager.get_dead_letter_stats(hours)


async def cleanup_old_dead_letter_jobs(days: int = 30) -> int:
    """Clean up dead letter jobs older than specified days"""
    return await _dead_letter_manager.cleanup_old_dead_letter_jobs(days)


async def export_dead_letter_jobs(
    filter_criteria: Optional[DeadLetterFilter] = None, format: str = "json"
) -> str:
    """Export dead letter jobs to file"""
    return await _dead_letter_manager.export_dead_letter_jobs(filter_criteria, format)


def create_filter() -> DeadLetterFilter:
    """Create a new dead letter filter"""
    return DeadLetterFilter()
