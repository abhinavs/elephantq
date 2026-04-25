"""
Tests that the migration files are correctly structured and contain all required schema.
"""

from pathlib import Path

from soniq.db.migrations import MigrationRunner

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "soniq" / "db" / "migrations"
BASELINE = MIGRATIONS_DIR / "001_soniq_baseline.sql"


class TestMigrationStructure:
    """Verify the single baseline migration exists and is discoverable."""

    def test_only_baseline_exists(self):
        files = sorted(f.name for f in MIGRATIONS_DIR.glob("*.sql"))
        assert files == ["001_soniq_baseline.sql"]

    def test_baseline_discovered(self):
        runner = MigrationRunner()
        migrations = runner.discover_migrations()
        versions = [v for v, _, _ in migrations]
        assert versions == ["001"]


class TestBaselineContents:
    """Everything the old 001-005 migration set used to create must live here."""

    def test_core_jobs(self):
        content = BASELINE.read_text()
        assert "soniq_jobs" in content
        assert "idx_soniq_jobs_queue_status_priority" in content
        assert "result JSONB" in content  # was migration 005

    def test_workers_and_fk(self):
        content = BASELINE.read_text()
        assert "soniq_workers" in content
        assert "worker_id" in content
        assert "ON DELETE SET NULL" in content

    def test_scheduling(self):
        content = BASELINE.read_text()
        assert "soniq_recurring_jobs" in content
        assert "soniq_job_timeouts" in content
        assert "soniq_config" in content

    def test_features(self):
        content = BASELINE.read_text()
        assert "soniq_dead_letter_jobs" in content
        assert "soniq_webhook_endpoints" in content
        assert "soniq_webhook_deliveries" in content
        assert "soniq_logs" in content
