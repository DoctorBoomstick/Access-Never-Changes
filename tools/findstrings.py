#!/usr/bin/env python3
"""List the string literals in the mod that look like words a player hears.

    python tools/findstrings.py                 every file, counts
    python tools/findstrings.py app.py -v       one file, every string

For the locale work: what is still hard-coded English, and where. Heuristic,
not proof -- it skips docstrings, print() and log text, identifiers, and
anything with no letters in it, and leaves the judging to whoever reads it.
"""

from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "fallout2_access")

# Calls whose string arguments are never spoken.
QUIET_CALLS = {"print", "getattr", "hasattr", "setattr", "get", "startswith",
               "endswith", "split", "rsplit", "join", "replace", "strip",
               "lstrip", "rstrip", "encode", "decode", "open", "compile",
               "match", "search", "sub", "findall", "finditer", "fullmatch",
               "pack", "unpack", "unpack_from", "calcsize", "join",
               "import_module", "LoadLibrary", "Dispatch", "isinstance",
               "_log", "log", "debug", "tr", "find", "index", "count",
               "Event", "struct", "path"}
IDENT = re.compile(r"^(?:[a-z0-9]+_[a-z0-9_]*|\w+\.\w+[\w.]*|[a-z]+[A-Z]\w*|[A-Z0-9_]+_[A-Z0-9_]+)$")
WORDY = re.compile(r"[A-Za-z]{2,}")


def docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    getattr(body[0], "value", None), ast.Constant):
                out.add(id(body[0].value))
    return out


def quiet(tree):
    """Constants that sit inside a call that never speaks, or are dict keys."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (
                f.attr if isinstance(f, ast.Attribute) else "")
            if name in QUIET_CALLS:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant):
                        out.add(id(sub))
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant):
                    out.add(id(k))
        if isinstance(node, ast.Subscript):
            for sub in ast.walk(node.slice):
                if isinstance(sub, ast.Constant):
                    out.add(id(sub))
        if isinstance(node, ast.Compare):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant):
                    out.add(id(sub))
        if isinstance(node, ast.keyword) and node.arg in ("encoding", "errors", "mode"):
            out.add(id(node.value))
    return out


def strings(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    skip = docstrings(tree) | quiet(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in skip:
                continue
            text = node.value
            if not WORDY.search(text) or IDENT.match(text.strip()):
                continue
            if text.startswith("[") and "]" in text[:20]:
                continue  # "[app] ..." log prefixes
            found.append((node.lineno, text))
    return sorted(found)


def files(args):
    if args:
        return [a if os.path.isabs(a) else os.path.join(PKG, a) for a in args]
    out = []
    for folder, _dirs, names in os.walk(PKG):
        for name in names:
            if name.endswith(".py"):
                out.append(os.path.join(folder, name))
    return sorted(out)


def main(argv):
    verbose = "-v" in argv
    args = [a for a in argv if a != "-v"]
    total = 0
    for path in files(args):
        found = strings(path)
        if not found:
            continue
        total += len(found)
        print("{:5d}  {}".format(len(found), os.path.relpath(path, ROOT)))
        if verbose:
            for line, text in found:
                print("        {:5d}: {!r}".format(line, text))
    print("{:5d}  total".format(total))


if __name__ == "__main__":
    main(sys.argv[1:])
