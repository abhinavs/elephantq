"""
Tests for ``soniq tasks-list`` and ``soniq tasks-check``.

The two commands deliberately read from different sources: ``list``
from the in-process registry; ``check`` from the shared registry
table. After the flat-CLI rewrite (S8) the parser is the contract;
these tests run handlers directly and introspect the parser produced
by ``soniq.cli.main.build_parser``.
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

from tests.db_utils import TEST_DATABASE_URL

os.environ.setdefault("SONIQ_DATABASE_URL", TEST_DATABASE_URL)

from soniq.cli.main import build_parser  # noqa: E402
from soniq.cli.tasks import handle_tasks_check, handle_tasks_list  # noqa: E402

# ---------------------------------------------------------------------------
# tasks-list
# ---------------------------------------------------------------------------


def test_tasks_list_prints_valid_json():
    """The ``tasks-list`` command emits valid JSON on stdout."""
    import json

    out = io.StringIO()
    with redirect_stdout(out):
        rc = handle_tasks_list(SimpleNamespace())
    assert rc == 0
    parsed = json.loads(out.getvalue())
    assert isinstance(parsed, list)


def test_tasks_list_help_text_says_in_process():
    """The CLI help text must explicitly say "in-process" so an operator
    running ``soniq tasks-list`` on a producer-only deployment does not
    see an empty list and conclude the registry table is empty."""
    parser = build_parser()
    help_text = _subcommand_help(parser, "tasks-list")
    assert "in-process" in help_text.lower()
    assert "dashboard" in help_text.lower()


# ---------------------------------------------------------------------------
# tasks-check
# ---------------------------------------------------------------------------


def test_tasks_check_help_text_mentions_shared_registry():
    parser = build_parser()
    help_text = _subcommand_help(parser, "tasks-check")
    assert (
        "shared registry" in help_text.lower() or "registry table" in help_text.lower()
    )


def test_tasks_check_without_database_url_emits_helpful_error(monkeypatch):
    """``check`` needs a live DB connection. If SONIQ_DATABASE_URL is
    missing AND ``--database-url`` is unset, the codemod must fail with
    a clear hint pointing at the env var name (so an operator running
    it in a CI container without the env var gets a readable hint
    instead of a connection traceback)."""
    monkeypatch.delenv("SONIQ_DATABASE_URL", raising=False)
    err = io.StringIO()
    with redirect_stderr(err):
        rc = handle_tasks_check(SimpleNamespace(package="some_pkg", database_url=None))
    assert rc == 2
    assert "SONIQ_DATABASE_URL" in err.getvalue()


def test_tasks_check_without_package_arg_errors(monkeypatch):
    monkeypatch.setenv("SONIQ_DATABASE_URL", "postgresql://nowhere/db")
    err = io.StringIO()
    with redirect_stderr(err):
        rc = handle_tasks_check(SimpleNamespace(package=None, database_url=None))
    assert rc == 2
    msg = err.getvalue().lower()
    assert "package" in msg or "stub" in msg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subcommand_help(parser, name: str) -> str:
    """Render the ``--help`` text for a named subcommand.

    Walks the top-level parser to find the subparser for ``name`` and
    formats its help into a string. Used to pin help text wording so a
    refactor cannot silently drop the disambiguation that operators
    rely on.
    """
    for action in parser._actions:
        if isinstance(action, getattr(__import__("argparse"), "_SubParsersAction")):
            sub = action.choices.get(name)
            assert sub is not None, f"subcommand {name!r} not registered"
            return sub.format_help()
    raise AssertionError("no subparsers on parser")
