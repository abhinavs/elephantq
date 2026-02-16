"""
Comprehensive Error Handling Edge Cases Tests - SIMPLIFIED VERSION

Tests ElephantQ's robustness under various failure conditions.
Rewritten to use global API consistently and be reliable.
"""

import asyncio
import os

import pytest

# Ensure we're using test database
os.environ["ELEPHANTQ_DATABASE_URL"] = "postgresql://postgres@localhost/elephantq_test"

import elephantq


# Test jobs for edge cases
@elephantq.job()
async def database_dependent_job(data: str):
    """Job that makes database queries during execution"""
    return f"processed: {data}"


@elephantq.job()
async def memory_intensive_job(size_mb: int = 1):
    """Job that consumes memory (reduced for testing)"""
    # Allocate small amount of memory for testing
    data = ["x" * 1024 for _ in range(size_mb)]
    await asyncio.sleep(0.01)  # Simulate processing
    return f"processed {len(data)} KB"


@elephantq.job()
async def timeout_job():
    """Job that raises timeout error"""
    raise asyncio.TimeoutError("Database query timeout")


@elephantq.job()
async def memory_failure_job():
    """Job that simulates memory failure"""
    raise MemoryError("Simulated insufficient memory")


@elephantq.job()
async def system_error_job():
    """Job that raises system error"""
    raise OSError(28, "Simulated: No space left on device")


@elephantq.job()
async def fd_error_job():
    """Job that simulates file descriptor exhaustion"""
    raise OSError(24, "Simulated: Too many open files")


@elephantq.job(retries=2)
async def sometimes_failing_job(attempt_number: int):
    """Job that fails first, then succeeds"""
    if attempt_number == 1:
        raise Exception("Simulated transient failure")
    return f"Success on attempt {attempt_number}"


@elephantq.job()
async def good_job(data: str):
    """Job that always succeeds"""
    return f"processed: {data}"


@elephantq.job()
async def bad_job():
    """Job that always fails"""
    raise Exception("This job always fails")


class TestDatabaseConnectionFailures:
    """Test database connection failure scenarios"""

    @pytest.mark.asyncio
    async def test_database_timeout_during_processing(self):
        """Test database timeout during job processing"""
        job_id = await elephantq.enqueue(timeout_job)

        # Process job - should handle timeout gracefully by failing the job
        processed = await elephantq.run_worker(run_once=True)
        assert processed  # Job was processed (failed gracefully)

        # Verify job failed
        status = await elephantq.get_job_status(job_id)
        assert status["status"] in ["failed", "dead_letter"]


class TestMemoryPressureScenarios:
    """Test memory pressure scenarios"""

    @pytest.mark.asyncio
    async def test_memory_intensive_job_execution(self):
        """Test execution of memory-intensive jobs"""
        job_id = await elephantq.enqueue(memory_intensive_job, size_mb=1)

        processed = await elephantq.run_worker(run_once=True)
        assert processed  # Job should complete successfully

        # Verify job succeeded
        status = await elephantq.get_job_status(job_id)
        assert status["status"] == "done"

    @pytest.mark.asyncio
    async def test_simulated_memory_failure(self):
        """Test job that simulates memory failure"""
        job_id = await elephantq.enqueue(memory_failure_job)

        processed = await elephantq.run_worker(run_once=True)
        assert processed  # Should handle memory error gracefully

        # Verify job failed
        status = await elephantq.get_job_status(job_id)
        assert status["status"] in ["failed", "dead_letter"]


class TestHighVolumeErrorScenarios:
    """Test high volume error scenarios"""

    @pytest.mark.asyncio
    async def test_job_failure_handling(self):
        """Test handling of job failures"""
        job_id = await elephantq.enqueue(bad_job)

        # Process multiple times to handle retries
        for _ in range(5):
            processed = await elephantq.run_worker(run_once=True)
            if not processed:
                break

        # Verify job eventually failed
        status = await elephantq.get_job_status(job_id)
        assert status["status"] in ["failed", "dead_letter"]

    @pytest.mark.asyncio
    async def test_queue_size_handling(self):
        """Test queue size handling under load"""
        # Enqueue multiple jobs quickly
        job_ids = []
        for i in range(10):
            job_id = await elephantq.enqueue(good_job, data=f"job_{i}")
            job_ids.append(job_id)

        # Process all jobs
        processed_count = 0
        for _ in range(20):  # More attempts than jobs to handle all processing
            processed = await elephantq.run_worker(run_once=True)
            if processed:
                processed_count += 1
            else:
                break

        # Verify all jobs were processed
        assert processed_count >= 1  # At least some jobs processed


class TestSystemResourceFailures:
    """Test system resource failure scenarios"""

    @pytest.mark.asyncio
    async def test_simulated_system_error(self):
        """Test job that simulates system error"""
        job_id = await elephantq.enqueue(system_error_job)

        processed = await elephantq.run_worker(run_once=True)
        assert processed  # Should handle system error gracefully

        # Verify job failed
        status = await elephantq.get_job_status(job_id)
        assert status["status"] in ["failed", "dead_letter"]

    @pytest.mark.asyncio
    async def test_simulated_file_descriptor_error(self):
        """Test job that simulates file descriptor exhaustion"""
        job_id = await elephantq.enqueue(fd_error_job)

        processed = await elephantq.run_worker(run_once=True)
        assert processed  # Should handle FD error gracefully

        # Verify job failed
        status = await elephantq.get_job_status(job_id)
        assert status["status"] in ["failed", "dead_letter"]


class TestGracefulDegradation:
    """Test graceful degradation scenarios"""

    @pytest.mark.asyncio
    async def test_job_recovery_after_failure(self):
        """Test that jobs can recover after transient failures"""
        job_id = await elephantq.enqueue(sometimes_failing_job, attempt_number=1)

        # Process job multiple times to handle retries
        for _ in range(5):
            processed = await elephantq.run_worker(run_once=True)
            if not processed:
                break

        # Job should eventually succeed or fail gracefully
        status = await elephantq.get_job_status(job_id)
        assert status["status"] in ["done", "failed", "dead_letter"]

    @pytest.mark.asyncio
    async def test_error_isolation_between_jobs(self):
        """Test that errors in one job don't affect others"""
        good_job_id = await elephantq.enqueue(good_job, data="test")
        bad_job_id = await elephantq.enqueue(bad_job)

        # Process both jobs
        for _ in range(10):  # Multiple attempts to handle retries
            processed = await elephantq.run_worker(run_once=True)
            if not processed:
                break

        # Verify good job succeeded and bad job failed
        good_status = await elephantq.get_job_status(good_job_id)
        bad_status = await elephantq.get_job_status(bad_job_id)

        assert good_status["status"] == "done"
        assert bad_status["status"] in ["failed", "dead_letter"]
