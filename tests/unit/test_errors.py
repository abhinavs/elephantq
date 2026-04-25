"""
Test suite for errors.py — SoniqError and MigrationError.
"""

import pytest

from soniq.errors import MigrationError, SoniqError


class TestSoniqError:
    def test_basic_error_creation(self):
        error = SoniqError(message="Test error", error_code="TEST_ERROR")
        assert error.message == "Test error"
        assert error.error_code == "TEST_ERROR"
        assert error.context == {}
        assert error.suggestions == []
        assert "Soniq Error [TEST_ERROR]: Test error" in str(error)

    def test_error_with_context(self):
        context = {"user_id": 123, "operation": "test_op"}
        error = SoniqError(
            message="Context error", error_code="CONTEXT_ERROR", context=context
        )
        assert error.context == context
        error_str = str(error)
        assert "Context:" in error_str
        assert "user_id: 123" in error_str

    def test_error_with_suggestions(self):
        suggestions = ["Check configuration", "Restart service"]
        error = SoniqError(
            message="Suggestion error",
            error_code="SUGGESTION_ERROR",
            suggestions=suggestions,
        )
        assert error.suggestions == suggestions

    def test_empty_context_and_suggestions(self):
        error = SoniqError(
            message="Test", error_code="TEST", context={}, suggestions=[]
        )
        error_str = str(error)
        assert "Context:" not in error_str
        assert "Suggestions:" not in error_str


class TestMigrationError:
    def test_migration_error_basic(self):
        error = MigrationError(
            migration_step="create_jobs_table", reason="Table already exists"
        )
        assert error.error_code == "MIGRATION_FAILED"
        assert "create_jobs_table" in error.message
        assert "Table already exists" in error.message

    def test_migration_error_with_database_info(self):
        database_info = {"version": "13.2", "encoding": "UTF8"}
        error = MigrationError(
            migration_step="add_index",
            reason="Insufficient privileges",
            database_info=database_info,
        )
        assert error.context["version"] == "13.2"
        assert error.context["encoding"] == "UTF8"


class TestErrorInheritance:
    def test_migration_inherits_from_soniq_error(self):
        assert issubclass(MigrationError, SoniqError)
        assert issubclass(MigrationError, Exception)

    def test_error_can_be_caught_as_exception(self):
        with pytest.raises(Exception):
            raise MigrationError("step", "reason")
