"""
Structured logging surface for Soniq.

Two pieces of public API live here:

- ``LogSink`` Protocol - the plugin extension point. Any object exposing
  ``emit(record)`` (the stdlib ``logging.Handler`` shape) satisfies it,
  so users can pass ``StreamHandler``, ``RotatingFileHandler``,
  ``SysLogHandler``, or a third-party Sentry / Datadog handler directly
  to ``Soniq(log_sink=...)``.
- ``LogService`` / ``LogAnalyzer`` - operator-facing read paths over the
  ``soniq_logs`` table populated by structured-logging consumers.
"""

import logging
import re
from contextlib import asynccontextmanager
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:
    from soniq.app import Soniq


@runtime_checkable
class LogSink(Protocol):
    """A ``logging.Handler``-compatible destination for Soniq log records.

    Any object that exposes ``emit(record)`` satisfies the Protocol; that
    includes the stdlib's ``StreamHandler``, ``RotatingFileHandler``,
    ``SysLogHandler``, and most third-party handlers.
    """

    def emit(self, record: logging.LogRecord) -> None: ...


_VALID_TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


class LogAnalyzer:
    """Log analysis and reporting tools.

    Constructed against a ``Soniq`` instance for pool resolution.
    """

    def __init__(
        self,
        app: "Soniq",
        *,
        table_name: str = "soniq_logs",
    ):
        if not _VALID_TABLE_NAME.match(table_name):
            raise ValueError(f"Invalid table name: {table_name!r}")
        self._app = app
        self.table_name = table_name

    @asynccontextmanager
    async def _acquire(self) -> AsyncIterator[Any]:
        await self._app.ensure_initialized()
        async with self._app.backend.acquire() as conn:
            yield conn

    async def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get error summary for the specified time period"""
        async with self._acquire() as conn:
            error_counts = await conn.fetch(
                f"""
                SELECT
                    job_name,
                    COUNT(*) as error_count,
                    array_agg(DISTINCT message) as error_messages
                FROM {self.table_name}
                WHERE level IN ('ERROR', 'CRITICAL')
                AND timestamp >= NOW() - ($1 || ' hours')::INTERVAL
                AND job_name IS NOT NULL
                GROUP BY job_name
                ORDER BY error_count DESC
            """,
                str(hours),
            )

            error_trends = await conn.fetch(
                f"""
                SELECT
                    DATE_TRUNC('hour', timestamp) as hour,
                    COUNT(*) as error_count
                FROM {self.table_name}
                WHERE level IN ('ERROR', 'CRITICAL')
                AND timestamp >= NOW() - ($1 || ' hours')::INTERVAL
                GROUP BY hour
                ORDER BY hour
            """,
                str(hours),
            )

            return {
                "error_counts_by_job": [dict(row) for row in error_counts],
                "error_trends": [dict(row) for row in error_trends],
                "total_errors": sum(row["error_count"] for row in error_counts),
            }

    async def get_performance_logs(
        self, job_name: Optional[str] = None, hours: int = 24
    ) -> List[Dict]:
        """Get performance logs with duration metrics"""
        async with self._acquire() as conn:
            conditions = [
                "performance_data IS NOT NULL",
                "timestamp >= NOW() - ($1 || ' hours')::INTERVAL",
            ]
            params: list = [str(hours)]
            param_idx = 2

            if job_name:
                conditions.append(f"job_name = ${param_idx}")
                params.append(job_name)
                param_idx += 1

            where_clause = " AND ".join(conditions)

            performance_logs = await conn.fetch(
                f"""
                SELECT
                    timestamp, job_id, job_name, queue, performance_data
                FROM {self.table_name}
                WHERE {where_clause}
                ORDER BY timestamp DESC
            """,
                *params,
            )

            return [dict(row) for row in performance_logs]

    async def search_logs(
        self,
        query: str,
        job_id: Optional[str] = None,
        level: Optional[str] = None,
        hours: int = 24,
    ) -> List[Dict]:
        """Search logs with filters"""
        async with self._acquire() as conn:
            conditions = ["timestamp >= NOW() - ($1 || ' hours')::INTERVAL"]
            params: list = [str(hours)]
            param_idx = 2

            conditions.append(f"message ILIKE ${param_idx}")
            params.append(f"%{query}%")
            param_idx += 1

            if job_id:
                conditions.append(f"job_id = ${param_idx}")
                params.append(job_id)
                param_idx += 1

            if level:
                conditions.append(f"level = ${param_idx}")
                params.append(level.upper())
                param_idx += 1

            where_clause = " AND ".join(conditions)

            logs = await conn.fetch(
                f"""
                SELECT *
                FROM {self.table_name}
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT 1000
            """,
                *params,
            )

            return [dict(row) for row in logs]


class LogService:
    """High-level log query service bound to a Soniq instance.

    Wraps a per-app ``LogAnalyzer``. The ``LogSink`` Protocol is the
    extension point for plugging in non-database log destinations; this
    service is purely about *reading* the structured log table.
    """

    def __init__(self, app: "Soniq"):
        self._app = app
        self.analyzer = LogAnalyzer(app)

    async def setup(self) -> int:
        """No-op in 0.0.3+: log tables are part of the core schema and are
        applied by ``Soniq.setup()`` (migration ``0006_logs.sql``).

        Kept on the surface to avoid AttributeError for prior callers.
        Returns 0 (no migrations applied here).
        """
        await self._app.ensure_initialized()
        return 0

    async def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        return await self.analyzer.get_error_summary(hours)

    async def get_performance_logs(
        self, job_name: Optional[str] = None, hours: int = 24
    ) -> List[Dict]:
        return await self.analyzer.get_performance_logs(job_name, hours)

    async def search_logs(
        self,
        query: str,
        job_id: Optional[str] = None,
        level: Optional[str] = None,
        hours: int = 24,
    ) -> List[Dict]:
        return await self.analyzer.search_logs(query, job_id, level, hours)
