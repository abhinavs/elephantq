"""
`soniq migrate-enqueue` codemod.

Rewrites a project's old-shape calls to the new shape:

    @app.job()                   ->  @app.job(name="<canonical>")
    @app.job(queue="x")          ->  @app.job(name="<canonical>", queue="x")
    app.enqueue(my_func, x=1)    ->  app.enqueue("<canonical>", args={"x": 1})

The codemod refuses to invent canonical names. Callers either supply
a ``migrate-enqueue.toml`` mapping function names -> canonical task
names, or pass ``--use-derived-names`` to fall back to ``func.__name__``
(a quick-start convenience, not the recommended path).

Exit codes:
    0   all old-shape call sites were rewritten.
    2   at least one call site had no mapping and was left untouched.
        The codemod prints a per-site diagnostic.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional


def _load_name_map(path: str) -> Dict[str, str]:
    """Read a [names] section of a TOML file mapping ident -> task name."""
    if not os.path.exists(path):
        return {}
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    section = data.get("names", {})
    if not isinstance(section, dict):
        return {}
    return {str(k): str(v) for k, v in section.items()}


def _walk_python_files(paths: List[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                if "__pycache__" in root or "/." in root:
                    continue
                for f in files:
                    if f.endswith(".py"):
                        out.append(os.path.join(root, f))
        elif p.endswith(".py"):
            out.append(p)
    return sorted(out)


def _import_engine():
    """Import the migrate_source engine. Tries the in-repo scripts/ path
    first, then falls back to a vendored copy if one is shipped beside
    this CLI command."""
    try:
        from scripts.migrate_enqueue import migrate_source

        return migrate_source
    except ImportError:
        pass
    # Repo-root fallback for editable installs.
    here = os.path.dirname(__file__)
    repo_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    sys.path.insert(0, repo_root)
    try:
        from scripts.migrate_enqueue import (
            migrate_source,  # type: ignore[import-not-found]
        )

        return migrate_source
    finally:
        sys.path.pop(0)


def run_codemod(
    paths: List[str],
    name_map: Dict[str, str],
    use_derived: bool,
    stdout: Any = None,
    stderr: Any = None,
) -> int:
    """Apply the codemod. Returns 0 on full success, 2 on any refused site."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    migrate_source = _import_engine()

    def resolver(short: str, kind: str) -> Optional[str]:
        if short in name_map:
            return name_map[short]
        if use_derived:
            return short
        return None

    files = _walk_python_files(paths)
    refused = 0
    rewrites = 0

    for path in files:
        with open(path) as fh:
            src = fh.read()
        new_src, changes = migrate_source(src, path=path, name_resolver=resolver)
        for change in changes:
            if "REFUSE:" in change:
                print(change, file=stderr)
                refused += 1
            else:
                print(change, file=stdout)
                rewrites += 1
        if new_src != src:
            with open(path, "w") as fh:
                fh.write(new_src)

    print(
        f"\nsoniq migrate-enqueue: {rewrites} rewrites across {len(files)} files; "
        f"{refused} site(s) refused (missing canonical name).",
        file=stdout,
    )
    return 0 if refused == 0 else 2


def handle_migrate_enqueue(args) -> int:
    """argparse handler for `soniq migrate-enqueue`."""
    paths = args.paths or [os.getcwd()]
    config = args.config or "migrate-enqueue.toml"
    use_derived = bool(args.use_derived_names)

    if not use_derived and not os.path.exists(config):
        print(
            f"soniq migrate-enqueue: required config file {config!r} not found. "
            f"Create it with a [names] section mapping function names to "
            f"canonical task names, or pass --use-derived-names to fall back "
            f"to func.__name__ as a quick-start convenience.",
            file=sys.stderr,
        )
        return 2

    name_map = _load_name_map(config) if os.path.exists(config) else {}
    return run_codemod(paths=paths, name_map=name_map, use_derived=use_derived)


def register_migrate_enqueue_command():
    """Register the `migrate-enqueue` command on the global CLI registry."""
    from ..registry import CLICommand, get_cli_registry

    registry = get_cli_registry()
    registry.register_command(
        CLICommand(
            name="migrate-enqueue",
            help="Rewrite old-shape enqueue/job calls to the new name-or-ref shape",
            description=(
                "Rewrite @app.job() / app.enqueue(callable, **kwargs) call sites "
                "to the new @app.job(name=...) / app.enqueue('name', args={...}) "
                "shape. By default the codemod requires a migrate-enqueue.toml "
                "file mapping function names to canonical task names; pass "
                "--use-derived-names to fall back to func.__name__ as a "
                "quick-start convenience."
            ),
            handler=handle_migrate_enqueue,
            arguments=[
                {
                    "args": ["paths"],
                    "kwargs": {
                        "nargs": "*",
                        "help": "Files or directories to rewrite (default: cwd)",
                    },
                },
                {
                    "args": ["--config"],
                    "kwargs": {
                        "default": "migrate-enqueue.toml",
                        "help": "Path to TOML config with [names] mapping",
                    },
                },
                {
                    "args": ["--use-derived-names"],
                    "kwargs": {
                        "action": "store_true",
                        "help": (
                            "Fall back to func.__name__ when no canonical "
                            "name is configured. Quick-start convenience; "
                            "the recommended path is an explicit mapping."
                        ),
                    },
                },
            ],
            category="migration",
        )
    )
