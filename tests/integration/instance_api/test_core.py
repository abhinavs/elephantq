"""
Test suite for ElephantQ core functionality
"""

import json
import logging
import os
import uuid

import pytest
from pydantic import BaseModel

import elephantq
from elephantq.core.registry import get_job
from elephantq.db.connection import close_pool

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)

# Set test database URL for all tests
os.environ["ELEPHANTQ_DATABASE_URL"] = "postgresql://postgres@localhost/elephantq_test"


class SampleJobArgs(BaseModel):
    x: int
    y: int


_flaky_job_fail_counts = {}


@pytest.mark.asyncio
async def test_enqueue_and_run_job():
    """Test job enqueue and processing with instance-based architecture"""
    # Create a ElephantQ instance for testing (not using global)
    app = elephantq.ElephantQ(
        database_url="postgresql://postgres@localhost/elephantq_test"
    )

    # Register job with the instance
    @app.job(retries=5, args_model=SampleJobArgs)
    async def instance_sample_job(x, y):
        return x + y

    # Clear test table using instance pool to ensure consistency
    instance_pool = await app.get_pool()
    async with instance_pool.acquire() as conn:
        await conn.execute("DELETE FROM elephantq_jobs")

    # Enqueue job using instance API
    job_id = await app.enqueue(instance_sample_job, x=1, y=2)
    assert job_id

    # Process the job using instance worker
    await app.run_worker(run_once=True)

    # Check job status using instance pool
    async with instance_pool.acquire() as conn:
        job_record = await conn.fetchrow(
            "SELECT * FROM elephantq_jobs WHERE id = $1", uuid.UUID(job_id)
        )

        assert job_record is not None, f"Job {job_id} not found in database"
        assert (
            job_record["job_name"]
            == "tests.integration.instance_api.test_core.instance_sample_job"
        )
        assert json.loads(job_record["args"]) == {"x": 1, "y": 2}
        assert job_record["max_attempts"] == 6  # retries=5 -> max_attempts=6
        assert job_record["status"] == "done"

    # Clean up the instance
    await app.close()


@pytest.mark.asyncio
async def test_enqueue_job_invalid_args():
    # Configure global app to use test database
    elephantq.configure(database_url="postgresql://postgres@localhost/elephantq_test")

    # Define job with args validation
    @elephantq.job(retries=5, args_model=SampleJobArgs)
    async def sample_job(x, y):
        return x + y

    # Clear test table using global app pool
    global_app = elephantq._get_global_app()
    global_pool = await global_app.get_pool()
    async with global_pool.acquire() as conn:
        await conn.execute("DELETE FROM elephantq_jobs")

    with pytest.raises(ValueError, match="Invalid arguments for job"):
        await elephantq.enqueue(sample_job, x=1, y="invalid")

    # Clean up global app
    if global_app.is_initialized:
        await global_app.close()


@pytest.mark.asyncio
async def test_retry_mechanism():
    global _flaky_job_fail_counts
    _flaky_job_fail_counts = {}  # Reset for this test

    # Configure global app to use test database
    elephantq.configure(database_url="postgresql://postgres@localhost/elephantq_test")

    # Define flaky job that fails first 2 times then succeeds
    @elephantq.job(retries=3)
    async def flaky_job(job_id: str, should_fail: bool):
        if should_fail:
            _flaky_job_fail_counts[job_id] = (
                _flaky_job_fail_counts.get(job_id, 0) + 1
            )
            if _flaky_job_fail_counts[job_id] <= 2:
                raise ValueError("Simulated failure")
        return "Success"

    # Define job that always fails
    @elephantq.job(retries=3)
    async def always_fail_job(job_id: str):
        raise ValueError("Always fails")

    # Clear test table using global app pool
    global_app = elephantq._get_global_app()
    global_pool = await global_app.get_pool()
    async with global_pool.acquire() as conn:
        await conn.execute("DELETE FROM elephantq_jobs")

    # Test job that succeeds after retries
    job_id_1 = str(uuid.uuid4())
    actual_job_id_1 = await elephantq.enqueue(
        flaky_job, job_id=job_id_1, should_fail=True
    )

    # Process job using global worker (will retry until success or max attempts)
    await elephantq.run_worker(run_once=True)

    # Check final status - should have succeeded after 3 attempts (2 failures + 1 success)
    async with global_pool.acquire() as conn:
        job_record = await conn.fetchrow(
            "SELECT * FROM elephantq_jobs WHERE id = $1", uuid.UUID(actual_job_id_1)
        )
        assert job_record["status"] == "done"
        assert job_record["attempts"] == 2  # 2 failed attempts, then success

    # Test job that exceeds max retries
    job_id_2 = str(uuid.uuid4())
    actual_job_id_2 = await elephantq.enqueue(always_fail_job, job_id=job_id_2)

    # Process job using global worker (will retry until max attempts reached)
    await elephantq.run_worker(run_once=True)

    async with global_pool.acquire() as conn:
        job_record = await conn.fetchrow(
            "SELECT * FROM elephantq_jobs WHERE id = $1", uuid.UUID(actual_job_id_2)
        )
        assert job_record["status"] == "dead_letter"
        assert job_record["attempts"] == 4  # retries=3 means max_attempts=4
        assert "Always fails" in job_record["last_error"]

    # Clean up global app
    if global_app.is_initialized:
        await global_app.close()


