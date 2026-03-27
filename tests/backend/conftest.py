"""
Backend conformance test fixtures.

Parametrized over Memory and SQLite backends.
Postgres conformance runs separately in tests/integration/.
"""

import pytest

from elephantq.backends.memory import MemoryBackend
from elephantq.backends.sqlite import SQLiteBackend


@pytest.fixture(params=["memory", "sqlite"])
async def backend(request, tmp_path):
    if request.param == "memory":
        b = MemoryBackend()
    elif request.param == "sqlite":
        b = SQLiteBackend(str(tmp_path / "test.db"))
    await b.initialize()
    yield b
    await b.close()
