"""
Structured Logging with Job Context.
Structured JSON logging, job-specific loggers, performance context.
"""

import asyncio
import json
import logging
import logging.handlers
import sys
import time
import traceback
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from contextvars import ContextVar
from pathlib import Path
import uuid

from elephantq.db.connection import get_pool


# Context variables for request tracking
job_context: ContextVar[Optional['JobContext']] = ContextVar('job_context', default=None)
request_id_context: ContextVar[Optional[str]] = ContextVar('request_id', default=None)


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
            timestamp=datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            level=record.levelname,
            message=record.getMessage(),
            logger_name=record.name,
            module=record.module,
            function=record.funcName,
            line_number=record.lineno,
            thread_id=record.thread,
            process_id=record.process,
            request_id=req_id,
            job_context=job_ctx.to_dict() if job_ctx else None
        )
        
        # Add exception information
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            exception_data = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "module": exc_type.__module__ if exc_type else None
            }
            
            if self.include_traceback and exc_traceback:
                exception_data["traceback"] = traceback.format_exception(
                    exc_type, exc_value, exc_traceback
                )
            
            log_data.exception = exception_data
        
        # Add extra fields from record
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 
                          'filename', 'module', 'lineno', 'funcName', 'created', 
                          'msecs', 'relativeCreated', 'thread', 'threadName',
                          'processName', 'process', 'exc_info', 'exc_text', 'stack_info']:
                extra_fields[key] = value
        
        if extra_fields:
            log_data.extra_fields = extra_fields
        
        # Performance metrics if available
        if hasattr(record, 'duration_ms'):
            log_data.performance = {
                "duration_ms": getattr(record, 'duration_ms'),
                "memory_usage_mb": getattr(record, 'memory_usage_mb', None),
                "cpu_usage_percent": getattr(record, 'cpu_usage_percent', None)
            }
        
        return json.dumps(asdict(log_data), default=str)


class DatabaseLogHandler(logging.Handler):
    """Log handler that stores logs in PostgreSQL"""
    
    def __init__(self, table_name: str = "elephantq_logs", batch_size: int = 100):
        super().__init__()
        self.table_name = table_name
        self.batch_size = batch_size
        self.log_buffer: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._background_task = None
        
    async def setup_database(self):
        """Create logs table if it doesn't exist"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    logger_name TEXT NOT NULL,
                    module TEXT,
                    function TEXT,
                    line_number INTEGER,
                    request_id TEXT,
                    job_id TEXT,
                    job_name TEXT,
                    queue TEXT,
                    extra_data JSONB,
                    exception_data JSONB,
                    performance_data JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_timestamp ON {self.table_name}(timestamp);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_job_id ON {self.table_name}(job_id);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_level ON {self.table_name}(level);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_request_id ON {self.table_name}(request_id);
            """)
    
    def emit(self, record: logging.LogRecord):
        """Add log record to buffer"""
        try:
            # Convert to structured format
            log_entry = self._format_log_entry(record)
            
            # Add to buffer (thread-safe)
            asyncio.create_task(self._add_to_buffer(log_entry))
            
        except Exception:
            self.handleError(record)
    
    async def _add_to_buffer(self, log_entry: Dict[str, Any]):
        """Add log entry to buffer and flush if needed"""
        async with self._lock:
            self.log_buffer.append(log_entry)
            
            if len(self.log_buffer) >= self.batch_size:
                await self._flush_buffer()
    
    async def _flush_buffer(self):
        """Flush log buffer to database"""
        if not self.log_buffer:
            return
            
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                # Prepare batch insert
                values = []
                for entry in self.log_buffer:
                    values.append((
                        entry['timestamp'],
                        entry['level'],
                        entry['message'],
                        entry['logger_name'],
                        entry.get('module'),
                        entry.get('function'),
                        entry.get('line_number'),
                        entry.get('request_id'),
                        entry.get('job_id'),
                        entry.get('job_name'),
                        entry.get('queue'),
                        json.dumps(entry.get('extra_data')) if entry.get('extra_data') else None,
                        json.dumps(entry.get('exception_data')) if entry.get('exception_data') else None,
                        json.dumps(entry.get('performance_data')) if entry.get('performance_data') else None
                    ))
                
                await conn.executemany(f"""
                    INSERT INTO {self.table_name} (
                        timestamp, level, message, logger_name, module, function, 
                        line_number, request_id, job_id, job_name, queue,
                        extra_data, exception_data, performance_data
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                """, values)
                
                self.log_buffer.clear()
                
        except Exception as e:
            # Fallback to console logging if database fails
            print(f"Failed to write logs to database: {e}", file=sys.stderr)
    
    def _format_log_entry(self, record: logging.LogRecord) -> Dict[str, Any]:
        """Format log record for database storage"""
        job_ctx = job_context.get()
        req_id = request_id_context.get()
        
        entry = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc),
            'level': record.levelname,
            'message': record.getMessage(),
            'logger_name': record.name,
            'module': record.module,
            'function': record.funcName,
            'line_number': record.lineno,
            'request_id': req_id
        }
        
        # Add job context
        if job_ctx:
            entry.update({
                'job_id': job_ctx.job_id,
                'job_name': job_ctx.job_name,
                'queue': job_ctx.queue
            })
        
        # Add exception data
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            entry['exception_data'] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "traceback": traceback.format_exception(exc_type, exc_value, exc_traceback)
            }
        
        # Add performance data
        if hasattr(record, 'duration_ms'):
            entry['performance_data'] = {
                "duration_ms": getattr(record, 'duration_ms'),
                "memory_usage_mb": getattr(record, 'memory_usage_mb', None),
                "cpu_usage_percent": getattr(record, 'cpu_usage_percent', None)
            }
        
        # Add extra fields
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 
                          'filename', 'module', 'lineno', 'funcName', 'created', 
                          'msecs', 'relativeCreated', 'thread', 'threadName',
                          'processName', 'process', 'exc_info', 'exc_text', 'stack_info']:
                extra_fields[key] = value
        
        if extra_fields:
            entry['extra_data'] = extra_fields
        
        return entry
    
    async def close(self):
        """Close handler and flush remaining logs"""
        async with self._lock:
            await self._flush_buffer()


