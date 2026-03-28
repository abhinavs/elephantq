"""
Tests for logging.py structures and formatter.

Covers: JSONFormatter.format, LogRecord, JobContext dataclass.
"""

import json
import logging
import os

import pytest

pytest.importorskip("structlog")

os.environ.setdefault("ELEPHANTQ_LOGGING_ENABLED", "true")

from elephantq.features.logging import (  # noqa: E402
    JobContext,
    JSONFormatter,
    LogRecord,
)


class TestJobContext:
    def test_to_dict(self):
        ctx = JobContext(
            job_id="j1",
            job_name="mod.task",
            queue="default",
            attempt=1,
            max_attempts=3,
        )
        d = ctx.to_dict()
        assert d["job_id"] == "j1"
        assert d["job_name"] == "mod.task"
        assert d["queue"] == "default"


class TestLogRecord:
    def test_creation(self):
        record = LogRecord(
            timestamp="2025-01-01T00:00:00",
            level="INFO",
            message="Job started",
            logger_name="elephantq.test",
            module="test_mod",
            function="test_fn",
            line_number=42,
            thread_id=1,
            process_id=100,
        )
        assert record.level == "INFO"
        assert record.message == "Job started"
        assert record.module == "test_mod"


class TestJSONFormatter:
    def test_format_produces_valid_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="elephantq.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "test message"
        assert parsed["level"] == "INFO"
        assert "timestamp" in parsed

    def test_format_with_exception(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="elephantq.test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error occurred",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "ERROR"
        # Exception info should appear somewhere in the output
        assert "exception" in parsed or "traceback" in parsed or "ValueError" in output
