"""
Tests for the `soniq migrate-enqueue` codemod.

The codemod is exercised at two layers: the engine (migrate_source) and
the CLI wrapper (run_codemod). The engine tests validate the AST
rewrite; the CLI tests validate the missing-mapping refusal flow plus
the --use-derived-names flag.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

# Engine import: prefer the in-repo scripts/ path.
_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _REPO_ROOT)
from scripts.migrate_enqueue import migrate_source  # noqa: E402
from soniq.cli.commands.migrate_enqueue import run_codemod  # noqa: E402

# ---------------------------------------------------------------------------
# Engine tests
# ---------------------------------------------------------------------------


class TestMigrateSourceEngine:
    def test_simple_kwargs_call_rewritten(self):
        src = """
import asyncio

async def go():
    await app.enqueue(my_func, x=1)
""".lstrip()
        new, changes = migrate_source(src)
        assert 'app.enqueue("my_func", args={"x": 1})' in new
        assert any("rewrite app.enqueue(my_func" in c for c in changes)

    def test_connection_kwarg_preserved_outside_args_dict(self):
        src = """
async def go():
    await app.enqueue(f, connection=c, x=1)
""".lstrip()
        new, _ = migrate_source(src)
        assert 'app.enqueue("f", args={"x": 1}, connection=c)' in new

    def test_queue_priority_preserved_outside_args_dict(self):
        src = """
async def go():
    await app.enqueue(my_func, x=1, queue="urgent", priority=5)
""".lstrip()
        new, _ = migrate_source(src)
        # ast.unparse may emit either quote style; check structural shape
        # rather than verbatim text.
        assert 'app.enqueue("my_func", args={"x": 1},' in new
        assert "queue=" in new and "urgent" in new
        assert "priority=5" in new

    def test_string_first_arg_left_alone(self):
        src = 'await app.enqueue("already.migrated", args={"x": 1})\n'
        new, _ = migrate_source(src)
        assert new == src

    def test_module_level_soniq_enqueue_rewritten(self):
        src = """
async def go():
    await soniq.enqueue(my_func, x=1)
""".lstrip()
        new, _ = migrate_source(src)
        assert 'soniq.enqueue("my_func", args={"x": 1})' in new

    def test_idempotent(self):
        src = """
async def go():
    await app.enqueue(my_func, x=1)
""".lstrip()
        once, _ = migrate_source(src)
        twice, second_changes = migrate_source(once)
        assert once == twice
        # Second pass produces no rewrites.
        assert not any("rewrite" in c or "add name" in c for c in second_changes)

    def test_job_decorator_gets_explicit_name(self):
        src = """
@app.job()
async def my_task(x):
    pass
""".lstrip()
        new, changes = migrate_source(src)
        assert '@app.job(name="my_task")' in new
        assert any("add name='my_task'" in c for c in changes)

    def test_job_decorator_with_existing_kwargs_preserves_them(self):
        src = """
@app.job(retries=3, queue="urgent")
async def my_task():
    pass
""".lstrip()
        new, _ = migrate_source(src)
        assert '@app.job(name="my_task", retries=3, queue="urgent")' in new

    def test_resolver_can_remap_names(self):
        src = """
@app.job()
async def my_task():
    pass

await app.enqueue(my_task)
""".lstrip()
        new, _ = migrate_source(
            src,
            name_resolver=lambda short, kind: f"billing.{short}",
        )
        assert '@app.job(name="billing.my_task")' in new
        assert 'app.enqueue("billing.my_task")' in new

    def test_resolver_returning_none_refuses_and_emits_diagnostic(self):
        src = """
@app.job()
async def my_task():
    pass

await app.enqueue(my_task, x=1)
""".lstrip()
        new, changes = migrate_source(src, name_resolver=lambda *_: None)
        # No rewrite happened.
        assert "@app.job()" in new
        assert "app.enqueue(my_task" in new
        # Two REFUSE diagnostics (decorator + call).
        refuses = [c for c in changes if "REFUSE" in c]
        assert len(refuses) >= 2
        assert all("my_task" in r for r in refuses)


# ---------------------------------------------------------------------------
# CLI wrapper tests
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """A small project tree with a known old-shape call."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "tasks.py").write_text(
        "async def go():\n    await app.enqueue(my_func, x=1)\n"
    )
    return tmp_path


class TestRunCodemod:
    def test_use_derived_names_rewrites_to_bare_ident(self, tmp_project):
        out = io.StringIO()
        err = io.StringIO()
        rc = run_codemod(
            paths=[str(tmp_project)],
            name_map={},
            use_derived=True,
            stdout=out,
            stderr=err,
        )
        assert rc == 0
        text = (tmp_project / "src" / "tasks.py").read_text()
        assert 'app.enqueue("my_func", args={"x": 1})' in text

    def test_missing_mapping_without_derive_refuses_and_exits_non_zero(
        self, tmp_project
    ):
        out = io.StringIO()
        err = io.StringIO()
        rc = run_codemod(
            paths=[str(tmp_project)],
            name_map={},  # no mapping at all
            use_derived=False,
            stdout=out,
            stderr=err,
        )
        assert rc == 2
        # File untouched (no rewrite happened).
        text = (tmp_project / "src" / "tasks.py").read_text()
        assert "app.enqueue(my_func, x=1)" in text
        # Diagnostic on stderr mentions migrate-enqueue.toml.
        err_str = err.getvalue()
        assert "REFUSE" in err_str
        assert "migrate-enqueue.toml" in err_str
        assert "my_func" in err_str

    def test_explicit_mapping_rewrites_with_canonical_name(self, tmp_project):
        out = io.StringIO()
        err = io.StringIO()
        rc = run_codemod(
            paths=[str(tmp_project)],
            name_map={"my_func": "billing.my_func"},
            use_derived=False,
            stdout=out,
            stderr=err,
        )
        assert rc == 0
        text = (tmp_project / "src" / "tasks.py").read_text()
        assert 'app.enqueue("billing.my_func", args={"x": 1})' in text

    def test_partial_mapping_refuses_for_unmapped_only(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "tasks.py").write_text(
            "async def go():\n"
            "    await app.enqueue(known_task, x=1)\n"
            "    await app.enqueue(unknown_task, y=2)\n"
        )
        out = io.StringIO()
        err = io.StringIO()
        rc = run_codemod(
            paths=[str(tmp_path)],
            name_map={"known_task": "ns.known"},
            use_derived=False,
            stdout=out,
            stderr=err,
        )
        assert rc == 2
        text = (src_dir / "tasks.py").read_text()
        # Mapped one rewritten.
        assert 'app.enqueue("ns.known", args={"x": 1})' in text
        # Unmapped one untouched.
        assert "app.enqueue(unknown_task, y=2)" in text
        # Diagnostic mentions the unmapped one.
        assert "unknown_task" in err.getvalue()
