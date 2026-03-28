"""
Tests that ElephantQ accepts a backend parameter.
"""

import inspect

import pytest


def test_elephantq_init_accepts_backend():
    """ElephantQ.__init__ should accept a backend parameter."""
    from elephantq.app import ElephantQ

    sig = inspect.signature(ElephantQ.__init__)
    assert "backend" in sig.parameters


def test_elephantq_exposes_backend_attribute():
    """ElephantQ should expose the _backend attribute for internal use."""
    from elephantq.app import ElephantQ

    app = ElephantQ(backend="memory")
    assert hasattr(app, "_backend")


def test_elephantq_resolves_memory_backend_string():
    """ElephantQ(backend='memory') should create a MemoryBackend."""
    from elephantq.app import ElephantQ
    from elephantq.backends.memory import MemoryBackend

    app = ElephantQ(backend="memory")
    assert isinstance(app._backend, MemoryBackend)


def test_elephantq_resolves_sqlite_backend_string(tmp_path):
    """ElephantQ(backend='sqlite') should create a SQLiteBackend."""
    pytest.importorskip("aiosqlite")
    from elephantq.app import ElephantQ
    from elephantq.backends.sqlite import SQLiteBackend

    app = ElephantQ(backend="sqlite", database_url=str(tmp_path / "test.db"))
    assert isinstance(app._backend, SQLiteBackend)


def test_elephantq_unknown_backend_raises():
    """ElephantQ(backend='redis') should raise ValueError."""
    import pytest

    from elephantq.app import ElephantQ

    with pytest.raises(ValueError, match="Unknown backend"):
        ElephantQ(backend="redis")
