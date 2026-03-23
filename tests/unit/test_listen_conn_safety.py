"""
Test that the LISTEN connection in the worker loop is acquired safely.

The connection must be acquired inside the try block so it is always
released in the finally block, even if an exception occurs during setup.
"""

import ast
from pathlib import Path


def test_listen_conn_acquired_inside_try():
    """
    In the worker() inner function of _run_worker_continuous,
    listen_conn must be assigned inside the try block (or initialized
    to None before try) so the finally block can always clean it up.
    """
    client_path = (
        Path(__file__).parent.parent.parent / "elephantq" / "client.py"
    )
    source = client_path.read_text()

    # The fix requires one of:
    # 1. listen_conn = None before try, then acquired inside try
    # 2. listen_conn acquired inside try block directly

    # Check that "listen_conn = None" appears before "try:" in the worker function
    # OR that pool.acquire() is inside the try block
    lines = source.splitlines()

    # Find the worker() function inside _run_worker_continuous
    in_worker_func = False
    found_none_init = False
    found_try = False
    found_acquire_before_try = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if "async def worker():" in stripped:
            in_worker_func = True
            found_none_init = False
            found_try = False
            continue

        if in_worker_func:
            if "listen_conn = None" in stripped:
                found_none_init = True
            if stripped == "try:":
                found_try = True
            if "pool.acquire()" in stripped and not found_try:
                found_acquire_before_try = True
            # Stop at the end of the worker function
            if stripped.startswith("# Setup signal") or stripped.startswith("shutdown_event"):
                break

    assert not found_acquire_before_try or found_none_init, (
        "listen_conn is acquired via pool.acquire() before the try block "
        "without being initialized to None first. If an exception occurs "
        "between acquire and the try block, the connection leaks."
    )