class JobLogger:
    """Job-specific logger with context"""
    
    def __init__(self, job_id: str, job_name: str, queue: str, attempt: int, max_attempts: int):
        self.context = JobContext(
            job_id=job_id,
            job_name=job_name,
            queue=queue,
            attempt=attempt,
            max_attempts=max_attempts
        )
        self.logger = logging.getLogger(f"elephantq.job.{job_name}")
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
    
    def log_performance(self, duration_ms: float, memory_usage_mb: Optional[float] = None, 
                       cpu_usage_percent: Optional[float] = None, **kwargs):
        """Log performance metrics"""
        extra = {
            'duration_ms': duration_ms,
            'memory_usage_mb': memory_usage_mb,
            'cpu_usage_percent': cpu_usage_percent,
            **kwargs
        }
        self.logger.info(f"Job performance: {duration_ms:.2f}ms", extra=extra)
    
    def log_milestone(self, milestone: str, elapsed_ms: Optional[float] = None, **kwargs):
        """Log job milestone"""
        if elapsed_ms is None:
            elapsed_ms = (time.time() - self._start_time) * 1000
        
        extra = {'milestone': milestone, 'elapsed_ms': elapsed_ms, **kwargs}
        self.logger.info(f"Milestone: {milestone} (elapsed: {elapsed_ms:.2f}ms)", extra=extra)
    
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
        backup_count: int = 5
    ):
        """Setup production-grade logging configuration"""
        
        # Create root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper()))
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Setup formatters
        if log_format.lower() == "json":
            formatter = JSONFormatter()
        else:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
                log_file,
                maxBytes=max_file_size,
                backupCount=backup_count
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        
        # Database handler
        if database_logging:
            db_handler = DatabaseLogHandler()
            asyncio.create_task(db_handler.setup_database())
            root_logger.addHandler(db_handler)
        
        # Set up specific loggers for different components
        LoggingConfig._setup_component_loggers()
    
    @staticmethod
    def _setup_component_loggers():
        """Setup loggers for different ElephantQ components"""
        
        # Job execution logger
        job_logger = logging.getLogger("elephantq.job")
        job_logger.setLevel(logging.INFO)
        
        # Queue logger
        queue_logger = logging.getLogger("elephantq.queue")
        queue_logger.setLevel(logging.INFO)
        
        # Metrics logger
        metrics_logger = logging.getLogger("elephantq.metrics")
        metrics_logger.setLevel(logging.INFO)
        
        # Webhook logger
        webhook_logger = logging.getLogger("elephantq.webhook")
        webhook_logger.setLevel(logging.INFO)
        
        # Database logger
        db_logger = logging.getLogger("elephantq.db")
        db_logger.setLevel(logging.WARNING)  # Only log warnings and errors


