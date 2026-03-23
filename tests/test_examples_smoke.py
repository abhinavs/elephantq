"""
Smoke tests for all example files and codebase hygiene checks.

Ensures every example is syntactically valid Python and uses importable APIs.
Also checks for dead documentation URLs.
"""

import ast
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
PROJECT_ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize(
    "example", list(EXAMPLES_DIR.glob("*.py")), ids=lambda p: p.name
)
def test_example_syntax(example):
    """Every example must be valid Python."""
    source = example.read_text()
    # This will raise SyntaxError if the file is not valid Python
    ast.parse(source, filename=str(example))


def test_recurring_jobs_uses_real_api():
    """recurring_jobs.py must use the actual elephantq API, not fictional methods."""
    source = (EXAMPLES_DIR / "recurring_jobs.py").read_text()

    # These patterns indicate the broken API calls from the review
    assert "elephantq.schedule(" not in source or "run_at" in source or "run_in" in source, (
        "recurring_jobs.py calls elephantq.schedule() with a cron string, "
        "but elephantq.schedule() requires run_at or run_in keyword arguments"
    )
    assert "elephantq.every(" not in source, (
        "recurring_jobs.py calls elephantq.every() which does not exist. "
        "Use elephantq.features.recurring.every() instead."
    )


def test_transactional_enqueue_setup_call():
    """transactional_enqueue.py must not pass unsupported args to elephantq.setup()."""
    source = (EXAMPLES_DIR / "transactional_enqueue.py").read_text()

    assert "setup(database_url=" not in source, (
        "transactional_enqueue.py passes database_url to elephantq.setup(), "
        "but setup() takes no arguments"
    )


@pytest.mark.parametrize(
    "example",
    [
        "basic_app.py",
        "queue_routing.py",
        "file_processing.py",
        "recurring_jobs.py",
        "webhook_delivery.py",
    ],
)
def test_example_imports_resolve(example):
    """Key imports in each example must resolve to real modules/functions."""
    source = (EXAMPLES_DIR / example).read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                __import__(mod)
        elif isinstance(node, ast.ImportFrom):
            if node.module and not node.module.startswith("fastapi"):
                # Skip fastapi since it's optional for examples
                top = node.module.split(".")[0]
                __import__(top)


def test_no_dead_documentation_urls():
    """No references to non-existent docs.elephantq.dev should exist in source code."""
    dead_url_files = []
    elephantq_dir = PROJECT_ROOT / "elephantq"

    for py_file in elephantq_dir.rglob("*.py"):
        content = py_file.read_text()
        if "docs.elephantq.dev" in content:
            dead_url_files.append(str(py_file.relative_to(PROJECT_ROOT)))

    assert dead_url_files == [], (
        f"Found references to non-existent docs.elephantq.dev in: {dead_url_files}"
    )
