"""
Tests for db/context.py — DatabaseContext class.
"""

from soniq.db.context import DatabaseContext


class TestDatabaseContext:
    def test_from_global_api(self):
        ctx = DatabaseContext.from_global_api()
        assert ctx._soniq_instance is None
        assert ctx._database_url is None

    def test_from_database_url(self):
        ctx = DatabaseContext.from_database_url("postgresql://localhost/test")
        assert ctx._database_url == "postgresql://localhost/test"

    def test_from_instance(self):
        from soniq import Soniq

        app = Soniq(backend="memory")
        ctx = DatabaseContext.from_instance(app)
        assert ctx._soniq_instance is app

    def test_init_defaults(self):
        ctx = DatabaseContext()
        assert ctx._pool is None
        assert ctx._owns_pool is False
