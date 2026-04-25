"""
Structured Logging with Job Context.
Structured JSON logging, job-specific loggers, performance context.

The `LogSink` Protocol formalizes the contract Soniq's logging path
expects of its destination. It is intentionally a subset of the standard
`logging.Handler` API so any stdlib-compatible handler (file, stream,
SysLog, third-party Sentry/Datadog handlers) can be passed to
`Soniq(log_sink=...)` directly. The shipped default is `DatabaseLogHandler`,
which writes structured records into `soniq_logs`.
"""

import asyncio
import json
import logging
import logging.handlers
import re
import sys
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
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
    """A `logging.Handler`-compatible destination for Soniq log records.

    Any object that exposes `emit(record)` and an optional `close()`
    satisfies the Protocol. That includes the stdlib's `StreamHandler`,
    `RotatingFileHandler`, `SysLogHandler`, and the bundled
    `DatabaseLogHandler`.
    """

    def emit(self, record: logging.LogRecord) -> None: ...


_VALID_TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

# Context variables for request tracking
job_context: ContextVar[Optional["JobContext"]] = ContextVar(
    "job_context", default=None
)
request_id_context: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


@dataclass
class JobContext:
    """Job execution context for logging"""

    job_id: str
    job_name: str
    queue: str
    attempt: int
    max_attempts: int
    correlation_id: Optional[str] = None
    user_id: Optional[str] = None
    tags: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LogRecord:
    """Structured log record"""

    timestamp: str
    level: str
    message: str
    logger_name: str
    module: str
    function: str
    line_number: int
    thread_id: int
    process_id: int
    request_id: Optional[str] = None
    job_context: Optional[Dict[str, Any]] = None
    extra_fields: Optional[Dict[str, Any]] = None
    exception: Optional[Dict[str, Any]] = None
    performance: Optional[Dict[str, Any]] = None


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""

    def __init__(self, include_traceback: bool = True):
        super().__init__()
        self.include_traceback = include_traceback

    def format(self, record: logging.LogRecord) -> str:
        # Get context information
        job_ctx = job_context.get()
        req_id = request_id_context.get()

        # Base log record
        log_data = LogRecord(
            timestamp=datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            level=record.levelname,
            message=record.getMessage(),
            logger_name=record.name,
            module=record.module,
            function=record.funcName,
            line_number=record.lineno,
            thread_id=record.thread or 0,
            process_id=record.process or 0,
            request_id=req_id,
            job_context=job_ctx.to_dict() if job_ctx else None,
        )

        # Add exception information
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            exception_data: Dict[str, Any] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "module": exc_type.__module__ if exc_type else None,
            }

            if self.include_traceback and exc_traceback:
                exception_data["traceback"] = traceback.format_exception(
                    exc_type, exc_value, exc_traceback
                )

            log_data.exception = exception_data

        # Add extra fields from record
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "exc_info",
                "exc_text",
                "stack_info",
            ]:
                extra_fields[key] = value

        if extra_fields:
            log_data.extra_fields = extra_fields

        # Performance metrics if available
        if hasattr(record, "duration_ms"):
            log_data.performance = {
                "duration_ms": getattr(record, "duration_ms"),
                "memory_usage_mb": getattr(record, "memory_usage_mb", None),
                "cpu_usage_percent": getattr(record, "cpu_usage_percent", None),
            }

        return json.dumps(asdict(log_data), default=str)


_STOP_SENTINEL = object()


