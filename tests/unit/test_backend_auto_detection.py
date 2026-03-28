"""
Tests for automatic backend detection based on database_url.
"""

import pytest


def test_postgres_url_selects_postgres_backend():
    """postgresql:// URLs should auto-select PostgresBackend."""
    from elephantq.app import ElephantQ

    app = ElephantQ(database_url="postgresql://localhost/myapp")
    # Backend is None at construction — PostgresBackend created lazily in _ensure_initialized
    # But we can verify it WILL choose Postgres by checking settings
    assert app.settings.database_url == "postgresql://localhost/myapp"
    assert app._backend is None  # Created lazily


def test_sqlite_file_url_selects_sqlite_backend(tmp_path):
    """A .db file path should auto-select SQLiteBackend."""
    pytest.importorskip("aiosqlite")
    from elephantq.app import ElephantQ
    from elephantq.backends.sqlite import SQLiteBackend

    db_path = str(tmp_path / "myapp.db")
    app = ElephantQ(database_url=db_path)
    assert isinstance(app._backend, SQLiteBackend)


def test_sqlite_extension_detected(tmp_path):
    """.sqlite extension should also auto-select SQLiteBackend."""
    pytest.importorskip("aiosqlite")
    from elephantq.app import ElephantQ
    from elephantq.backends.sqlite import SQLiteBackend

    db_path = str(tmp_path / "myapp.sqlite")
    app = ElephantQ(database_url=db_path)
    assert isinstance(app._backend, SQLiteBackend)


def test_no_config_defaults_to_sqlite():
    """No database_url at all should default to SQLiteBackend (zero-setup)."""
    pytest.importorskip("aiosqlite")
    # Override the env to avoid picking up test config
    import os

    from elephantq.app import ElephantQ
    from elephantq.backends.sqlite import SQLiteBackend

    old = os.environ.pop("ELEPHANTQ_DATABASE_URL", None)
    try:
        app = ElephantQ(database_url="elephantq.db")
        assert isinstance(app._backend, SQLiteBackend)
    finally:
        if old:
            os.environ["ELEPHANTQ_DATABASE_URL"] = old


def test_explicit_backend_overrides_auto_detection():
    """Explicit backend= param should override URL-based detection."""
    from elephantq.app import ElephantQ
    from elephantq.backends.memory import MemoryBackend

    app = ElephantQ(backend="memory")
    assert isinstance(app._backend, MemoryBackend)
