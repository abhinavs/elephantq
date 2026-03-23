"""
Tests that invalid dependency UUIDs raise ValueError instead of being silently skipped.

Written to verify LOW-01.
"""

import os

import pytest

os.environ.setdefault("ELEPHANTQ_DEPENDENCIES_ENABLED", "true")


class TestDependencyValidation:
    @pytest.mark.asyncio
    async def test_invalid_uuid_raises_valueerror(self):
        from elephantq.features.dependencies import store_job_dependencies
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.transaction = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=None),
        ))
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        ))

        with patch("elephantq.features.dependencies.get_context_pool", return_value=mock_pool):
            with pytest.raises(ValueError, match="Invalid dependency job ID"):
                await store_job_dependencies(
                    "550e8400-e29b-41d4-a716-446655440000",
                    ["not-a-uuid"],
                )
