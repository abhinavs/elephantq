"""
Extended tests for logging.py — JobLogger and setup.
"""

import os

import pytest

pytest.importorskip("structlog")

os.environ.setdefault("ELEPHANTQ_LOGGING_ENABLED", "true")

from elephantq.features.logging import JobContext, JobLogger  # noqa: E402


class TestJobLogger:
    def test_creation(self):
        logger = JobLogger(
            job_id="j1",
            job_name="mod.task",
            queue="default",
            attempt=1,
            max_attempts=3,
        )
        assert logger.context.job_id == "j1"

    def test_info_does_not_raise(self):
        logger = JobLogger(
            job_id="j1",
            job_name="mod.task",
            queue="default",
            attempt=1,
            max_attempts=3,
        )
        logger.info("test message")

    def test_warning_does_not_raise(self):
        logger = JobLogger(
            job_id="j1",
            job_name="mod.task",
            queue="default",
            attempt=1,
            max_attempts=3,
        )
        logger.warning("test warning")

    def test_error_does_not_raise(self):
        logger = JobLogger(
            job_id="j1",
            job_name="mod.task",
            queue="default",
            attempt=1,
            max_attempts=3,
        )
        logger.error("test error")

    def test_debug_does_not_raise(self):
        logger = JobLogger(
            job_id="j1",
            job_name="mod.task",
            queue="default",
            attempt=1,
            max_attempts=3,
        )
        logger.debug("test debug")

    def test_add_tag(self):
        logger = JobLogger(
            job_id="j1",
            job_name="mod.task",
            queue="default",
            attempt=1,
            max_attempts=3,
        )
        logger.add_tag("env", "prod")

    def test_set_correlation_id(self):
        logger = JobLogger(
            job_id="j1",
            job_name="mod.task",
            queue="default",
            attempt=1,
            max_attempts=3,
        )
        logger.set_correlation_id("corr-123")

    def test_context_manager(self):
        logger = JobLogger(
            job_id="j1",
            job_name="mod.task",
            queue="default",
            attempt=1,
            max_attempts=3,
        )
        with logger:
            logger.info("inside context")


class TestJobContext:
    def test_fields(self):
        ctx = JobContext(
            job_id="j1",
            job_name="mod.task",
            queue="default",
            attempt=2,
            max_attempts=5,
        )
        assert ctx.attempt == 2
        assert ctx.job_name == "mod.task"
