"""
Tests that the migration files are correctly structured and contain all required schema.
"""

from pathlib import Path

from elephantq.db.migrations import MigrationRunner

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "elephantq" / "db" / "migrations"


class TestMigrationStructure:
    """Verify migrations exist and are discoverable."""

    def test_all_expected_migrations_exist(self):
        files = sorted(f.name for f in MIGRATIONS_DIR.glob("*.sql"))
        assert files == [
            "001_core_jobs.sql",
            "002_workers.sql",
            "003_scheduling.sql",
            "004_features.sql",
            "005_job_results.sql",
        ]

    def test_all_migrations_discovered(self):
        runner = MigrationRunner()
        migrations = runner.discover_migrations()
        versions = [v for v, _, _ in migrations]
        assert versions == ["001", "002", "003", "004", "005"]


class TestCoreJobsMigration:
    """001: core jobs table and indexes."""

    def test_jobs_table(self):
        content = (MIGRATIONS_DIR / "001_core_jobs.sql").read_text()
        assert "elephantq_jobs" in content
        assert "idx_elephantq_jobs_queue_status_priority" in content

    def test_no_worker_id_column(self):
        """worker_id is added by 002, not 001 — keeps the dependency clean."""
        content = (MIGRATIONS_DIR / "001_core_jobs.sql").read_text()
        assert "worker_id" not in content


class TestWorkersMigration:
    """002: worker heartbeat and job tracking."""

    def test_workers_table_and_fk(self):
        content = (MIGRATIONS_DIR / "002_workers.sql").read_text()
        assert "elephantq_workers" in content
        assert "worker_id" in content
        assert "ON DELETE SET NULL" in content


class TestSchedulingMigration:
    """003: recurring jobs, dependencies, and timeouts."""

    def test_recurring_jobs(self):
        content = (MIGRATIONS_DIR / "003_scheduling.sql").read_text()
        assert "elephantq_recurring_jobs" in content

    def test_no_dependencies_table(self):
        content = (MIGRATIONS_DIR / "003_scheduling.sql").read_text()
        assert "elephantq_job_dependencies" not in content

    def test_timeouts(self):
        content = (MIGRATIONS_DIR / "003_scheduling.sql").read_text()
        assert "elephantq_job_timeouts" in content
        assert "elephantq_config" in content


class TestFeaturesMigration:
    """004: dead letter, webhooks, logging."""

    def test_dead_letter(self):
        content = (MIGRATIONS_DIR / "004_features.sql").read_text()
        assert "elephantq_dead_letter_jobs" in content

    def test_webhooks(self):
        content = (MIGRATIONS_DIR / "004_features.sql").read_text()
        assert "elephantq_webhook_endpoints" in content
        assert "elephantq_webhook_deliveries" in content

    def test_logging(self):
        content = (MIGRATIONS_DIR / "004_features.sql").read_text()
        assert "elephantq_logs" in content
