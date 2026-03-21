import asyncio
import logging
import os
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCreateJobRecordUsesParameterizedNotify:
    """Verify _create_job_record sends pg_notify via parameterized SELECT, not an f-string NOTIFY."""

    @pytest.mark.asyncio
    async def test_non_unique_job_uses_pg_notify_params(self):
        from elephantq.core.queue import _create_job_record

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="INSERT 0 1")

        job_id = str(uuid.uuid4())
        job_meta = {"retries": 3}

        result = await _create_job_record(
            conn,
            job_id=job_id,
            job_name="mymodule.my_task",
            job_meta=job_meta,
            args_json='{"x": 1}',
            args_hash=None,
            final_priority=10,
            final_queue="default",
            final_unique=False,
            scheduled_at=None,
        )

        assert result == job_id

        # The second execute call should be the pg_notify
        notify_call = conn.execute.call_args_list[-1]
        sql = notify_call.args[0]
        assert "pg_notify" in sql
        assert "$1" in sql and "$2" in sql
        # Should NOT contain NOTIFY as a raw SQL command
        assert "NOTIFY" not in sql.upper().replace("PG_NOTIFY", "")
        # Verify the channel and queue were passed as parameters
        assert notify_call.args[1] == "elephantq_new_job"
        assert notify_call.args[2] == "default"

    @pytest.mark.asyncio
    async def test_unique_job_uses_pg_notify_params(self):
        from elephantq.core.queue import _create_job_record

        conn = AsyncMock()
        row = {"id": uuid.uuid4()}
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute = AsyncMock(return_value="SELECT 1")

        job_id = str(uuid.uuid4())
        job_meta = {"retries": 2}

        await _create_job_record(
            conn,
            job_id=job_id,
            job_name="mymodule.unique_task",
            job_meta=job_meta,
            args_json='{"y": 2}',
            args_hash="abc123",
            final_priority=5,
            final_queue="critical",
            final_unique=True,
            scheduled_at=None,
        )

        # The execute call after fetchrow should be pg_notify
        notify_call = conn.execute.call_args_list[-1]
        sql = notify_call.args[0]
        assert "pg_notify($1, $2)" in sql


class TestCleanupStaleWorkersParameterized:
    """Verify cleanup_stale_workers uses parameterized INTERVAL."""

    @pytest.mark.asyncio
    async def test_interval_is_parameterized(self):
        from contextlib import asynccontextmanager

        from elephantq.core.heartbeat import cleanup_stale_workers

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")

        @asynccontextmanager
        async def _acquire():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.acquire = _acquire

        await cleanup_stale_workers(mock_pool, stale_threshold_seconds=120)

        fetch_call = mock_conn.fetch.call_args
        sql = fetch_call.args[0]
        # Should use ($1 || ' seconds')::INTERVAL pattern, not an f-string
        assert "($1 || ' seconds')::INTERVAL" in sql
        assert fetch_call.args[1] == "120"


class TestGetDeliveryStatsParameterized:
    """Verify get_delivery_stats uses parameterized INTERVAL for hours."""

    @pytest.mark.asyncio
    async def test_interval_hours_is_parameterized(self, monkeypatch):
        from contextlib import asynccontextmanager

        from elephantq.features import webhooks

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(
            return_value={
                "total_deliveries": 0,
                "successful_deliveries": 0,
                "failed_deliveries": 0,
                "pending_deliveries": 0,
                "avg_attempts": 0,
            }
        )
        mock_conn.fetch = AsyncMock(return_value=[])

        @asynccontextmanager
        async def _acquire():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.acquire = _acquire

        monkeypatch.setattr(webhooks, "get_pool", AsyncMock(return_value=mock_pool))

        manager = webhooks.WebhookManager()
        await manager.get_delivery_stats(hours=48)

        fetchrow_call = mock_conn.fetchrow.call_args
        sql = fetchrow_call.args[0]
        assert "($1 || ' hours')::INTERVAL" in sql
        assert fetchrow_call.args[1] == "48"


class TestSecretKeyNotLogged:
    """Verify that the auto-generated secret key value does not appear in log output."""

    def test_generated_key_not_in_logs(self, caplog, monkeypatch):
        # Remove any existing key so the manager generates one
        monkeypatch.delenv("ELEPHANTQ_SECRET_KEY", raising=False)

        # Reset the global manager so a fresh one is created
        import elephantq.features.signing as signing_mod

        signing_mod._secret_manager = None

        with caplog.at_level(logging.DEBUG, logger="elephantq.features.signing"):
            manager = signing_mod.SecretManager()

        # The warning message should not contain the actual key
        generated_key = manager._secret_key
        for record in caplog.records:
            assert generated_key not in record.message, (
                "The generated secret key value must not appear in log messages"
            )


class TestRowsAffectedHelper:
    """Verify _rows_affected correctly parses asyncpg status strings."""

    @pytest.mark.parametrize(
        "status_string,expected",
        [
            ("UPDATE 3", 3),
            ("DELETE 0", 0),
            ("INSERT 0 1", 1),
            ("", 0),
        ],
    )
    def test_rows_affected(self, status_string, expected):
        from elephantq.core.queue import _rows_affected

        assert _rows_affected(status_string) == expected
