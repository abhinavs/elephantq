"""
Test compliance with Soniq feature specification
"""

import os
import uuid

import pytest

import soniq
from tests.db_utils import TEST_DATABASE_URL

# Use test database
os.environ["SONIQ_DATABASE_URL"] = TEST_DATABASE_URL


# Test job definitions
@soniq.job(name="basic_job", retries=3)
async def basic_job(message: str):
    return f"Basic: {message}"


@soniq.job(name="advanced_job", retries=2, priority=50, queue="test")
async def advanced_job(message: str, count: int):
    return f"Advanced: {message} x{count}"


@pytest.mark.asyncio
async def test_free_features_compliance():
    """Test all Free Features (Phase 1 - MVP) compliance"""

    # ✅ PostgreSQL-based job persistence (JSON payload)
    job_id = await soniq.enqueue("basic_job", args={"message": "test persistence"})

    # Use global app pool for consistency
    global_app = soniq.get_global_app()
    app_pool = await global_app._get_pool()

    async with app_pool.acquire() as conn:
        job_record = await conn.fetchrow(
            "SELECT * FROM soniq_jobs WHERE id = $1", uuid.UUID(job_id)
        )
        assert job_record is not None
        assert job_record["job_name"] == "basic_job"
        assert job_record["args"] == {"message": "test persistence"}

    # ✅ Job processing with retry mechanism
    processed = await soniq.run_worker(run_once=True)
    assert processed

    # Verify job completed
    async with app_pool.acquire() as conn:
        job_record = await conn.fetchrow(
            "SELECT * FROM soniq_jobs WHERE id = $1", uuid.UUID(job_id)
        )
        assert job_record["status"] == "done"
        assert job_record["max_attempts"] == 4  # retries=3 -> max_attempts=4

    # ✅ Internal DB connection pooling
    pool = await soniq.get_global_app()._get_pool()
    assert pool is not None


@pytest.mark.asyncio
async def test_pro_features_compliance():
    """Test optional features (Phase 2) compliance"""

    # ✅ Priority queues (numeric)
    await soniq.enqueue(
        "advanced_job", args={"message": "high priority", "count": 1}, priority=10
    )

    await soniq.enqueue(
        "advanced_job", args={"message": "low priority", "count": 1}, priority=100
    )

    # Verify priority ordering in database
    global_app = soniq.get_global_app()
    app_pool = await global_app._get_pool()

    async with app_pool.acquire() as conn:
        jobs = await conn.fetch(
            "SELECT priority FROM soniq_jobs WHERE status = 'queued' ORDER BY priority ASC"
        )
        priorities = [job["priority"] for job in jobs]
        assert priorities == [10, 100]  # High priority first

    # ✅ Scheduling API exists
    assert hasattr(soniq, "schedule")


@pytest.mark.asyncio
async def test_dsl_usage_examples_compliance():
    """Test that DSL usage examples from spec work exactly as documented"""

    # Spec Example 1: Registering a Job
    @soniq.job(name="send_email", retries=3)
    async def send_email(to: str, subject: str, body: str):
        return f"Email to {to}: {subject}"

    # Spec Example 2: Enqueuing a Job
    job_id = await soniq.enqueue(
        "send_email",
        args={"to": "user@example.com", "subject": "Hello", "body": "Test message"},
    )

    # Verify job was enqueued
    status = await soniq.get_job(job_id)
    assert status is not None
    assert status["status"] == "queued"

    # Spec Example 3: Scheduling a Job (basic)
    from datetime import datetime, timedelta, timezone

    future_time = datetime.now(timezone.utc) + timedelta(minutes=30)

    scheduled_job_id = await soniq.schedule(
        "send_email",
        args={
            "to": "user@example.com",
            "subject": "Scheduled",
            "body": "Scheduled message",
        },
        run_at=future_time,
    )

    # Verify job was scheduled
    scheduled_status = await soniq.get_job(scheduled_job_id)
    assert scheduled_status is not None
    assert scheduled_status["status"] == "queued"
    assert scheduled_status["scheduled_at"] is not None


@pytest.mark.asyncio
async def test_cli_commands_compliance():
    """Top-level CLI parser must expose the core subcommands per spec."""
    import argparse

    from soniq.cli.main import build_parser, main

    assert main is not None

    parser = build_parser()
    sub_action = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    command_names = set(sub_action.choices.keys())

    assert "setup" in command_names
    assert "start" in command_names

    start_help = sub_action.choices["start"].format_help()
    assert "worker" in start_help.lower()


@pytest.mark.asyncio
async def test_database_schema_compliance():
    """Test database schema matches specification"""

    # Use global app pool for consistency
    global_app = soniq.get_global_app()
    app_pool = await global_app._get_pool()

    async with app_pool.acquire() as conn:
        # Check table exists
        table_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'soniq_jobs'
            )
            """
        )
        assert table_exists

        # Check required columns exist
        columns = await conn.fetch(
            """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'soniq_jobs'
            """
        )

        column_names = {col["column_name"] for col in columns}
        required_columns = {
            "id",
            "job_name",
            "args",
            "status",
            "queue",
            "priority",
            "attempts",
            "max_attempts",
            "scheduled_at",
            "last_error",
            "created_at",
            "updated_at",
        }

        assert required_columns.issubset(
            column_names
        ), f"Missing columns: {required_columns - column_names}"


@pytest.mark.asyncio
async def test_project_structure_compliance():
    """Test project structure matches specification"""
    # Check main directories exist
    base_path = os.path.dirname(soniq.__file__)

    required_dirs = [
        "core",  # Task decorator, queue logic, processor loop
        "cli",  # CLI commands
        "db",  # Database utilities
    ]

    for dir_name in required_dirs:
        dir_path = os.path.join(base_path, dir_name)
        assert os.path.isdir(dir_path), f"Required directory missing: {dir_name}"

    # Check key modules exist
    assert hasattr(soniq, "job")
    assert hasattr(soniq, "enqueue")
    assert hasattr(soniq, "schedule")
    assert hasattr(soniq, "run_worker")
    assert hasattr(soniq, "get_job")
    assert hasattr(soniq, "cancel_job")
    assert hasattr(soniq, "retry_job")
    assert hasattr(soniq, "delete_job")
    assert hasattr(soniq, "list_jobs")
    assert hasattr(soniq, "get_queue_stats")
