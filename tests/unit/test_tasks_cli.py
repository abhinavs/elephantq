"""
Tests for `soniq tasks list` and `soniq tasks check`.

The two commands deliberately read from different sources: `list` from
the in-process registry; `check` from the shared registry table. The
CLI --help text disambiguation is regression-tested so it cannot
silently drift.
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

from tests.db_utils import TEST_DATABASE_URL

os.environ.setdefault("SONIQ_DATABASE_URL", TEST_DATABASE_URL)

from soniq.cli.commands.tasks import (  # noqa: E402
    handle_tasks_check,
    handle_tasks_list,
    register_tasks_commands,
)

# ---------------------------------------------------------------------------
# tasks list
# ---------------------------------------------------------------------------


def test_tasks_list_prints_valid_json():
    """The `list` command emits valid JSON on stdout."""
    import json

    out = io.StringIO()
    with redirect_stdout(out):
        rc = handle_tasks_list(SimpleNamespace())
    assert rc == 0
    parsed = json.loads(out.getvalue())
    assert isinstance(parsed, list)


def test_tasks_list_help_text_says_in_process(capsys):
    """The CLI help text must explicitly say 'in-process' so an operator
    running `soniq tasks list` on a producer-only instance does not see
    an empty list and conclude the registry table is empty."""
    register_tasks_commands()
    from soniq.cli.registry import get_cli_registry

    registry = get_cli_registry()
    cmd = registry.get_command("tasks-list")
    assert cmd is not None
    assert "in-process" in cmd.description.lower()
    assert "dashboard" in cmd.description.lower()


# ---------------------------------------------------------------------------
# tasks check
# ---------------------------------------------------------------------------


def test_tasks_check_help_text_mentions_shared_registry(capsys):
    register_tasks_commands()
    from soniq.cli.registry import get_cli_registry

    registry = get_cli_registry()
    cmd = registry.get_command("tasks-check")
    assert cmd is not None
    assert "shared registry" in cmd.description.lower() or (
        "registry table" in cmd.description.lower()
    )


def test_tasks_check_without_database_url_emits_helpful_error(monkeypatch):
    """`check` needs a live DB connection. If SONIQ_DATABASE_URL is
    missing AND --database-url is unset, the codemod must fail with a
    clear hint pointing at the env var name (so an operator running it
    in a CI container without the env var gets a readable hint instead
    of a connection traceback)."""
    monkeypatch.delenv("SONIQ_DATABASE_URL", raising=False)
    err = io.StringIO()
    with redirect_stderr(err):
        rc = handle_tasks_check(SimpleNamespace(package="some_pkg", database_url=None))
    assert rc == 2
    msg = err.getvalue()
    assert "SONIQ_DATABASE_URL" in msg


def test_tasks_check_without_package_arg_errors(monkeypatch):
    monkeypatch.setenv("SONIQ_DATABASE_URL", "postgresql://nowhere/db")
    err = io.StringIO()
    with redirect_stderr(err):
        rc = handle_tasks_check(SimpleNamespace(package=None, database_url=None))
    assert rc == 2
    assert "package" in err.getvalue().lower() or "stub" in err.getvalue().lower()
