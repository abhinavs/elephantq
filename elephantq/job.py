"""
Job model, status enum, and runtime context.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    """Job lifecycle statuses."""

    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class JobContext:
    """
    Runtime metadata about the currently executing job.

    Injected automatically into job functions that declare a
    parameter with this type annotation.

    Example:
        @elephantq.job()
        async def process_order(order_id: str, ctx: JobContext):
            print(f"Job {ctx.job_id}, attempt {ctx.attempt}")
    """

    job_id: str
    job_name: str
    attempt: int
    max_attempts: int
    queue: str
    worker_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
