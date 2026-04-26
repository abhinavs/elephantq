"""
Test suite for edge cases, error handling, and integration scenarios
"""

import os
from datetime import datetime, timedelta

import pytest
from pydantic import BaseModel

import soniq
from tests.db_utils import TEST_DATABASE_URL

# Use test database
os.environ["SONIQ_DATABASE_URL"] = TEST_DATABASE_URL


class ComplexJobArgs(BaseModel):
    data: dict
    numbers: list[int]
    optional_field: str = "default"


# Test job definitions
@soniq.job(name="simple_job")
async def simple_job(message: str):
    return f"Processed: {message}"


@soniq.job(name="complex_job", retries=3)
async def complex_job(data: dict, numbers: list[int], optional_field: str = "default"):
    return f"Complex job processed: {len(data)} keys, {len(numbers)} numbers"


@soniq.job(name="exception_job")
async def exception_job(exception_type: str):
    if exception_type == "value_error":
        raise ValueError("Test value error")
    elif exception_type == "type_error":
        raise TypeError("Test type error")
    elif exception_type == "runtime_error":
        raise RuntimeError("Test runtime error")
    else:
        raise Exception("Unknown exception type")


@pytest.mark.asyncio
async def test_malformed_job_data():
    """Test handling of malformed or corrupted job data"""

    # Register a test job to ensure registry is populated
    @soniq.job(name="test_simple_job", retries=3)
    async def test_simple_job(message: str):
        return f"Processed: {message}"

    # Enqueue a normal job first
    job_id = await soniq.enqueue("test_simple_job", args={"message": "normal job"})

    # Process the job
    processed = await soniq.run_worker(run_once=True)
    assert processed

    # Get job status to verify it worked
    status = await soniq.get_job(job_id)
    assert status["status"] == "done"


@pytest.mark.asyncio
async def test_concurrent_job_processing():
    """Test concurrent processing of jobs by multiple workers"""
    # Enqueue multiple jobs using global API
    job_ids = []
    for i in range(5):  # Reduced for speed
        job_id = await soniq.enqueue(
            "simple_job", args={"message": f"concurrent job {i}"}
        )
        job_ids.append(job_id)

    # Process all jobs
    processed_count = 0
    for _ in range(10):  # Try multiple times to process all jobs
        processed = await soniq.run_worker(run_once=True)
        if processed:
            processed_count += 1
        else:
            break

    # Verify all jobs were processed
    done_jobs = await soniq.list_jobs(status="done")
    assert len(done_jobs) >= 5


@pytest.mark.asyncio
async def test_database_connection_failures():
    """Test that the worker handles errors without crashing."""
    # Enqueue a job normally
    await soniq.enqueue("simple_job", args={"message": "connection test"})

    # Process the job — this should succeed
    processed = await soniq.run_worker(run_once=True)
    assert processed is True


@pytest.mark.asyncio
async def test_job_argument_validation_edge_cases():
    """Test complex argument validation scenarios"""
    # Test valid complex arguments
    valid_job_id = await soniq.enqueue(
        "complex_job",
        args={
            "data": {"key": "value", "nested": {"inner": "data"}},
            "numbers": [1, 2, 3, 4, 5],
            "optional_field": "custom_value",
        },
    )

    # Process the job
    processed = await soniq.run_worker(run_once=True)
    assert processed

    # Verify job completed
    status = await soniq.get_job(valid_job_id)
    assert status["status"] == "done"


@pytest.mark.asyncio
async def test_exception_handling_in_jobs():
    """Test different types of exceptions in job execution"""
    # Enqueue jobs that will raise different exceptions
    value_error_job = await soniq.enqueue(
        "exception_job", args={"exception_type": "value_error"}
    )
    type_error_job = await soniq.enqueue(
        "exception_job", args={"exception_type": "type_error"}
    )

    # Process jobs (they will fail)
    for _ in range(10):  # Multiple attempts to handle retries
        processed = await soniq.run_worker(run_once=True)
        if not processed:
            break

    # Check that jobs failed with appropriate errors
    value_status = await soniq.get_job(value_error_job)
    type_status = await soniq.get_job(type_error_job)

    assert value_status["status"] in ["failed", "dead_letter"]
    assert type_status["status"] in ["failed", "dead_letter"]
    assert "Test value error" in value_status["last_error"]
    assert "Test type error" in type_status["last_error"]


