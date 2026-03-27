"""
Fixtures for SQLite backend tests.

No PostgreSQL required. Uses temp files that are cleaned up automatically.
"""

import pytest

from elephantq.backends.sqlite import SQLiteBackend


@pytest.fixture
async def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "test_elephantq.db"))
    await b.initialize()
    yield b
    await b.close()
