"""
Job Dependencies System for ElephantQ.
Implements job dependency tracking and enforcement.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from elephantq.db.context import get_context_pool

from .flags import require_feature


class DependencyStatus(Enum):
    """Status of job dependencies"""

    PENDING = "pending"  # Dependencies not yet checked
    WAITING = "waiting"  # Waiting for dependencies to complete
    READY = "ready"  # Dependencies satisfied, ready to run
    FAILED = "failed"  # One or more dependencies failed
    TIMEOUT = "timeout"  # Dependency wait timed out


async def store_job_dependencies(
    job_id: str, dependencies: List[str], dependency_timeout: Optional[int] = None
) -> bool:
    """
    Store job dependencies in the database

    Args:
        job_id: ID of the job that has dependencies
        dependencies: List of job IDs this job depends on
        dependency_timeout: Timeout in seconds for waiting for dependencies

    Returns:
        True if stored successfully
    """
    require_feature("dependencies_enabled", "Job dependencies")
    if not dependencies:
        return True

    pool = await get_context_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Create dependency table if it doesn't exist
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS elephantq_job_dependencies (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    job_id UUID NOT NULL REFERENCES elephantq_jobs(id) ON DELETE CASCADE,
                    depends_on_job_id UUID NOT NULL,
                    dependency_status TEXT DEFAULT 'pending' CHECK (dependency_status IN ('pending', 'waiting', 'ready', 'failed', 'timeout')),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    timeout_at TIMESTAMP,
                    UNIQUE(job_id, depends_on_job_id)
                )
            """
            )

            # Store each dependency
            for dep_job_id in dependencies:
                try:
                    dep_uuid = uuid.UUID(dep_job_id)
                except ValueError:
                    continue

                timeout_at = None
                if dependency_timeout:
                    timeout_at = datetime.now() + timedelta(seconds=dependency_timeout)

                await conn.execute(
                    """
                    INSERT INTO elephantq_job_dependencies 
                    (job_id, depends_on_job_id, timeout_at)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (job_id, depends_on_job_id) DO NOTHING
                """,
                    uuid.UUID(job_id),
                    dep_uuid,
                    timeout_at,
                )

    return True


async def add_job_dependency(
    job_id: str, depends_on_job_id: str, dependency_timeout: Optional[int] = None
) -> bool:
    """Add a single job dependency."""
    return await store_job_dependencies(job_id, [depends_on_job_id], dependency_timeout)


async def check_job_dependencies(job_id: str) -> DependencyStatus:
    """
    Check if job dependencies are satisfied

    Args:
        job_id: Job ID to check dependencies for

    Returns:
        DependencyStatus indicating current state
    """
    pool = await get_context_pool()
    async with pool.acquire() as conn:
        # Get all dependencies for this job
        dependencies = await conn.fetch(
            """
            SELECT d.depends_on_job_id, d.dependency_status, d.timeout_at,
                   j.status as dep_job_status, j.id as dep_job_exists
            FROM elephantq_job_dependencies d
            LEFT JOIN elephantq_jobs j ON d.depends_on_job_id = j.id
            WHERE d.job_id = $1
        """,
            uuid.UUID(job_id),
        )

        if not dependencies:
            # No dependencies, job is ready
            return DependencyStatus.READY

        # Check each dependency
        pending_count = 0
        failed_count = 0
        timeout_count = 0
        completed_count = 0

        for dep in dependencies:
            # Check for timeout
            if dep["timeout_at"] and datetime.now() > dep["timeout_at"]:
                timeout_count += 1
                # Update status to timeout
                await conn.execute(
                    """
                    UPDATE elephantq_job_dependencies 
                    SET dependency_status = 'timeout', updated_at = NOW()
                    WHERE job_id = $1 AND depends_on_job_id = $2
                """,
                    uuid.UUID(job_id),
                    dep["depends_on_job_id"],
                )
                continue

            # Check if dependency job exists
            if not dep["dep_job_exists"]:
                # Dependency job doesn't exist, treat as failed
                failed_count += 1
                await conn.execute(
                    """
                    UPDATE elephantq_job_dependencies 
                    SET dependency_status = 'failed', updated_at = NOW()
                    WHERE job_id = $1 AND depends_on_job_id = $2
                """,
                    uuid.UUID(job_id),
                    dep["depends_on_job_id"],
                )
                continue

            dep_status = dep["dep_job_status"]

            if dep_status == "done":
                completed_count += 1
                # Update dependency status to ready
                await conn.execute(
                    """
                    UPDATE elephantq_job_dependencies 
                    SET dependency_status = 'ready', updated_at = NOW()
                    WHERE job_id = $1 AND depends_on_job_id = $2
                """,
                    uuid.UUID(job_id),
                    dep["depends_on_job_id"],
                )

            elif dep_status in ("failed", "dead_letter"):
                failed_count += 1
                # Update dependency status to failed
                await conn.execute(
                    """
                    UPDATE elephantq_job_dependencies 
                    SET dependency_status = 'failed', updated_at = NOW()
                    WHERE job_id = $1 AND depends_on_job_id = $2
                """,
                    uuid.UUID(job_id),
                    dep["depends_on_job_id"],
                )

            else:
                # Still pending (queued, or other status)
                pending_count += 1
                # Update dependency status to waiting
                await conn.execute(
                    """
                    UPDATE elephantq_job_dependencies 
                    SET dependency_status = 'waiting', updated_at = NOW()
                    WHERE job_id = $1 AND depends_on_job_id = $2
                """,
                    uuid.UUID(job_id),
                    dep["depends_on_job_id"],
                )

        # Determine overall status
        if timeout_count > 0:
            return DependencyStatus.TIMEOUT
        elif failed_count > 0:
            return DependencyStatus.FAILED
        elif pending_count > 0:
            return DependencyStatus.WAITING
        else:
            # All dependencies completed
            return DependencyStatus.READY