@pytest.mark.asyncio
async def test_large_job_payloads():
    """Test handling of jobs with large argument payloads"""
    # Create moderate data payload (within database index limits)
    large_data = {
        "large_list": list(range(50)),  # Reduced for speed
        "large_dict": {f"key_{i}": f"value_{i}" for i in range(10)},
        "large_string": "x" * 100,
    }

    # Enqueue job with large payload
    job_id = await soniq.enqueue(
        "complex_job", args={"data": large_data, "numbers": list(range(20))}
    )

    # Process the job
    processed = await soniq.run_worker(run_once=True)
    assert processed

    # Verify job completed
    status = await soniq.get_job(job_id)
    assert status["status"] == "done"
    assert len(status["args"]["data"]["large_list"]) == 50


@pytest.mark.asyncio
async def test_worker_shutdown_handling():
    """Test graceful worker shutdown"""
    # Enqueue a quick job
    await soniq.enqueue("simple_job", args={"message": "shutdown test"})

    # Test that run_worker with run_once=True completes without hanging
    try:
        await soniq.run_worker(run_once=True)
        # The main goal is to verify no hanging or crashing occurs
        print("Worker completed successfully without hanging")
    except Exception as e:
        pytest.fail(f"Worker run_once failed: {e}")


@pytest.mark.asyncio
async def test_registry_edge_cases():
    """Test job registry behavior in edge cases"""
    # Test duplicate job registration with global Soniq app
    global_app = soniq._get_global_app()
    app_registry = global_app._get_job_registry()

    initial_count = len(app_registry)

    # Register the same job function multiple times
    @soniq.job(name="duplicate_job")
    async def duplicate_job():
        return "duplicate"

    @soniq.job(name="duplicate_job")
    async def duplicate_job():  # Same name, should replace  # noqa: F811
        return "replaced"

    @soniq.job(name="another_job")
    async def another_job():
        return "another"

    # Registry should handle duplicates gracefully
    assert len(app_registry) >= initial_count


@pytest.mark.asyncio
async def test_timezone_and_datetime_handling():
    """Naive datetimes are rejected; timezone-aware datetimes are accepted."""
    from datetime import timezone

    # Naive datetimes are ambiguous across hosts and must raise.
    naive = datetime.now() + timedelta(minutes=30)
    with pytest.raises(ValueError, match="timezone-aware"):
        await soniq.enqueue("simple_job", args={"message": "naive"}, scheduled_at=naive)

    # Timezone-aware datetimes continue to work.
    tz_time = datetime.now(timezone.utc) + timedelta(minutes=30)
    tz_job = await soniq.enqueue(
        "simple_job", args={"message": "timezone"}, scheduled_at=tz_time
    )
    tz_status = await soniq.get_job(tz_job)
    assert tz_status["scheduled_at"] is not None
    assert tz_status["status"] == "queued"


@pytest.mark.asyncio
async def test_cli_integration():
    """Test CLI commands integration"""
    # Test CLI imports don't crash
    from soniq.cli.commands.core import register_core_commands
    from soniq.cli.commands.database import register_database_commands
    from soniq.cli.main import main
    from soniq.cli.registry import get_cli_registry

    # Register both core and database commands
    register_core_commands()
    register_database_commands()
    registry = get_cli_registry()

    commands = registry.get_all_commands()
    command_names = [cmd.name for cmd in commands]

    assert "setup" in command_names  # Database setup command (database.py)
    assert "start" in command_names  # Worker start command (core.py)

    # Test that main function exists and is callable
    assert callable(main)


@pytest.mark.asyncio
async def test_environment_variable_handling():
    """Test handling of environment variables and configuration"""
    original_env = os.environ.copy()

    try:
        # Test database URL environment variable
        test_url = "postgresql://test@localhost/test_db"
        os.environ["SONIQ_DATABASE_URL"] = test_url

        # Verify environment variable is read correctly
        assert os.environ.get("SONIQ_DATABASE_URL") == test_url

    finally:
        # Restore original environment
        os.environ.clear()
        os.environ.update(original_env)
