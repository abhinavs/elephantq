"""
Smoke tests for all example files.

Ensures every example is syntactically valid Python and uses importable APIs.
"""

import ast
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


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
