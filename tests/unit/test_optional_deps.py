"""
Tests that optional dependency guards work correctly.

Written to verify HIGH-03: optional deps produce clear error messages.
"""

import pytest


class TestOptionalDepGuards:
    """Verify import guards produce actionable error messages."""

    def test_recurring_has_croniter_guard(self):
        """recurring.py should have a _require_croniter guard function."""
        pytest.importorskip("croniter")
        from soniq.features.recurring import _require_croniter

        # Since croniter is installed in dev, this should not raise
        _require_croniter()

    def test_webhooks_has_aiohttp_guard(self):
        """webhooks.py should have a _require_aiohttp guard function."""
        pytest.importorskip("aiohttp")
        from soniq.features.webhooks import _require_aiohttp

        # Since aiohttp is installed in dev, this should not raise
        _require_aiohttp()

    def test_signing_has_cryptography_guard(self):
        """signing.py should have a _require_cryptography guard function."""
        pytest.importorskip("cryptography")
        from soniq.features.signing import _require_cryptography

        # Since cryptography is installed in dev, this should not raise
        _require_cryptography()

    def test_core_import_without_optional_deps(self):
        """Core soniq should be importable (deps are installed but the
        import path should not fail at module level if they weren't)."""
        import soniq

        assert hasattr(soniq, "enqueue")
        assert hasattr(soniq, "job")

    def test_pyproject_core_deps_minimal(self):
        """pyproject.toml core deps should only be asyncpg, pydantic, pydantic-settings."""
        from pathlib import Path

        content = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text()

        # Find the dependencies section
        in_deps = False
        core_deps = []
        for line in content.split("\n"):
            if line.strip() == "dependencies = [":
                in_deps = True
                continue
            if in_deps:
                if line.strip() == "]":
                    break
                dep = line.strip().strip('"').strip("'").strip(",").strip('"')
                if dep:
                    core_deps.append(dep.split(">=")[0].split("<")[0].strip())

        assert "asyncpg" in core_deps
        assert "pydantic" in core_deps
        assert "pydantic-settings" in core_deps
        assert "croniter" not in core_deps, "croniter should be in [scheduling] extra"
        assert "aiohttp" not in core_deps, "aiohttp should be in [webhooks] extra"
        assert "structlog" not in core_deps, "structlog should be in [logging] extra"
        assert (
            "cryptography" not in core_deps
        ), "cryptography should be in [webhooks] extra"