class DatabaseLogHandler(logging.Handler):
    """Log handler that stores logs in PostgreSQL.

    Uses a bounded asyncio.Queue plus a single consumer task. `emit()` is
    cheap (queue.put_nowait) and never spawns a fresh task per record;
    a queue-full condition degrades to a one-shot stderr warning rather
    than orphan tasks accumulating under high log volume.
    """

    def __init__(
        self,
        app: Optional["Soniq"] = None,
        *,
        table_name: str = "soniq_logs",
        batch_size: int = 100,
        queue_max: int = 10_000,
    ):
        super().__init__()
        if not _VALID_TABLE_NAME.match(table_name):
            raise ValueError(f"Invalid table name: {table_name!r}")
        self._app = app
        self.table_name = table_name
        self.batch_size = batch_size
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_max)
        self._consumer_task: Optional[asyncio.Task] = None
        self._dropped_warned = False

    @asynccontextmanager
    async def _acquire(self) -> AsyncIterator[Any]:
        """Borrow an asyncpg connection for log writes.

        Falls back to the global Soniq app when no instance was wired in.
        Tests construct the handler without an app and rely on this fallback;
        production code passes an explicit ``Soniq``.
        """
        if self._app is not None:
            await self._app._ensure_initialized()
            async with self._app.backend.acquire() as conn:
                yield conn
            return
        import soniq

        app = soniq._get_global_app()
        await app._ensure_initialized()
        async with app.backend.acquire() as conn:
            yield conn

    async def setup_database(self):
        """Tables are created by migrations. No-op."""
        pass

    def emit(self, record: logging.LogRecord):
        """Format the record and enqueue it for the consumer task."""
        try:
            log_entry = self._format_log_entry(record)
        except Exception:
            self.handleError(record)
            return

        self._ensure_consumer()
        try:
            self._queue.put_nowait(log_entry)
        except asyncio.QueueFull:
            if not self._dropped_warned:
                self._dropped_warned = True
                sys.stderr.write(
                    "Soniq: log queue is full; dropping records "
                    "(message shown once per handler instance)\n"
                )

    def _ensure_consumer(self) -> None:
        """Lazily start the consumer task on the running event loop."""
        if self._consumer_task is not None and not self._consumer_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop. emit() will keep enqueuing; the consumer
            # starts on the next emit() that runs inside a loop.
            return
        self._consumer_task = loop.create_task(self._consume())

    async def _consume(self) -> None:
        """Drain the queue in batches until the stop sentinel arrives."""
        batch: List[Dict[str, Any]] = []
        while True:
            item = await self._queue.get()
            if item is _STOP_SENTINEL:
                if batch:
                    await self._flush_batch(batch)
                return
            batch.append(item)
            # Greedy drain up to batch_size without blocking.
            while len(batch) < self.batch_size and not self._queue.empty():
                next_item = self._queue.get_nowait()
                if next_item is _STOP_SENTINEL:
                    await self._flush_batch(batch)
                    return
                batch.append(next_item)
            if len(batch) >= self.batch_size:
                await self._flush_batch(batch)
                batch = []

    async def _flush_batch(self, batch):
        """Write a batch of log entries to the database."""
        if not batch:
            return

        try:
            async with self._acquire() as conn:
                values = []
                for entry in batch:
                    # JSONB columns: pass dict directly, the pool codec
                    # serializes (no manual json.dumps needed).
                    values.append(
                        (
                            entry["timestamp"],
                            entry["level"],
                            entry["message"],
                            entry["logger_name"],
                            entry.get("module"),
                            entry.get("function"),
                            entry.get("line_number"),
                            entry.get("request_id"),
                            entry.get("job_id"),
                            entry.get("job_name"),
                            entry.get("queue"),
                            entry.get("extra_data"),
                            entry.get("exception_data"),
                            entry.get("performance_data"),
                        )
                    )

                await conn.executemany(
                    f"""
                    INSERT INTO {self.table_name} (
                        timestamp, level, message, logger_name, module, function,
                        line_number, request_id, job_id, job_name, queue,
                        extra_data, exception_data, performance_data
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                """,
                    values,
                )

        except Exception as e:
            # Fallback to console logging if database fails
            sys.stderr.write(f"Soniq: Failed to write logs to database: {e}\n")

    def _format_log_entry(self, record: logging.LogRecord) -> Dict[str, Any]:
        """Format log record for database storage"""
        job_ctx = job_context.get()
        req_id = request_id_context.get()

        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger_name": record.name,
            "module": record.module,
            "function": record.funcName,
            "line_number": record.lineno,
            "request_id": req_id,
        }

        # Add job context
        if job_ctx:
            entry.update(
                {
                    "job_id": job_ctx.job_id,
                    "job_name": job_ctx.job_name,
                    "queue": job_ctx.queue,
                }
            )

        # Add exception data
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            entry["exception_data"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "traceback": traceback.format_exception(
                    exc_type, exc_value, exc_traceback
                ),
            }

        # Add performance data
        if hasattr(record, "duration_ms"):
            entry["performance_data"] = {
                "duration_ms": getattr(record, "duration_ms"),
                "memory_usage_mb": getattr(record, "memory_usage_mb", None),
                "cpu_usage_percent": getattr(record, "cpu_usage_percent", None),
            }

        # Add extra fields
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "exc_info",
                "exc_text",
                "stack_info",
            ]:
                extra_fields[key] = value

        if extra_fields:
            entry["extra_data"] = extra_fields

        return entry

    async def close(self):
        """Stop the consumer task and flush any remaining records."""
        if self._consumer_task is None:
            return
        await self._queue.put(_STOP_SENTINEL)
        try:
            await self._consumer_task
        except asyncio.CancelledError:
            pass
        finally:
            self._consumer_task = None


