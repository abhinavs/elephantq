"""
Tests for job introspection and management

These tests cover the job management features that developers use to check on their jobs,
retry failed ones, cancel long-running ones, etc. Real-world stuff that matters.
"""

import pytest

import soniq


async def process_test_jobs():
    """Helper to process jobs from all test queues using global API"""
    # Use the global API worker to process jobs from all relevant test queues
    await soniq.run_worker(
        run_once=True, queues=["test", "unique_test", "priority_test", "default"]
    )


# Set up test environment
import os  # noqa: E402

from tests.db_utils import TEST_DATABASE_URL  # noqa: E402

os.environ["SONIQ_DATABASE_URL"] = TEST_DATABASE_URL


# Some test jobs to work with
@soniq.job(name="simple_task", retries=2, priority=50, queue="test")
async def simple_task(message: str):
    return f"Processed: {message}"


@soniq.job(name="unique_task", retries=1, priority=10, queue="unique_test", unique=True)
async def unique_task(task_id: str):
    return f"Unique task: {task_id}"


@soniq.job(name="priority_task", retries=3, priority=1, queue="priority_test")
async def priority_task(data: str):
    return f"Priority task: {data}"


class TestJobIntrospection:
    """Test job status and introspection features"""

    # Database setup handled by conftest.py

    @pytest.mark.asyncio
    async def test_get_job_existing_job(self):
        """Getting status for a job that exists should work as expected"""

        # Table clearing handled by conftest.py

        # Put a job in the queue
        job_id = await soniq.enqueue("simple_task", args={"message": "test"})

        # Now check its status
        status = await soniq.get_job(job_id)

        # Should get back all the details we expect
        assert status is not None
        assert status["id"] == job_id
        # Job name includes the full module path
        expected_job_name = "simple_task"
        assert status["job_name"] == expected_job_name
        assert status["status"] == "queued"
        assert status["queue"] == "test"
        assert status["priority"] == 50
        assert status["attempts"] == 0
        assert status["max_attempts"] == 3  # retries=2 -> max_attempts=3
        assert status["args"] == {"message": "test"}
        assert "created_at" in status
        assert "updated_at" in status

    @pytest.mark.asyncio
    async def test_get_job_nonexistent_job(self):
        """Test getting status of non-existent job"""
        status = await soniq.get_job("00000000-0000-0000-0000-000000000000")
        assert status is None

    @pytest.mark.asyncio
    async def test_cancel_queued_job(self):
        """Test cancelling a queued job"""
        # Enqueue a job
        job_id = await soniq.enqueue("simple_task", args={"message": "cancel_me"})

        # Cancel the job
        success = await soniq.cancel_job(job_id)
        assert success is True

        # Verify job is cancelled
        status = await soniq.get_job(job_id)
        assert status["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job(self):
        """Test cancelling non-existent job"""
        success = await soniq.cancel_job("00000000-0000-0000-0000-000000000000")
        assert success is False

    @pytest.mark.asyncio
    async def test_cancel_processed_job(self):
        """Test that completed jobs cannot be cancelled"""
        # Enqueue and process a job
        job_id = await soniq.enqueue("simple_task", args={"message": "process_me"})

        await process_test_jobs()

        # Try to cancel the completed job
        success = await soniq.cancel_job(job_id)
        assert success is False, "Should not be able to cancel completed job"

        # Verify job is still done
        status = await soniq.get_job(job_id)
        assert status["status"] == "done"

    @pytest.mark.asyncio
    async def test_retry_failed_job(self):
        """DLQ Option A: dead-lettered jobs leave soniq_jobs and live in
        soniq_dead_letter_jobs as the single source of truth. retry_job only
        matches status='failed' rows in soniq_jobs, so it is a no-op for
        dead-lettered jobs (returns False). Resurrection happens via
        DeadLetterService.replay()."""

        @soniq.job(name="failing_task", retries=1, queue="test")
        async def failing_task():
            raise Exception("Intentional failure")

        job_id = await soniq.enqueue("failing_task")

        # Process to make it fail - retries=1 means max_attempts=2
        await process_test_jobs()  # First attempt (fails, retries)
        await process_test_jobs()  # Second attempt (dead-letters)

        # Verify it left soniq_jobs.
        assert await soniq.get_job(job_id) is None

        # retry_job is a no-op for dead-lettered jobs.
        assert await soniq.retry_job(job_id) is False

    @pytest.mark.asyncio
    async def test_retry_queued_job(self):
        """Test that queued jobs cannot be retried"""
        job_id = await soniq.enqueue("simple_task", args={"message": "queued_job"})

        success = await soniq.retry_job(job_id)
        assert success is False

    @pytest.mark.asyncio
    async def test_delete_job(self):
        """Test deleting a job"""
        job_id = await soniq.enqueue("simple_task", args={"message": "delete_me"})

        # Delete the job
        success = await soniq.delete_job(job_id)
        assert success is True

        # Verify job is gone
        status = await soniq.get_job(job_id)
        assert status is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_job(self):
        """Test deleting non-existent job"""
        success = await soniq.delete_job("00000000-0000-0000-0000-000000000000")
        assert success is False


class TestJobListing:
    """Test job listing and filtering features"""

    # Database setup handled by conftest.py

    @pytest.mark.asyncio
    async def test_list_all_jobs(self):
        """Test listing all jobs"""
        # Enqueue multiple jobs
        job1 = await soniq.enqueue("simple_task", args={"message": "job1"})
        job2 = await soniq.enqueue("priority_task", args={"data": "job2"})
        job3 = await soniq.enqueue("unique_task", args={"task_id": "job3"})

        # List all jobs
        jobs = await soniq.list_jobs(limit=10)

        assert len(jobs) == 3
        job_ids = {job["id"] for job in jobs}
        assert {job1, job2, job3}.issubset(job_ids)

    @pytest.mark.asyncio
    async def test_list_jobs_by_queue(self):
        """Test filtering jobs by queue"""
        # Enqueue jobs in different queues
        await soniq.enqueue(
            "simple_task", args={"message": "test_queue_job"}
        )  # test queue
        await soniq.enqueue(
            "priority_task", args={"data": "priority_queue_job"}
        )  # priority_test queue

        # Filter by test queue
        test_jobs = await soniq.list_jobs(queue="test")
        assert len(test_jobs) == 1
        assert test_jobs[0]["queue"] == "test"

        # Filter by priority_test queue
        priority_jobs = await soniq.list_jobs(queue="priority_test")
        assert len(priority_jobs) == 1
        assert priority_jobs[0]["queue"] == "priority_test"

    @pytest.mark.asyncio
    async def test_list_jobs_by_status(self):
        """Test filtering jobs by status"""
        # Enqueue jobs - one will be processed, one scheduled for future
        await soniq.enqueue("simple_task", args={"message": "immediate_job"})
        from datetime import datetime, timedelta, timezone

        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        await soniq.enqueue(
            "simple_task", args={"message": "future_job"}, scheduled_at=future_time
        )

        # Process jobs - only immediate job should be processed
        await process_test_jobs()

        # List queued jobs (should include the future job)
        queued_jobs = await soniq.list_jobs(status="queued")
        assert len(queued_jobs) >= 1
        assert all(job["status"] == "queued" for job in queued_jobs)

        # List done jobs (should include the immediate job)
        done_jobs = await soniq.list_jobs(status="done")
        assert len(done_jobs) >= 1
        assert all(job["status"] == "done" for job in done_jobs)

    @pytest.mark.asyncio
    async def test_list_jobs_with_limit(self):
        """Test job listing with limit"""
        # Enqueue multiple jobs
        for i in range(5):
            await soniq.enqueue("simple_task", args={"message": f"job_{i}"})

        # List with limit
        jobs = await soniq.list_jobs(limit=3)
        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_list_jobs_with_offset(self):
        """Test job listing with offset"""
        # Enqueue jobs
        job_ids = []
        for i in range(5):
            job_id = await soniq.enqueue(
                "simple_task", args={"message": f"offset_job_{i}"}
            )
            job_ids.append(job_id)

        # Get first 2 jobs
        first_batch = await soniq.list_jobs(limit=2, offset=0)
        assert len(first_batch) == 2

        # Get next 2 jobs
        second_batch = await soniq.list_jobs(limit=2, offset=2)
        assert len(second_batch) == 2

        # Ensure no overlap
        first_ids = {job["id"] for job in first_batch}
        second_ids = {job["id"] for job in second_batch}
        assert first_ids.isdisjoint(second_ids)


class TestUniqueJobs:
    """Test unique job functionality"""

    # Database setup handled by conftest.py

    @pytest.mark.asyncio
    async def test_unique_job_prevention(self):
        """Test that unique jobs prevent duplicates"""
        # Enqueue same unique job twice
        job1 = await soniq.enqueue("unique_task", args={"task_id": "same_task"})
        job2 = await soniq.enqueue("unique_task", args={"task_id": "same_task"})

        # Should return same job ID
        assert job1 == job2

        # Verify only one job exists
        jobs = await soniq.list_jobs(queue="unique_test")
        assert len(jobs) == 1
        assert jobs[0]["id"] == job1

    @pytest.mark.asyncio
    async def test_unique_job_different_args(self):
        """Test that unique jobs with different args are allowed"""
        job1 = await soniq.enqueue("unique_task", args={"task_id": "task1"})
        job2 = await soniq.enqueue("unique_task", args={"task_id": "task2"})

        # Should be different job IDs
        assert job1 != job2

        # Verify both jobs exist
        jobs = await soniq.list_jobs(queue="unique_test")
        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_unique_job_after_completion(self):
        """Test that unique jobs can be re-enqueued after completion"""
        # Enqueue and process unique job
        job1 = await soniq.enqueue("unique_task", args={"task_id": "completed_task"})
        await process_test_jobs()

        # Verify job is done
        status = await soniq.get_job(job1)
        assert status["status"] == "done"

        # Enqueue same unique job again
        job2 = await soniq.enqueue("unique_task", args={"task_id": "completed_task"})

        # Should be a new job ID
        assert job1 != job2

        # Verify new job is queued
        status = await soniq.get_job(job2)
        assert status["status"] == "queued"

    @pytest.mark.asyncio
    async def test_non_unique_job_allows_duplicates(self):
        """Test that non-unique jobs allow duplicates"""
        # Table clearing handled by conftest.py

        # Enqueue same non-unique job twice
        job1 = await soniq.enqueue("simple_task", args={"message": "same_message"})
        job2 = await soniq.enqueue("simple_task", args={"message": "same_message"})

        # Should be different job IDs
        assert job1 != job2

        # Verify both jobs exist
        jobs = await soniq.list_jobs(queue="test")
        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_unique_override_parameter(self):
        """Test unique parameter override in enqueue"""
        # Non-unique job made unique via parameter
        job1 = await soniq.enqueue(
            "simple_task", args={"message": "override_test"}, unique=True
        )
        job2 = await soniq.enqueue(
            "simple_task", args={"message": "override_test"}, unique=True
        )

        # Should return same job ID
        assert job1 == job2

        # Verify only one job exists
        jobs = await soniq.list_jobs(queue="test")
        task_jobs = [job for job in jobs if job["args"]["message"] == "override_test"]
        assert len(task_jobs) == 1


class TestQueueStats:
    """Test queue statistics functionality"""

    # Database setup handled by conftest.py

    @pytest.mark.asyncio
    async def test_empty_queue_stats(self):
        """get_queue_stats on an empty instance returns the canonical six-key
        zero-shape dict (per docs/contracts/queue_stats.md)."""
        stats = await soniq.get_queue_stats()
        assert stats == {
            "total": 0,
            "queued": 0,
            "processing": 0,
            "done": 0,
            "dead_letter": 0,
            "cancelled": 0,
        }

    @pytest.mark.asyncio
    async def test_queue_stats_with_jobs(self):
        """Whole-instance counts roll up across queues."""
        # Enqueue jobs in different queues
        await soniq.enqueue("simple_task", args={"message": "test1"})  # test queue
        await soniq.enqueue("simple_task", args={"message": "test2"})  # test queue
        await soniq.enqueue(
            "priority_task", args={"data": "priority1"}
        )  # priority_test queue

        # Cancel one job
        job_to_cancel = await soniq.enqueue(
            "simple_task", args={"message": "cancel_me"}
        )
        await soniq.cancel_job(job_to_cancel)

        # Process some jobs
        await process_test_jobs()

        stats = await soniq.get_queue_stats()
        assert stats["total"] >= 4
        assert stats["cancelled"] >= 1

    @pytest.mark.asyncio
    async def test_queue_stats_structure(self):
        """Stats are the canonical 6-key dict from soniq.types.QueueStats."""
        await soniq.enqueue("simple_task", args={"message": "stats_test"})

        stats = await soniq.get_queue_stats()
        required_fields = {
            "total",
            "queued",
            "processing",
            "done",
            "dead_letter",
            "cancelled",
        }
        assert set(stats.keys()) == required_fields
        for field in required_fields:
            assert isinstance(stats[field], int)

        assert stats["total"] == 1
        assert stats["queued"] == 1
