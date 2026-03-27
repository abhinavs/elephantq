"""
Tests that ElephantQ accepts a backend parameter.
"""

import inspect


def test_elephantq_init_accepts_backend():
    """ElephantQ.__init__ should accept a backend parameter."""
    from elephantq.client import ElephantQ

    sig = inspect.signature(ElephantQ.__init__)
    assert "backend" in sig.parameters


def test_elephantq_exposes_backend_property():
    """ElephantQ should expose the backend for features/tests."""
    from elephantq.client import ElephantQ

    assert hasattr(ElephantQ, "backend") or "backend" in dir(ElephantQ)


def test_elephantq_resolves_memory_backend_string():
    """ElephantQ(backend='memory') should create a MemoryBackend."""
    from elephantq.backends.memory import MemoryBackend
    from elephantq.client import ElephantQ

    app = ElephantQ(backend="memory")
    assert isinstance(app.backend, MemoryBackend)


def test_elephantq_resolves_sqlite_backend_string(tmp_path):
    """ElephantQ(backend='sqlite') should create a SQLiteBackend."""
    from elephantq.backends.sqlite import SQLiteBackend
    from elephantq.client import ElephantQ

    app = ElephantQ(backend="sqlite", database_url=str(tmp_path / "test.db"))
    assert isinstance(app.backend, SQLiteBackend)


def test_elephantq_unknown_backend_raises():
    """ElephantQ(backend='redis') should raise ValueError."""
    import pytest

    from elephantq.client import ElephantQ

    with pytest.raises(ValueError, match="Unknown backend"):
        ElephantQ(backend="redis")