@pytest.mark.asyncio
async def test_run_worker_processes_job():
    # Configure global app to use test database
    elephantq.configure(database_url="postgresql://postgres@localhost/elephantq_test")

    # Define sample job
    @elephantq.job(retries=5, args_model=SampleJobArgs)
    async def sample_job(x, y):
        return x + y

    # Clear test table using global app pool
    global_app = elephantq._get_global_app()
    global_pool = await global_app.get_pool()
    async with global_pool.acquire() as conn:
        await conn.execute("DELETE FROM elephantq_jobs")

    # Enqueue job using global API
    job_id = await elephantq.enqueue(sample_job, x=10, y=20)

    # Process job using global worker
    await elephantq.run_worker(run_once=True)

    # Check job status using global pool
    async with global_pool.acquire() as conn:
        job_record = await conn.fetchrow(
            "SELECT * FROM elephantq_jobs WHERE id = $1", uuid.UUID(job_id)
        )
        assert job_record["status"] == "done"

    # Clean up global app
    if global_app.is_initialized:
        await global_app.close()


@pytest.mark.asyncio
async def test_cli_worker():
    # Test that CLI worker module can be imported and executed
    # This verifies the CLI structure is correct

    # Test importing the CLI main function
    from elephantq.cli.main import main

    assert main is not None

    # Test that we can access run_worker through global API (which uses ElephantQ instance)
    import elephantq

    assert elephantq.run_worker is not None

    # Test that ElephantQ instances have run_worker method
    from elephantq import ElephantQ

    app = ElephantQ(database_url="postgresql://postgres@localhost/elephantq_test")
    assert app.run_worker is not None


@pytest.mark.asyncio
async def test_task_discovery():
    # Configure global app to use test database
    elephantq.configure(database_url="postgresql://postgres@localhost/elephantq_test")

    # Clear test table using global app pool
    global_app = elephantq._get_global_app()
    global_pool = await global_app.get_pool()
    async with global_pool.acquire() as conn:
        await conn.execute("DELETE FROM elephantq_jobs")

    # Temporarily set the environment variable for task discovery
    original_env = os.environ.copy()
    os.environ["ELEPHANTQ_JOBS_MODULES"] = "jobs.my_tasks"

    # Import the module to trigger discovery
    import importlib

    importlib.import_module("jobs.my_tasks")

    # Verify that the discovered job is registered
    discovered_job_meta = get_job("jobs.my_tasks.discovered_job")
    assert discovered_job_meta is not None

    # Enqueue the discovered job using global API
    await elephantq.enqueue(
        discovered_job_meta["func"], message="Hello from discovered job!"
    )

    # Process using global worker
    await elephantq.run_worker(run_once=True)

    # Check job status using global pool
    async with global_pool.acquire() as conn:
        job_record = await conn.fetchrow(
            "SELECT * FROM elephantq_jobs WHERE job_name = 'jobs.my_tasks.discovered_job'"
        )
        assert job_record["status"] == "done"

    # Clean up global app
    global_app = elephantq._get_global_app()
    if global_app.is_initialized:
        await global_app.close()

    # Restore original environment variables
    os.environ.clear()
    os.environ.update(original_env)
    await close_pool()
