"""
Tests that the initial schema migration contains all required tables and indexes.
"""

from pathlib import Path

import pytest

from elephantq.db.migrations import MigrationRunner

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "elephantq" / "db" / "migrations"


class TestInitialSchema:
    """Verify the single initial migration has everything needed."""

    def test_single_migration_exists(self):
        files = list(MIGRATIONS_DIR.glob("*.sql"))
        assert len(files) == 1, f"Expected 1 migration file, found {len(files)}: {files}"
        assert files[0].name == "001_initial_schema.sql"

    def test_migration_discovered(self):
        runner = MigrationRunner()
        migrations = runner.discover_migrations()
        versions = [v for v, _, _ in migrations]
        assert "001" in versions

    def test_schema_contains_all_tables(self):
        content = (MIGRATIONS_DIR / "001_initial_schema.sql").read_text()
        assert "elephantq_jobs" in content
        assert "elephantq_workers" in content
        assert "elephantq_recurring_jobs" in content
        assert "elephantq_job_dependencies" in content

    def test_schema_contains_composite_index(self):
        content = (MIGRATIONS_DIR / "001_initial_schema.sql").read_text()
        assert "idx_elephantq_jobs_queue_status_priority" in content

    def test_schema_has_on_delete_set_null(self):
        content = (MIGRATIONS_DIR / "001_initial_schema.sql").read_text()
        assert "ON DELETE SET NULL" in content

    def test_schema_has_dependency_indexes(self):
        content = (MIGRATIONS_DIR / "001_initial_schema.sql").read_text()
        assert "idx_elephantq_job_deps_job_id" in content
        assert "idx_elephantq_job_deps_depends_on" in content
