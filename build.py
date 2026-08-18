#!/usr/bin/env python3
"""Compile the in-game scripts, and optionally install them.

    python build.py             compile scripts/*.ssl into build/
    python build.py --install   compile, then install into the game

The compiler ships with the sfall modders pack rather than with this repo, so
this looks for it and explains itself if it is missing. The compiled .int files
are committed, so nobody needs a compiler just to play -- this is for changing
the scripts.

Compiling is two passes because the packaged compiler's preprocessor has a bug
that makes a single pass fail on #include. It must also run with the working
directory set to the script folder, or `#include "sfall/..."` does not resolve.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "scripts")
BUILD = os.path.join(HERE, "build")

COMPILER_CANDIDATES = [
    r"modderspack_4.4.9\ScriptEditor\resources\compile.exe",
    r"ScriptEditor\resources\compile.exe",
    r"compile.exe",
]


def find_compiler(hint: str = "") -> str:
    roots = [hint] if hint else []
    roots += [HERE, os.path.dirname(HERE),
              r"C:\Program Files (x86)\Steam\steamapps\common\Fallout 2"]
    for root in roots:
        if not root:
            continue
        if root.lower().endswith("compile.exe") and os.path.exists(root):
            return root
        for rel in COMPILER_CANDIDATES:
            path = os.path.join(root, rel)
            if os.path.exists(path):
                return path
    return ""


HEADER_CANDIDATES = [
    r"data\scripts\sfall",
    r"modderspack_4.4.9\scripting_docs\headers",
    r"scripting_docs\headers",
]


def find_headers(hint: str = "") -> str:
    """Locate sfall's .h files.

    They are not vendored here on purpose: they belong to the sfall modders
    pack, and copying someone else's headers into this repo to save one command
    line argument is not a trade worth making. They are staged into scripts/
    for the compile and removed again, since `#include "sfall/..."` resolves
    relative to the file being compiled.
    """
    roots = [hint] if hint else []
    roots += [os.path.dirname(HERE),
              r"C:\Program Files (x86)\Steam\steamapps\common\Fallout 2"]
    for root in roots:
        if not root:
            continue
        if os.path.isdir(root) and os.path.exists(os.path.join(root, "sfall.h")):
            return root
        for rel in HEADER_CANDIDATES:
            path = os.path.join(root, rel)
            if os.path.exists(os.path.join(path, "sfall.h")):
                return path
    return ""


def compile_one(compiler: str, ssl_path: str) -> bool:
    name = os.path.basename(ssl_path)
    stem = os.path.splitext(name)[0]
    pre = "{}.preprocessed.ssl".format(stem)

    for step in ([compiler, "-P", name],
                 [compiler, pre, "-o", "{}.int".format(stem)]):
        result = subprocess.run(step, cwd=SCRIPTS, capture_output=True, text=True)
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0 or "[Error]" in output:
            print("  {}: FAILED".format(name))
            for line in output.splitlines():
                if "Error" in line or "error" in line:
                    print("    {}".format(line.strip()))
            return False

    os.makedirs(BUILD, exist_ok=True)
    shutil.move(os.path.join(SCRIPTS, "{}.int".format(stem)),
                os.path.join(BUILD, "{}.int".format(stem)))
    print("  {}: ok".format(name))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--compiler", default="", help="path to compile.exe or its folder")
    ap.add_argument("--headers", default="", help="folder holding sfall.h")
    ap.add_argument("--install", action="store_true",
                    help="run install.py afterwards")
    ap.add_argument("--game", default="", help="game folder, passed to install.py")
    args = ap.parse_args()

    compiler = find_compiler(args.compiler)
    if not compiler:
        print("Could not find compile.exe.\n"
              "It comes with the sfall modders pack, not with this repo:\n"
              "  https://sourceforge.net/projects/sfall/files/modderspack/\n"
              "Then: python build.py --compiler <path to compile.exe>\n\n"
              "You only need it to change the .ssl scripts. The compiled .int\n"
              "files in build/ are committed, so playing needs no compiler.")
        return 1

    headers = find_headers(args.headers)
    if not headers:
        print("Could not find sfall's headers (sfall.h and friends).\n"
              "They come with the modders pack, or sit in your game's\n"
              "data\\scripts\\sfall folder. Point at them with --headers.")
        return 1

    print("compiler: {}".format(compiler))
    print("headers:  {}".format(headers))
    sources = sorted(glob.glob(os.path.join(SCRIPTS, "gl_*.ssl")))
    if not sources:
        print("no scripts found in scripts/")
        return 1

    staged = os.path.join(SCRIPTS, "sfall")
    existed = os.path.isdir(staged)
    if not existed:
        shutil.copytree(headers, staged)
    try:
        ok = all(compile_one(compiler, path) for path in sources)
    finally:
        # The preprocessor leaves intermediates behind, and the staged headers
        # are not ours to keep.
        for junk in glob.glob(os.path.join(SCRIPTS, "*.preprocessed.ssl")):
            os.remove(junk)
        if not existed:
            shutil.rmtree(staged, ignore_errors=True)
    if not ok:
        return 1

    if args.install:
        cmd = [sys.executable, os.path.join(HERE, "install.py")]
        if args.game:
            cmd.append(args.game)
        return subprocess.call(cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
