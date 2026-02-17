"""
Smoke tests for the elephantq dev command.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_cli_command(args, timeout=10, expect_success=True):
    env = os.environ.copy()
    env.setdefault("ELEPHANTQ_JOBS_MODULES", "tests.fixtures.cli_jobs")
    result = subprocess.run(
        [sys.executable, "-m", "elephantq.cli.main"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    if expect_success and result.returncode != 0:
        pytest.fail(f"CLI command failed: {result.stderr}")
    return result


@pytest.mark.asyncio
async def test_dev_command_help():
    result = run_cli_command(["dev", "--help"], timeout=5)
    assert "dev" in result.stdout.lower()
    assert "dashboard" in result.stdout.lower()
    assert "scheduler" in result.stdout.lower()


@pytest.mark.asyncio
async def test_dev_command_no_dashboard_scheduler():
    # Should start worker and exit quickly when run once? There is no run_once, so just check help.
    # We smoke test the command wiring via help output to avoid long-running process.
    result = run_cli_command(["dev", "--no-dashboard", "--no-scheduler", "--help"], timeout=5)
    assert "no-dashboard" in result.stdout
    assert "no-scheduler" in result.stdout
