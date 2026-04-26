"""
`soniq tasks list` and `soniq tasks check` CLIs.

Two thin commands over the cross-service observability surface:

- ``list`` prints the in-process registry (everything the current
  process registered after importing ``SONIQ_JOBS_MODULES``). It does
  *not* read the soniq_task_registry DB table; that table is
  fleet-wide observability shown in the dashboard.

- ``check`` compares the TaskRef declarations in a stub package
  against the soniq_task_registry table populated by running workers.
  Drift (refs without a corresponding worker row, or vice versa) is
  reported and exits non-zero so CI can block deploys.

The two commands deliberately read from different sources so an
operator running ``soniq tasks list`` on a producer-only instance does
not see an empty list and conclude the registry is empty - they see
what the current process registered, which is the right scope for a
local listing.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from typing import Any, Dict, List, Optional

# Both commands share these option names with the rest of the soniq CLI.


def _load_in_process_jobs() -> List[Dict[str, Any]]:
    """Discover and return registered jobs in the current process.

    Imports modules listed in SONIQ_JOBS_MODULES (comma-separated) so
    decorator-time registrations populate the global registry. Then
    reads from soniq._get_global_app()._get_job_registry().
    """
    modules = os.environ.get("SONIQ_JOBS_MODULES", "")
    for mod in [m.strip() for m in modules.split(",") if m.strip()]:
        try:
            importlib.import_module(mod)
        except Exception as e:
            print(
                f"soniq tasks list: failed to import {mod!r}: {e}",
                file=sys.stderr,
            )

    import soniq

    app = soniq._get_global_app()
    registry = app._get_job_registry()
    rows = []
    for name, meta in registry.list_jobs().items():
        args_model = meta.get("args_model")
        rows.append(
            {
                "name": name,
                "queue": meta.get("queue"),
                "priority": meta.get("priority"),
                "args_model": (
                    getattr(args_model, "__name__", repr(args_model))
                    if args_model is not None
                    else None
                ),
            }
        )
    return rows


def handle_tasks_list(args) -> int:
    """argparse handler for `soniq tasks list`.

    Lists task names registered by the current process after importing
    SONIQ_JOBS_MODULES. To see what is in the shared registry table
    across the fleet, use the dashboard.
    """
    rows = _load_in_process_jobs()
    print(json.dumps(rows, indent=2, sort_keys=True))
    return 0


def _load_task_refs_from_package(package_path: str) -> List[Dict[str, Any]]:
    """Import a Python package directory or module and collect TaskRef
    instances declared inside it. Returns a list of dicts with name,
    args_model, and source location."""
    import inspect

    from soniq.task_ref import TaskRef

    # Make package importable: add the parent dir to sys.path if package_path
    # is a directory; if it's a dotted module name, just import it.
    abs_path = os.path.abspath(package_path)
    if os.path.isdir(abs_path):
        parent = os.path.dirname(abs_path)
        package_name = os.path.basename(abs_path)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        module = importlib.import_module(package_name)
    else:
        module = importlib.import_module(package_path)

    found: List[Dict[str, Any]] = []
    seen_names: set[str] = set()

    def visit(mod):
        for _, value in inspect.getmembers(mod):
            if isinstance(value, TaskRef) and value.name not in seen_names:
                found.append(
                    {
                        "name": value.name,
                        "args_model": (
                            getattr(value.args_model, "__name__", None)
                            if value.args_model
                            else None
                        ),
                        "default_queue": value.default_queue,
                    }
                )
                seen_names.add(value.name)

    visit(module)
    # Walk submodules (one level - keep this simple).
    if hasattr(module, "__path__"):
        import pkgutil

        for info in pkgutil.iter_modules(module.__path__, prefix=f"{module.__name__}."):
            try:
                visit(importlib.import_module(info.name))
            except Exception as e:
                print(
                    f"soniq tasks check: skipped {info.name}: {e}",
                    file=sys.stderr,
                )
    return found


async def _load_registry_table_names(database_url: Optional[str]) -> List[str]:
    """Fetch the task names registered in the soniq_task_registry DB
    table for the configured Postgres database."""
    from soniq.app import Soniq

    app = Soniq(database_url=database_url) if database_url else Soniq()
    await app._ensure_initialized()
    try:
        backend = app._backend
        assert backend is not None  # narrow after init
        rows = await backend.list_registered_task_names()
        return sorted({r["task_name"] for r in rows})
    finally:
        await app.close()


def handle_tasks_check(args) -> int:
    """argparse handler for `soniq tasks check`.

    Compares stub-package TaskRefs against the shared registry table
    populated by running workers. Drift exits non-zero so CI can block
    deploys.
    """
    if not args.package:
        print(
            "soniq tasks check: a stub package path or dotted module is required",
            file=sys.stderr,
        )
        return 2

    db_url = os.environ.get("SONIQ_DATABASE_URL") or args.database_url
    if not db_url:
        print(
            "soniq tasks check: requires SONIQ_DATABASE_URL to read the "
            "shared task registry; set it in the environment or pass "
            "--database-url.",
            file=sys.stderr,
        )
        return 2

    refs = _load_task_refs_from_package(args.package)
    ref_names = {r["name"] for r in refs}

    import asyncio

    table_names = set(asyncio.run(_load_registry_table_names(db_url)))

    in_stub_not_table = sorted(ref_names - table_names)
    in_table_not_stub = sorted(table_names - ref_names)

    drift_count = len(in_stub_not_table) + len(in_table_not_stub)

    if not drift_count:
        print(
            f"soniq tasks check: OK - {len(ref_names)} TaskRef(s) match "
            f"{len(table_names)} registered name(s) in the soniq_task_registry "
            f"table.",
            file=sys.stdout,
        )
        return 0

    if in_stub_not_table:
        print(
            "DRIFT: TaskRefs in the stub package have no worker registered "
            "for them in soniq_task_registry:",
            file=sys.stderr,
        )
        for n in in_stub_not_table:
            print(f"  - {n}", file=sys.stderr)
    if in_table_not_stub:
        print(
            "DRIFT: registered names in soniq_task_registry have no "
            "TaskRef in the stub package:",
            file=sys.stderr,
        )
        for n in in_table_not_stub:
            print(f"  - {n}", file=sys.stderr)
    return 2


def register_tasks_commands():
    """Register `tasks list` and `tasks check` on the global CLI registry.

    The CLI infrastructure here is flat (no native subgroups), so we
    expose two top-level commands with explicit names.
    """
    from ..registry import CLICommand, get_cli_registry

    registry = get_cli_registry()

    registry.register_command(
        CLICommand(
            name="tasks-list",
            help=(
                "List task names registered by the current process "
                "(in-process registry only)"
            ),
            description=(
                "Lists task names registered by the current (in-process) "
                "registry after importing SONIQ_JOBS_MODULES. To see what is "
                "in the shared registry table across the fleet, use the "
                "dashboard."
            ),
            handler=handle_tasks_list,
            arguments=[],
            category="observability",
        )
    )

    registry.register_command(
        CLICommand(
            name="tasks-check",
            help="Compare stub-package TaskRefs against the shared registry table",
            description=(
                "Compares stub-package TaskRefs against the shared registry "
                "table populated by running workers. Drift exits non-zero so "
                "CI can block deploys. Requires SONIQ_DATABASE_URL to read the "
                "registry table."
            ),
            handler=handle_tasks_check,
            arguments=[
                {
                    "args": ["package"],
                    "kwargs": {
                        "nargs": "?",
                        "help": (
                            "Stub package path or dotted module containing "
                            "TaskRef declarations"
                        ),
                    },
                },
                {
                    "args": ["--database-url"],
                    "kwargs": {
                        "default": None,
                        "help": (
                            "Postgres URL for the shared registry table "
                            "(falls back to SONIQ_DATABASE_URL)"
                        ),
                    },
                },
            ],
            category="observability",
        )
    )