class LogAnalyzer:
    """Log analysis and reporting tools"""
    
    def __init__(self, table_name: str = "elephantq_logs"):
        self.table_name = table_name
    
    async def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get error summary for the specified time period"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Get error counts by job type
            error_counts = await conn.fetch(f"""
                SELECT 
                    job_name,
                    COUNT(*) as error_count,
                    array_agg(DISTINCT message) as error_messages
                FROM {self.table_name}
                WHERE level IN ('ERROR', 'CRITICAL')
                AND timestamp >= NOW() - INTERVAL '{hours} hours'
                AND job_name IS NOT NULL
                GROUP BY job_name
                ORDER BY error_count DESC
            """)
            
            # Get error trends
            error_trends = await conn.fetch(f"""
                SELECT 
                    DATE_TRUNC('hour', timestamp) as hour,
                    COUNT(*) as error_count
                FROM {self.table_name}
                WHERE level IN ('ERROR', 'CRITICAL')
                AND timestamp >= NOW() - INTERVAL '{hours} hours'
                GROUP BY hour
                ORDER BY hour
            """)
            
            return {
                "error_counts_by_job": [dict(row) for row in error_counts],
                "error_trends": [dict(row) for row in error_trends],
                "total_errors": sum(row['error_count'] for row in error_counts)
            }
    
    async def get_performance_logs(self, job_name: Optional[str] = None, hours: int = 24) -> List[Dict]:
        """Get performance logs with duration metrics"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            where_clause = "WHERE performance_data IS NOT NULL"
            params = []
            
            if job_name:
                where_clause += " AND job_name = $1"
                params.append(job_name)
                
            where_clause += f" AND timestamp >= NOW() - INTERVAL '{hours} hours'"
            
            performance_logs = await conn.fetch(f"""
                SELECT 
                    timestamp,
                    job_id,
                    job_name,
                    queue,
                    performance_data
                FROM {self.table_name}
                {where_clause}
                ORDER BY timestamp DESC
            """, *params)
            
            return [dict(row) for row in performance_logs]
    
    async def search_logs(self, query: str, job_id: Optional[str] = None, 
                         level: Optional[str] = None, hours: int = 24) -> List[Dict]:
        """Search logs with filters"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            where_conditions = ["timestamp >= NOW() - INTERVAL '%s hours'"]
            params = [hours]
            
            # Text search
            where_conditions.append("message ILIKE $%s")
            params.append(f"%{query}%")
            
            # Job ID filter
            if job_id:
                where_conditions.append("job_id = $%s")
                params.append(job_id)
            
            # Level filter
            if level:
                where_conditions.append("level = $%s")
                params.append(level.upper())
            
            # Update parameter placeholders
            for i, condition in enumerate(where_conditions[1:], 2):
                where_conditions[i] = condition.replace('%s', str(i))
            
            where_clause = " AND ".join(where_conditions)
            
            logs = await conn.fetch(f"""
                SELECT *
                FROM {self.table_name}
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT 1000
            """, *params)
            
            return [dict(row) for row in logs]


# Global instances
_db_handler = None
_log_analyzer = LogAnalyzer()


# Public API
def get_job_logger(job_id: str, job_name: str, queue: str, attempt: int, max_attempts: int) -> JobLogger:
    """Get a job-specific logger with context"""
    return JobLogger(job_id, job_name, queue, attempt, max_attempts)


def setup_logging(log_level: str = "INFO", log_format: str = "json", 
                 log_file: Optional[str] = None, database_logging: bool = True):
    """Setup structured logging configuration"""
    LoggingConfig.setup_enterprise_logging(
        log_level=log_level,
        log_format=log_format,
        log_file=log_file,
        database_logging=database_logging
    )


async def get_error_summary(hours: int = 24) -> Dict[str, Any]:
    """Get error summary from logs"""
    return await _log_analyzer.get_error_summary(hours)


async def get_performance_logs(job_name: Optional[str] = None, hours: int = 24) -> List[Dict]:
    """Get performance logs"""
    return await _log_analyzer.get_performance_logs(job_name, hours)


async def search_logs(query: str, job_id: Optional[str] = None, 
                     level: Optional[str] = None, hours: int = 24) -> List[Dict]:
    """Search logs with filters"""
    return await _log_analyzer.search_logs(query, job_id, level, hours)


def log_with_context(logger_name: str, level: str, message: str, **kwargs):
    """Log message with current context"""
    logger = logging.getLogger(logger_name)
    getattr(logger, level.lower())(message, extra=kwargs)
