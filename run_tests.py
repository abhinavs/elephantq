#!/usr/bin/env python3
"""
ElephantQ Test Runner - Runs tests in organized batches with API isolation

This script runs tests in the new isolated structure:
- Global API tests: Use elephantq.job, elephantq.enqueue, etc.
- Instance API tests: Use app = ElephantQ(), app.job, etc.
- Infrastructure tests: Test underlying systems (CLI, connections, etc.)
- Unit tests: Test individual modules
"""
import os
import subprocess
import sys
from pathlib import Path
import shutil


def _bool_env(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.lower() in {"1", "true", "yes", "on"}


def _venv_python_path(venv_dir: str) -> str:
    return os.path.join(venv_dir, "bin", "python")


def _bootstrap_venv(project_root: str) -> None:
    """Ensure a venv exists, dependencies are installed, and re-exec in the venv."""
    if _bool_env("ELEPHANTQ_TEST_VENV_BOOTSTRAPPED"):
        return

    venv_dir = os.path.join(project_root, ".venv")
    venv_python = _venv_python_path(venv_dir)

    if not os.path.exists(venv_python):
        subprocess.check_call([sys.executable, "-m", "venv", venv_dir])

    _cleanup_legacy_editables(venv_python)

    subprocess.check_call([venv_python, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call(
        [venv_python, "-m", "pip", "install", "-e", ".[dev,dashboard,monitoring]"],
        cwd=project_root,
    )

    env = os.environ.copy()
    env["ELEPHANTQ_TEST_VENV_BOOTSTRAPPED"] = "1"
    env["ELEPHANTQ_TEST_VENV_PYTHON"] = venv_python
    os.execvpe(venv_python, [venv_python, __file__], env)


def _cleanup_legacy_editables(venv_python: str) -> None:
    """Remove stale editable installs from previous package names."""
    try:
        site_packages = subprocess.check_output(
            [
                venv_python,
                "-c",
                "import site; print(site.getsitepackages()[0])",
            ],
            text=True,
        ).strip()
    except Exception:
        return

    site_path = Path(site_packages)
    if not site_path.exists():
        return

    for pth in site_path.glob("__editable__.runql-*.pth"):
        pth.unlink(missing_ok=True)

    for dist in site_path.glob("runql-*.dist-info"):
        shutil.rmtree(dist, ignore_errors=True)


def run_test_batch(name, test_paths, verbose=True):
    """Run a batch of tests and return success status"""
    print(f"\n{'='*60}")
    print(f"Running {name}")
    print(f"{'='*60}")

    python = os.environ.get("ELEPHANTQ_TEST_VENV_PYTHON", sys.executable)
    cmd = [python, "-m", "pytest"] + test_paths
    if verbose:
        cmd.append("-v")
    else:
        cmd.extend(["--tb=no", "-q"])

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print(f"✅ {name} - ALL PASSED")
        return True
    else:
        print(f"❌ {name} - FAILED")
        return False


def main():
    """Run all test batches with new API isolation structure"""
    print("🚀 ElephantQ Comprehensive Test Suite")
    print("Running tests with API isolation for maximum reliability...")

    # Change to the script's directory (should be the elephantq root)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    print(f"📁 Running tests from: {script_dir}")

    # Bootstrap venv + deps to make this script self-sufficient
    _bootstrap_venv(script_dir)

    # Avoid row locks during tests when requested
    os.environ.setdefault("ELEPHANTQ_SKIP_UPDATE_LOCK", "true")

    # Define test batches with new structure
    test_batches = [
        # GLOBAL API TESTS - Use elephantq.job, elephantq.enqueue, etc.
        (
            "Global API - Job Management & Introspection",
            ["tests/integration/global_api/test_job_introspection.py"],
        ),
        (
            "Global API - Corrupted Data Handling",
            ["tests/integration/global_api/test_corrupted_data_handling.py"],
        ),
        (
            "Global API - Edge Cases",
            ["tests/integration/global_api/test_edge_cases.py"],
        ),
        (
            "Global API - Error Handling Edge Cases",
            ["tests/integration/global_api/test_error_handling_edge_cases.py"],
        ),
        (
            "Global API - Production Scenarios",
            ["tests/integration/global_api/test_production_scenarios.py"],
        ),
        (
            "Global API - Scheduling & Timing",
            ["tests/integration/global_api/test_scheduling.py"],
        ),
        (
            "Global API - Specification Compliance",
            ["tests/integration/global_api/test_specification_compliance.py"],
        ),
        (
            "Global API - TTL & Job Cleanup",
            ["tests/integration/global_api/test_ttl_functionality.py"],
        ),
        # INSTANCE API TESTS - Use app = ElephantQ(), app.job, etc.
        (
            "Instance API - Core Functionality",
            ["tests/integration/instance_api/test_core.py"],
        ),
        (
            "Instance API - Worker Heartbeat System",
            ["tests/integration/instance_api/test_worker_heartbeat.py"],
        ),
        (
            "Instance API - Worker Heartbeat Comprehensive",
            ["tests/integration/instance_api/test_worker_heartbeat_comprehensive.py"],
        ),
        # INFRASTRUCTURE TESTS - Support both APIs
        (
            "Infrastructure - CLI Integration",
            [
                "tests/integration/infrastructure/test_cli_integration.py",
                "tests/integration/infrastructure/test_cli_queue_behavior.py",
            ],
        ),
        (
            "Infrastructure - Signal Handling & Graceful Shutdown",
            [
                "tests/integration/infrastructure/test_signal_handling.py",
                "tests/integration/infrastructure/test_graceful_shutdown.py",
            ],
        ),
        (
            "Infrastructure - Database URL Integration",
            ["tests/integration/test_database_url_integration.py"],
        ),
        (
            "Infrastructure - Connection Context",
            ["tests/integration/infrastructure/test_connection_context.py"],
        ),
        (
            "Infrastructure - LISTEN/NOTIFY Performance",
            ["tests/integration/infrastructure/test_listen_notify.py"],
        ),
        (
            "Infrastructure - Queue Processing Behavior",
            ["tests/integration/infrastructure/test_queue_processing_behavior.py"],
        ),
        (
            "Integration - Feature Modules",
            [
                "tests/integration/test_dashboard_api.py",
                "tests/integration/test_dead_letter_queue.py",
                "tests/integration/test_webhooks.py",
                "tests/integration/test_migrations.py",
                "tests/integration/test_transactional_enqueue.py",
            ],
        ),
        # UNIT TESTS
        (
            "Unit Tests - Core Modules",
            [
                "tests/unit/test_health.py",
                "tests/unit/test_errors.py",
                "tests/unit/test_hashing.py",
                "tests/unit/test_signal_handling.py",
                "tests/unit/test_retry_backoff.py",
            ],
        ),
        (
            "Unit Tests - Other",
            [
                "tests/unit/test_configuration.py",
                "tests/unit/test_global_api.py",
            ],
        ),
    ]

    # Run each batch
    results = []
    total_batches = len(test_batches)

    for i, (name, paths) in enumerate(test_batches, 1):
        print(f"\n[{i}/{total_batches}] ", end="")
        success = run_test_batch(name, paths, verbose=False)
        results.append((name, success))

    # Summary
    print(f"\n{'='*60}")
    print("🎯 FINAL RESULTS")
    print(f"{'='*60}")

    passed_count = 0
    for name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{status:12} {name}")
        if success:
            passed_count += 1

    print(f"\n📊 SUMMARY: {passed_count}/{total_batches} test batches passed")

    if passed_count == total_batches:
        print("🎉 ALL TESTS PASSING! ElephantQ is ready for production! 🚀")
        return 0
    else:
        print("⚠️  Some test batches failed. Check individual results above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
