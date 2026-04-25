"""
One-shot migration helper for the soniq cross-service-enqueue work.

Rewrites the old call shapes to the new ones:

    @app.job()                  ->  @app.job(name="<func_name>")
    @app.job(queue="x")         ->  @app.job(name="<func_name>", queue="x")
    app.enqueue(my_func)        ->  app.enqueue("my_func")
    app.enqueue(my_func, x=1)   ->  app.enqueue("my_func", args={"x": 1})
    app.enqueue(f, x=1, queue="u")
                                 ->  app.enqueue("f", args={"x": 1}, queue="u")
    app.schedule(my_func, ...)  ->  app.schedule("my_func", ...)
    soniq.enqueue(my_func, ...) ->  soniq.enqueue("my_func", ...)

The migrator is line-based for surgical edits; it uses `ast` only to
find call locations. Enqueue-option kwargs (queue, priority,
scheduled_at, unique, dedup_key, connection, run_at, run_in) stay at
the top level; everything else collapses into ``args={...}``.

This is a development tool used to migrate the repo's own tests. It
is intentionally simple: it does *not* handle every edge case (e.g.
splat args, dynamic decorators, ``app = SomeContainer.app`` chains).
For the user-facing codemod see ``soniq migrate-enqueue``.

Usage:
    python3 scripts/migrate_enqueue.py [paths...]

Edits are in-place. Run from the repo root.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from typing import List, Tuple

ENQUEUE_OPTIONS = {
    "queue",
    "priority",
    "scheduled_at",
    "unique",
    "dedup_key",
    "connection",
    "run_at",
    "run_in",
}


def _decorator_name(dec: ast.expr) -> str | None:
    """Return the decorator's call-name as ``app.job`` / ``soniq.job``."""
    if isinstance(dec, ast.Call):
        return _attr_name(dec.func)
    return _attr_name(dec)


def _attr_name(node: ast.expr) -> str | None:
    """Return ``a.b.c`` for an ast.Attribute chain, else None."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    else:
        return None
    return ".".join(reversed(parts))


def _is_job_decorator(dec: ast.expr) -> bool:
    name = _decorator_name(dec)
    return name in {"app.job", "soniq.job"}


def _has_name_kwarg(call: ast.Call) -> bool:
    return any(kw.arg == "name" for kw in call.keywords)


def _func_short_name(node: ast.expr) -> str | None:
    """For ``app.enqueue(foo)`` / ``app.enqueue(mod.foo)`` return ``foo``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _replace_in_source(src: str, edits: List[Tuple[int, int, str]]) -> str:
    """Apply (start, end, replacement) edits in reverse order."""
    edits = sorted(edits, key=lambda e: (e[0], e[1]), reverse=True)
    out = src
    for start, end, replacement in edits:
        out = out[:start] + replacement + out[end:]
    return out


def _line_col_to_offset(src: str, line: int, col: int) -> int:
    """ast lineno is 1-based; col_offset is 0-based byte offset."""
    lines = src.split("\n")
    return sum(len(ln) + 1 for ln in lines[: line - 1]) + col


def _node_range(src: str, node: ast.AST) -> Tuple[int, int]:
    start = _line_col_to_offset(src, node.lineno, node.col_offset)
    end = _line_col_to_offset(src, node.end_lineno, node.end_col_offset)
    return start, end


def _migrate_job_decorator(src: str, dec: ast.expr) -> str | None:
    """Return replacement text for a @app.job(...) or @soniq.job(...) decorator
    that is missing name=. The decorator targets the next function whose name
    we know from the parent FunctionDef (caller passes it in via closure).
    """
    raise NotImplementedError("handled inline; this is a placeholder for clarity")


