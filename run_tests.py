#!/usr/bin/env python3
"""
Soniq Test Runner - Runs tests in organized batches with API isolation

This script runs tests in the new isolated structure:
- Global API tests: Use soniq.job, soniq.enqueue, etc.
- Instance API tests: Use app = Soniq(), app.job, etc.
- Infrastructure tests: Test underlying systems (CLI, connections, etc.)
- Unit tests: Test individual modules
"""
import os
import subprocess
import sys


def _bool_env(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.lower() in {"1", "true", "yes", "on"}


def _venv_python_path(venv_dir: str) -> str:
    return os.path.join(venv_dir, "bin", "python")


def _bootstrap_venv(project_root: str) -> None:
    """Ensure a venv exists, dependencies are installed, and re-exec in the venv."""
    if _bool_env("SONIQ_TEST_VENV_BOOTSTRAPPED"):
        return

    venv_dir = os.path.join(project_root, ".venv")
    venv_python = _venv_python_path(venv_dir)

    if not os.path.exists(venv_python):
        subprocess.check_call([sys.executable, "-m", "venv", venv_dir])

    _cleanup_legacy_editables(venv_python)

    try:
        subprocess.check_call([venv_python, "-m", "pip", "install", "--upgrade", "pip"])
    except Exception as exc:  # noqa: PIE786
        print(
            "⚠️ pip upgrade failed inside test venv; continuing with the existing pip installation."
        )
        print(f"   Details: {exc}")
    try:
        subprocess.check_call(
            [venv_python, "-m", "pip", "install", "-e", ".[dev,dashboard,monitoring]"],
            cwd=project_root,
        )
    except subprocess.CalledProcessError as exc:
        print(
            "⚠️ Editable install failed inside test venv; continuing with existing packages."
        )
        print(f"   Details: {exc}")

    env = os.environ.copy()
    env["SONIQ_TEST_VENV_BOOTSTRAPPED"] = "1"
    env["SONIQ_TEST_VENV_PYTHON"] = venv_python
    os.execvpe(venv_python, [venv_python, __file__], env)


def _cleanup_legacy_editables(venv_python: str) -> None:
    """No-op placeholder for removed legacy editable-install cleanup."""
    return


def run_test_batch(name, test_paths, verbose=True):
    """Run a batch of tests and return success status"""
    print(f"\n{'='*60}")
    print(f"Running {name}")
    print(f"{'='*60}")

    python = os.environ.get("SONIQ_TEST_VENV_PYTHON", sys.executable)
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


def run_flake8():
    """Run flake8 linting in the project"""
    print("\n============================================================")
    print("Running flake8 lint checks")
    print("============================================================")

    python = os.environ.get("SONIQ_TEST_VENV_PYTHON", sys.executable)
    result = subprocess.run([python, "-m", "flake8", "soniq"])
    if result.returncode != 0:
        sys.exit(result.returncode)


def main():
    """Run all test batches with new API isolation structure"""
    print("🚀 Soniq Comprehensive Test Suite")
    print("Running tests with API isolation for maximum reliability...")

    # Change to the script's directory (should be the soniq root)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    print(f"📁 Running tests from: {script_dir}")

    # Bootstrap venv + deps to make this script self-sufficient
    _bootstrap_venv(script_dir)

    # Run linting before the tests to catch formatting issues early
    run_flake8()

    # Avoid row locks during tests when requested
    os.environ.setdefault("SONIQ_SKIP_UPDATE_LOCK", "true")

    # Define test batches with new structure
    test_batches = [
        # UNIT TESTS — fastest, no external dependencies
        (
            "Unit Tests",
            ["tests/unit/"],
        ),
        # BACKEND CONFORMANCE — Memory + SQLite protocol compliance
        (
            "Backend Conformance Tests",
            ["tests/backend/"],
        ),
        # FUNCTIONAL TESTS — SQLite backend, no Postgres needed
        (
            "Functional Tests",
            ["tests/functional/"],
        ),
        # SMOKE TESTS — quick sanity checks
        (
            "Smoke Tests",
            ["tests/smoke/"],
        ),
        # GLOBAL API TESTS - Use soniq.job, soniq.enqueue, etc.
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
        # INSTANCE API TESTS - Use app = Soniq(), app.job, etc.
        (
            "Instance API - Core Functionality",
            ["tests/integration/instance_api/test_core.py"],
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
        # INTEGRATION - Standalone test files
        (
            "Integration - Concurrency & Recovery",
            [
                "tests/integration/test_concurrent_dequeue.py",
                "tests/integration/test_crash_recovery.py",
                "tests/integration/test_pool_exhaustion.py",
                "tests/integration/test_queueing_lock.py",
            ],
        ),
        (
            "Integration - Backend & Handlers",
            [
                "tests/integration/test_postgres_backend.py",
                "tests/integration/test_missing_handler.py",
                "tests/integration/test_timeout_integration.py",
            ],
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
        print("🎉 ALL TESTS PASSING! Soniq is ready for production! 🚀")
        return 0
    else:
        print("⚠️  Some test batches failed. Check individual results above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