async def get_jobs_ready_to_run(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Get jobs that are ready to run (no pending dependencies)

    Args:
        limit: Maximum number of jobs to return

    Returns:
        List of job records that are ready to run
    """
    require_feature("dependencies_enabled", "Job dependencies")
    pool = await get_context_pool()
    async with pool.acquire() as conn:
        # Get queued jobs that either have no dependencies or all dependencies are satisfied
        jobs = await conn.fetch(
            """
            SELECT DISTINCT j.*
            FROM elephantq_jobs j
            LEFT JOIN elephantq_job_dependencies d ON j.id = d.job_id
            WHERE j.status = 'queued'
            AND (j.scheduled_at IS NULL OR j.scheduled_at <= NOW())
            AND (
                d.job_id IS NULL  -- No dependencies
                OR NOT EXISTS (   -- OR all dependencies are satisfied
                    SELECT 1 FROM elephantq_job_dependencies d2 
                    WHERE d2.job_id = j.id 
                    AND d2.dependency_status NOT IN ('ready')
                )
            )
            ORDER BY j.priority ASC, j.created_at ASC
            LIMIT $1
        """,
            limit,
        )

        return [dict(job) for job in jobs]


async def update_dependent_jobs(completed_job_id: str) -> int:
    """
    Update jobs that were waiting for the completed job

    Args:
        completed_job_id: ID of job that just completed

    Returns:
        Number of jobs that may now be ready to run
    """
    require_feature("dependencies_enabled", "Job dependencies")
    pool = await get_context_pool()
    async with pool.acquire() as conn:
        # Find jobs that were waiting for this dependency
        waiting_jobs = await conn.fetch(
            """
            SELECT DISTINCT d.job_id
            FROM elephantq_job_dependencies d
            WHERE d.depends_on_job_id = $1
            AND d.dependency_status = 'waiting'
        """,
            uuid.UUID(completed_job_id),
        )

        updated_count = 0

        # Check each waiting job to see if it's now ready
        for row in waiting_jobs:
            job_id = str(row["job_id"])
            status = await check_job_dependencies(job_id)

            if status == DependencyStatus.READY:
                # Job is now ready - could trigger notification or processing
                updated_count += 1

        return updated_count


async def get_job_dependency_info(job_id: str) -> Dict[str, Any]:
    """
    Get comprehensive dependency information for a job

    Args:
        job_id: Job ID to get dependency info for

    Returns:
        Dictionary with dependency information
    """
    pool = await get_context_pool()
    async with pool.acquire() as conn:
        # Get dependencies (what this job waits for)
        dependencies = await conn.fetch(
            """
            SELECT d.depends_on_job_id, d.dependency_status, d.created_at, d.timeout_at,
                   j.job_name, j.status as dep_status, j.created_at as dep_created_at,
                   j.updated_at as dep_updated_at
            FROM elephantq_job_dependencies d
            LEFT JOIN elephantq_jobs j ON d.depends_on_job_id = j.id
            WHERE d.job_id = $1
            ORDER BY d.created_at ASC
        """,
            uuid.UUID(job_id),
        )

        # Get dependents (what jobs wait for this one)
        dependents = await conn.fetch(
            """
            SELECT d.job_id as dependent_job_id, d.dependency_status, d.created_at,
                   j.job_name, j.status as dependent_status, j.created_at as dependent_created_at
            FROM elephantq_job_dependencies d
            LEFT JOIN elephantq_jobs j ON d.job_id = j.id
            WHERE d.depends_on_job_id = $1
            ORDER BY d.created_at ASC
        """,
            uuid.UUID(job_id),
        )

        return {
            "job_id": job_id,
            "dependencies": [
                {
                    "job_id": str(dep["depends_on_job_id"]),
                    "job_name": dep["job_name"],
                    "dependency_status": dep["dependency_status"],
                    "job_status": dep["dep_status"],
                    "created_at": (
                        dep["created_at"].isoformat() if dep["created_at"] else None
                    ),
                    "timeout_at": (
                        dep["timeout_at"].isoformat() if dep["timeout_at"] else None
                    ),
                    "job_created_at": (
                        dep["dep_created_at"].isoformat()
                        if dep["dep_created_at"]
                        else None
                    ),
                    "job_updated_at": (
                        dep["dep_updated_at"].isoformat()
                        if dep["dep_updated_at"]
                        else None
                    ),
                }
                for dep in dependencies
            ],
            "dependents": [
                {
                    "job_id": str(dep["dependent_job_id"]),
                    "job_name": dep["job_name"],
                    "dependency_status": dep["dependency_status"],
                    "job_status": dep["dependent_status"],
                    "created_at": (
                        dep["created_at"].isoformat() if dep["created_at"] else None
                    ),
                    "job_created_at": (
                        dep["dependent_created_at"].isoformat()
                        if dep["dependent_created_at"]
                        else None
                    ),
                }
                for dep in dependents
            ],
            "dependency_count": len(dependencies),
            "dependent_count": len(dependents),
        }


async def remove_job_dependencies(job_id: str) -> bool:
    """
    Remove all dependencies for a job (cleanup)

    Args:
        job_id: Job ID to remove dependencies for

    Returns:
        True if removed successfully
    """
    require_feature("dependencies_enabled", "Job dependencies")
    pool = await get_context_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM elephantq_job_dependencies 
            WHERE job_id = $1 OR depends_on_job_id = $1
        """,
            uuid.UUID(job_id),
        )

    return True


