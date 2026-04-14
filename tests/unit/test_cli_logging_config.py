"""
CLI logging configuration: `_configure_cli_logging` attaches a single
StreamHandler so worker / scheduler commands emit job logs to the terminal.
"""

import logging

import pytest

from elephantq.cli.commands.core import _configure_cli_logging


@pytest.fixture
def clean_root_logger():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    root.handlers = []
    yield root
    root.handlers = saved_handlers
    root.setLevel(saved_level)


def test_configures_stream_handler_at_info(clean_root_logger):
    _configure_cli_logging("INFO")
    ours = [
        h
        for h in clean_root_logger.handlers
        if getattr(h, "_elephantq_cli_handler", False)
    ]
    assert len(ours) == 1
    assert clean_root_logger.level == logging.INFO


def test_respects_explicit_level(clean_root_logger):
    _configure_cli_logging("DEBUG")
    assert clean_root_logger.level == logging.DEBUG


def test_invalid_level_falls_back_to_info(clean_root_logger):
    _configure_cli_logging("NOPE")
    assert clean_root_logger.level == logging.INFO


def test_is_idempotent(clean_root_logger):
    _configure_cli_logging("INFO")
    _configure_cli_logging("INFO")
    _configure_cli_logging("INFO")
    ours = [
        h
        for h in clean_root_logger.handlers
        if getattr(h, "_elephantq_cli_handler", False)
    ]
    assert len(ours) == 1


def test_processor_logs_are_emitted(clean_root_logger, caplog):
    """Job-lifecycle logs from elephantq.core.processor reach handlers
    once CLI logging is configured."""
    _configure_cli_logging("INFO")
    with caplog.at_level(logging.INFO, logger="elephantq.core.processor"):
        logging.getLogger("elephantq.core.processor").info("Job abc completed in 12ms")
    assert any("Job abc completed" in rec.message for rec in caplog.records)
