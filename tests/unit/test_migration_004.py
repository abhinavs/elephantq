"""
Tests that migration 004 exists and is discoverable by the migration runner.
"""

from pathlib import Path

import pytest

from elephantq.db.migration_runner import MigrationRunner


class TestMigration004:
    """Verify migration 004 exists and is discoverable."""

    def test_migration_004_exists(self):
        migrations_dir = Path(__file__).parent.parent.parent / "elephantq" / "db" / "migrations"
        migration_file = migrations_dir / "004_composite_index_and_dependencies.sql"
        assert migration_file.exists(), "Migration 004 file does not exist"

    def test_migration_004_discovered(self):
        runner = MigrationRunner()
        migrations = runner.discover_migrations()
        versions = [v for v, _, _ in migrations]
        assert "004" in versions, "Migration 004 not discovered by runner"

    def test_migration_004_contains_composite_index(self):
        migrations_dir = Path(__file__).parent.parent.parent / "elephantq" / "db" / "migrations"
        content = (migrations_dir / "004_composite_index_and_dependencies.sql").read_text()
        assert "idx_elephantq_jobs_queue_status_priority" in content
        assert "queue, status, priority" in content

    def test_migration_004_contains_dependencies_table(self):
        migrations_dir = Path(__file__).parent.parent.parent / "elephantq" / "db" / "migrations"
        content = (migrations_dir / "004_composite_index_and_dependencies.sql").read_text()
        assert "elephantq_job_dependencies" in content
        assert "depends_on_job_id" in content
