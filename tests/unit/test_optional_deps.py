"""
Packaging policy tests:

- Default install is batteries-included for runtime: `croniter` (so the
  scheduler can fire cron-based recurring jobs) and `prometheus_client`
  (so `PrometheusMetricsSink` is importable from a plain
  `pip install soniq`).
- Dashboard, webhooks, sqlite, and structured logging stay opt-in
  through their respective extras and keep their `_require_*` guards.
- Core (`import soniq`) imports without any extra installed.
"""

from pathlib import Path

import pytest

PYPROJECT = Path(__file__).parent.parent.parent / "pyproject.toml"


def _parse_core_deps() -> list[str]:
    """Scrape `dependencies = [...]` from pyproject.toml.

    No tomllib here so the test can run on installs that don't ship it
    (Python 3.10 baseline). The format is stable enough for a string
    scrape - the pre-commit hooks will reject malformed pyproject.toml
    long before this test runs.
    """
    content = PYPROJECT.read_text()
    in_deps = False
    deps: list[str] = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped == "dependencies = [":
            in_deps = True
            continue
        if in_deps:
            if stripped == "]":
                break
            if stripped.startswith("#") or not stripped:
                continue
            dep = stripped.strip('"').strip("'").rstrip(",").strip().strip('"')
            if dep:
                deps.append(dep.split(">=")[0].split("<")[0].strip())
    return deps


class TestDefaultInstallContents:
    """The base `pip install soniq` ships exactly the runtime batteries."""

    def test_required_runtime_deps_present(self):
        deps = _parse_core_deps()
        assert "asyncpg" in deps
        assert "pydantic" in deps
        assert "pydantic-settings" in deps
        # Batteries included: scheduler + Prometheus metrics.
        assert "croniter" in deps
        assert "prometheus-client" in deps

    def test_optional_extras_not_in_default(self):
        deps = _parse_core_deps()
        # UI is opt-in.
        assert "fastapi" not in deps
        assert "uvicorn" not in deps
        # Other extras keep their _require_* guards.
        assert "aiohttp" not in deps
        assert "cryptography" not in deps
        assert "aiosqlite" not in deps
        assert "structlog" not in deps
        # psutil was removed when features.metrics was deleted.
        assert "psutil" not in deps


class TestExtraGuards:
    """Extras that stay optional must keep emitting actionable errors."""

    def test_webhooks_has_aiohttp_guard(self):
        pytest.importorskip("aiohttp")
        from soniq.features.webhooks import _require_aiohttp

        _require_aiohttp()

    def test_signing_has_cryptography_guard(self):
        pytest.importorskip("cryptography")
        from soniq.features.signing import _require_cryptography

        _require_cryptography()


class TestBatteriesIncluded:
    """Default-install modules import without lazy guards."""

    def test_scheduler_imports_croniter_at_module_load(self):
        from soniq.features import scheduler

        # No ImportError-tolerant shim: croniter is a hard dep now.
        assert scheduler.croniter is not None
        # The old _require_croniter helper is gone.
        assert not hasattr(scheduler, "_require_croniter")

    def test_prometheus_sink_constructs_without_extra(self):
        from prometheus_client import CollectorRegistry

        from soniq.observability import PrometheusMetricsSink

        # Use a private registry so the test doesn't pollute the
        # process-global one and doesn't collide with prior runs.
        sink = PrometheusMetricsSink(registry=CollectorRegistry())
        assert sink is not None

    def test_core_imports_without_dashboard(self):
        import soniq

        assert hasattr(soniq, "Soniq")
        assert hasattr(soniq, "TaskRef")
