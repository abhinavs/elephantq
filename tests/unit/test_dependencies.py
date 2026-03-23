"""
Tests for elephantq.features.dependencies — DDL safety and input validation.
"""

import inspect
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ELEPHANTQ_DEPENDENCIES_ENABLED", "true")


class TestNoInlineDDL:
    """Verify dependencies.py doesn't run CREATE TABLE at runtime."""

    def test_store_dependencies_no_create_table(self):
        from elephantq.features.dependencies import store_job_dependencies

        source = inspect.getsource(store_job_dependencies)
        assert "CREATE TABLE" not in source, (
            "store_job_dependencies() still contains inline CREATE TABLE DDL"
        )

    def test_store_dependencies_with_conn_no_create_table(self):
        from elephantq.features.dependencies import _store_dependencies_with_conn

        source = inspect.getsource(_store_dependencies_with_conn)
        assert "CREATE TABLE" not in source, (
            "_store_dependencies_with_conn() still contains inline CREATE TABLE DDL"
        )


class TestDependencyValidation:
    @pytest.mark.asyncio
    async def test_invalid_uuid_raises_valueerror(self):
        from elephantq.features.dependencies import store_job_dependencies

        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.transaction = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=None),
            )
        )
        mock_pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch(
            "elephantq.features.dependencies.get_context_pool",
            return_value=mock_pool,
        ):
            with patch("elephantq.features.dependencies.require_feature"):
                with pytest.raises(ValueError, match="Invalid dependency job ID"):
                    await store_job_dependencies(
                        "550e8400-e29b-41d4-a716-446655440000",
                        ["not-a-uuid"],
                    )