def migrate_source(src: str, path: str = "<input>") -> Tuple[str, List[str]]:
    """Return (new_source, list_of_changes) for a single file's source."""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return src, [f"{path}: parse error: {e}"]

    edits: List[Tuple[int, int, str]] = []
    changes: List[str] = []

    # Walk the AST. For every FunctionDef / AsyncFunctionDef, examine its
    # decorators (the @app.job ones). For every Call expression, examine
    # whether it's an enqueue/schedule call.
    for node in ast.walk(tree):
        # ----- @app.job / @soniq.job on a function definition -----
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if not _is_job_decorator(dec):
                    continue
                # Bare reference like @app.job (no parens) - skip; that was
                # never valid soniq usage.
                if not isinstance(dec, ast.Call):
                    continue
                if _has_name_kwarg(dec):
                    continue
                # Compute the source range of the call's argument list.
                # We rewrite (...) -> (name="<func_name>", ...).
                start, end = _node_range(src, dec)
                # Find the opening "(" within this range.
                snippet = src[start:end]
                paren_off = snippet.find("(")
                if paren_off < 0:
                    continue
                close_paren_off = snippet.rfind(")")
                inner = snippet[paren_off + 1 : close_paren_off].strip()
                if inner:
                    new_inner = f'name="{node.name}", {inner}'
                else:
                    new_inner = f'name="{node.name}"'
                new_call = (
                    snippet[: paren_off + 1] + new_inner + snippet[close_paren_off:]
                )
                edits.append((start, end, new_call))
                changes.append(
                    f"{path}:{dec.lineno}: add name={node.name!r} to {snippet[:paren_off]}"
                )

        # ----- app.enqueue / soniq.enqueue / app.schedule / soniq.schedule -----
        if isinstance(node, ast.Call):
            method_name = _attr_name(node.func)
            if method_name not in {
                "app.enqueue",
                "soniq.enqueue",
                "app.schedule",
                "soniq.schedule",
            }:
                continue
            # Skip calls that already use the new shape: first arg is a
            # string literal.
            if not node.args:
                continue
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                continue
            short = _func_short_name(first_arg)
            if not short:
                # Computed first arg; skip.
                continue
            # Collect the kwargs and split into args/options.
            args_kwargs: List[Tuple[str, ast.expr]] = []
            option_kwargs: List[Tuple[str, ast.expr]] = []
            for kw in node.keywords:
                if kw.arg is None:
                    # **splat - bail on this call.
                    args_kwargs = []
                    option_kwargs = []
                    short = None
                    break
                if kw.arg in ENQUEUE_OPTIONS:
                    option_kwargs.append((kw.arg, kw.value))
                else:
                    args_kwargs.append((kw.arg, kw.value))
            if short is None:
                continue
            # Rebuild the call:
            #   <prefix>(<"short">, args={<k>: <v>, ...}, <option_k>=<v>, ...)
            # We do this by source-substring slicing: replace from the start
            # of the first positional argument through end-of-call, preserving
            # the leading `app.enqueue(` text.
            call_start, call_end = _node_range(src, node)
            call_text = src[call_start:call_end]
            paren_open = call_text.find("(")
            if paren_open < 0:
                continue
            paren_close = call_text.rfind(")")
            prefix = call_text[: paren_open + 1]
            suffix = call_text[paren_close:]

            parts: List[str] = [f'"{short}"']
            if args_kwargs:
                items = ", ".join(f'"{k}": {ast.unparse(v)}' for k, v in args_kwargs)
                parts.append(f"args={{{items}}}")
            for k, v in option_kwargs:
                parts.append(f"{k}={ast.unparse(v)}")

            new_call = prefix + ", ".join(parts) + suffix
            edits.append((call_start, call_end, new_call))
            changes.append(f"{path}:{node.lineno}: rewrite {method_name}({short}, ...)")

    if not edits:
        return src, changes
    return _replace_in_source(src, edits), changes


def main(paths: List[str]) -> int:
    py_files: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                # Skip hidden dirs and __pycache__
                if "__pycache__" in root or "/." in root:
                    continue
                for f in files:
                    if f.endswith(".py"):
                        py_files.append(os.path.join(root, f))
        else:
            py_files.append(p)

    py_files = [
        p
        for p in py_files
        if not p.endswith("scripts/migrate_enqueue.py") and "/__pycache__/" not in p
    ]

    total_changes = 0
    for path in sorted(py_files):
        with open(path) as fh:
            src = fh.read()
        new_src, changes = migrate_source(src, path=path)
        if changes:
            for c in changes:
                print(c)
            total_changes += len(changes)
        if new_src != src:
            with open(path, "w") as fh:
                fh.write(new_src)
    print(f"\n{total_changes} edits across {len(py_files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["."]))