class DependencyManager:
    """Manager for job dependencies"""

    def __init__(self, check_interval: int = 30):
        """
        Initialize dependency manager

        Args:
            check_interval: How often to check for ready jobs (seconds)
        """
        self.check_interval = check_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the dependency manager background task"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._check_dependencies_loop())

    async def stop(self):
        """Stop the dependency manager"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _check_dependencies_loop(self):
        """Background loop to check and update dependencies"""
        while self._running:
            try:
                await self._check_all_dependencies()
            except Exception as e:
                print(f"Error checking dependencies: {e}")

            await asyncio.sleep(self.check_interval)

    async def _check_all_dependencies(self):
        """Check all pending dependencies and update statuses"""
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            # Get all jobs with pending dependencies
            jobs_with_deps = await conn.fetch(
                """
                SELECT DISTINCT d.job_id
                FROM elephantq_job_dependencies d
                JOIN elephantq_jobs j ON d.job_id = j.id
                WHERE j.status = 'queued'
                AND d.dependency_status IN ('pending', 'waiting')
            """
            )

            for row in jobs_with_deps:
                job_id = str(row["job_id"])
                await check_job_dependencies(job_id)


# Global dependency manager instance
_dependency_manager: Optional[DependencyManager] = None


async def start_dependency_manager(check_interval: int = 30) -> DependencyManager:
    """
    Start the global dependency manager

    Args:
        check_interval: How often to check dependencies in seconds

    Returns:
        DependencyManager instance
    """
    require_feature("dependencies_enabled", "Job dependencies")
    global _dependency_manager

    if _dependency_manager and _dependency_manager._running:
        return _dependency_manager

    _dependency_manager = DependencyManager(check_interval)
    await _dependency_manager.start()
    return _dependency_manager


async def stop_dependency_manager():
    """Stop the global dependency manager"""
    require_feature("dependencies_enabled", "Job dependencies")
    global _dependency_manager

    if _dependency_manager:
        await _dependency_manager.stop()
        _dependency_manager = None


def get_dependency_manager() -> Optional[DependencyManager]:
    """Get the current dependency manager instance"""
    return _dependency_manager
