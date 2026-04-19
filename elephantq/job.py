"""
Job model, status enum, and runtime context.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class Snooze:
    """
    Return value for a job handler that wants to defer without consuming a retry.

    Returning `Snooze(seconds=N, reason="...")` from a handler re-schedules
    the job to run again in N seconds with the attempts counter unchanged.
    Use it for rate-limited APIs (e.g. HTTP 429), webhook backpressure, or
    any "not ready yet" condition where a retry would be wasted.

    The duration is capped by the `snooze_max_seconds` setting to prevent
    a runaway handler from scheduling a job arbitrarily far into the future.
    """

    seconds: float
    reason: Optional[str] = field(default=None)


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
