"""
Tests for db/context.py — context operations.
"""

from elephantq.db.context import (
    DatabaseContext,
    clear_current_context,
    get_current_context,
    set_current_context,
)


class TestContextOperations:
    def test_set_and_get_current_context(self):
        ctx = DatabaseContext()
        set_current_context(ctx)
        result = get_current_context()
        assert result is ctx
        clear_current_context()

    def test_clear_current_context(self):
        ctx = DatabaseContext()
        set_current_context(ctx)
        clear_current_context()
        # After clearing, get_current_context should return None or raise
        result = get_current_context()
        assert result is None or result is not ctx

    def test_from_database_url_stores_url(self):
        ctx = DatabaseContext.from_database_url("postgresql://localhost/test")
        assert ctx._database_url == "postgresql://localhost/test"

    def test_repr(self):
        ctx = DatabaseContext()
        r = repr(ctx)
        assert "DatabaseContext" in r

    def test_database_url_property(self):
        ctx = DatabaseContext(database_url="postgresql://localhost/test")
        assert ctx.database_url == "postgresql://localhost/test"