class JobLogger:
    """Job-specific logger with context"""

    def __init__(
        self, job_id: str, job_name: str, queue: str, attempt: int, max_attempts: int
    ):
        self.context = JobContext(
            job_id=job_id,
            job_name=job_name,
            queue=queue,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        self.logger = logging.getLogger(f"soniq.job.{job_name}")
        self._start_time = time.time()

    def __enter__(self):
        """Set job context for logging"""
        self.token = job_context.set(self.context)
        self.request_token = request_id_context.set(str(uuid.uuid4()))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clear job context"""
        job_context.reset(self.token)
        request_id_context.reset(self.request_token)

    def info(self, message: str, **kwargs):
        """Log info message with job context"""
        self.logger.info(message, extra=kwargs)

    def warning(self, message: str, **kwargs):
        """Log warning message with job context"""
        self.logger.warning(message, extra=kwargs)

    def error(self, message: str, **kwargs):
        """Log error message with job context"""
        self.logger.error(message, extra=kwargs)

    def exception(self, message: str, **kwargs):
        """Log exception with job context"""
        self.logger.exception(message, extra=kwargs)

    def debug(self, message: str, **kwargs):
        """Log debug message with job context"""
        self.logger.debug(message, extra=kwargs)

    def log_performance(
        self,
        duration_ms: float,
        memory_usage_mb: Optional[float] = None,
        cpu_usage_percent: Optional[float] = None,
        **kwargs,
    ):
        """Log performance metrics"""
        extra = {
            "duration_ms": duration_ms,
            "memory_usage_mb": memory_usage_mb,
            "cpu_usage_percent": cpu_usage_percent,
            **kwargs,
        }
        self.logger.info(f"Job performance: {duration_ms:.2f}ms", extra=extra)

    def log_milestone(
        self, milestone: str, elapsed_ms: Optional[float] = None, **kwargs
    ):
        """Log job milestone"""
        if elapsed_ms is None:
            elapsed_ms = (time.time() - self._start_time) * 1000

        extra = {"milestone": milestone, "elapsed_ms": elapsed_ms, **kwargs}
        self.logger.info(
            f"Milestone: {milestone} (elapsed: {elapsed_ms:.2f}ms)", extra=extra
        )

    def add_tag(self, key: str, value: str):
        """Add tag to job context"""
        if self.context.tags is None:
            self.context.tags = {}
        self.context.tags[key] = value

    def set_correlation_id(self, correlation_id: str):
        """Set correlation ID for tracking across services"""
        self.context.correlation_id = correlation_id

    def set_user_id(self, user_id: str):
        """Set user ID for audit logging"""
        self.context.user_id = user_id


class LoggingConfig:
    """Centralized logging configuration"""

    @staticmethod
    def setup_enterprise_logging(
        log_level: str = "INFO",
        log_format: str = "json",
        log_file: Optional[str] = None,
        database_logging: bool = True,
        console_logging: bool = True,
        max_file_size: int = 100 * 1024 * 1024,  # 100MB
        backup_count: int = 5,
    ):
        """Setup production-grade logging configuration"""

        # Create root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper()))

        # Clear existing handlers
        root_logger.handlers.clear()

        # Setup formatters
        formatter: logging.Formatter
        if log_format.lower() == "json":
            formatter = JSONFormatter()
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )

        # Console handler
        if console_logging:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        # File handler with rotation
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=max_file_size, backupCount=backup_count
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

        # Database handler
        if database_logging:
            db_handler = DatabaseLogHandler()
            root_logger.addHandler(db_handler)

        # Set up specific loggers for different components
        LoggingConfig._setup_component_loggers()

    @staticmethod
    def _setup_component_loggers():
        """Setup loggers for different Soniq components"""

        # Job execution logger
        job_logger = logging.getLogger("soniq.job")
        job_logger.setLevel(logging.INFO)

        # Queue logger
        queue_logger = logging.getLogger("soniq.queue")
        queue_logger.setLevel(logging.INFO)

        # Metrics logger
        metrics_logger = logging.getLogger("soniq.metrics")
        metrics_logger.setLevel(logging.INFO)

        # Webhook logger
        webhook_logger = logging.getLogger("soniq.webhook")
        webhook_logger.setLevel(logging.INFO)

        # Database logger
        db_logger = logging.getLogger("soniq.db")
        db_logger.setLevel(logging.WARNING)  # Only log warnings and errors


class LogAnalyzer:
    """Log analysis and reporting tools.

    Constructed against a ``Soniq`` instance for pool resolution. The
    ``app`` parameter defaults to ``None`` so the legacy module-level
    helpers can keep working through the global app; library code should
    pass the instance.
    """

    def __init__(
        self,
        app: Optional["Soniq"] = None,
        *,
        table_name: str = "soniq_logs",
    ):
        if not _VALID_TABLE_NAME.match(table_name):
            raise ValueError(f"Invalid table name: {table_name!r}")
        self._app = app
        self.table_name = table_name

    @asynccontextmanager
    async def _acquire(self) -> AsyncIterator[Any]:
        if self._app is not None:
            await self._app._ensure_initialized()
            async with self._app.backend.acquire() as conn:
                yield conn
            return
        import soniq

        app = soniq._get_global_app()
        await app._ensure_initialized()
        async with app.backend.acquire() as conn:
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


def _service() -> LogService:
    """Build a service against the global Soniq app on demand."""
    import soniq

    return LogService(soniq._get_global_app())


# Public API
def get_job_logger(
    job_id: str, job_name: str, queue: str, attempt: int, max_attempts: int
) -> JobLogger:
    """Get a job-specific logger with context"""
    return JobLogger(job_id, job_name, queue, attempt, max_attempts)


def setup_logging(
    log_level: str = "INFO",
    log_format: str = "json",
    log_file: Optional[str] = None,
    database_logging: bool = True,
):
    """Setup structured logging configuration"""
    LoggingConfig.setup_enterprise_logging(
        log_level=log_level,
        log_format=log_format,
        log_file=log_file,
        database_logging=database_logging,
    )


async def get_error_summary(hours: int = 24) -> Dict[str, Any]:
    """Get error summary from logs"""
    return await _service().get_error_summary(hours)


async def get_performance_logs(
    job_name: Optional[str] = None, hours: int = 24
) -> List[Dict]:
    """Get performance logs"""
    return await _service().get_performance_logs(job_name, hours)


async def search_logs(
    query: str,
    job_id: Optional[str] = None,
    level: Optional[str] = None,
    hours: int = 24,
) -> List[Dict]:
    """Search logs with filters"""
    return await _service().search_logs(query, job_id, level, hours)


def log_with_context(logger_name: str, level: str, message: str, **kwargs):
    """Log message with current context"""
    logger = logging.getLogger(logger_name)
    getattr(logger, level.lower())(message, extra=kwargs)
