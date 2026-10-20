#!/usr/bin/env python3
"""Freeze the mod into dist\\AccessNeverChanges\\, ready for the installer.

    python installer/freeze.py

Needs PyInstaller and everything in requirements.txt. This machine's pip cannot
reach PyPI, so in practice this runs on GitHub Actions (.github/workflows/
release.yml) and the result comes back as a build artifact.

The layout it makes is the one fallout2_access/paths.py expects:

    AccessNeverChanges\\
        AccessNeverChanges.exe
        access.ini                       from config\\access.ini
        lang\\*.ini                       from lang\\
        nvdaControllerClient64.dll       from accessible_output2
        manual.html, LICENSE
        _internal\\                       PyInstaller's; the code and its data

One folder rather than one file, on purpose: a one-file exe unpacks itself to a
temporary folder on every start, which is slower and is exactly the behaviour
antivirus heuristics dislike in a program that reads another process's memory.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NAME = "AccessNeverChanges"
DIST = os.path.join(ROOT, "dist")
OUT = os.path.join(DIST, NAME)
WORK = os.path.join(ROOT, ".pyinstaller")

sys.path.insert(0, ROOT)
from install import SCRIPTS  # noqa: E402


def data(src: str, dest: str) -> list:
    return ["--add-data", "{}{}{}".format(os.path.join(ROOT, src), os.pathsep, dest)]


def pyinstaller() -> None:
    args = [
        sys.executable, "-m", "PyInstaller",
        os.path.join(ROOT, "f2access.py"),
        "--name", NAME,
        "--onedir", "--noconsole", "--noconfirm", "--clean",
        "--distpath", DIST, "--workpath", WORK, "--specpath", WORK,
        # Imported by name at run time (memory/resolve.py), so collected whole.
        "--collect-submodules", "fallout2_access",
        # accessible_output2 loads screen reader DLLs from its own lib folder.
        "--collect-all", "accessible_output2",
        "--collect-submodules", "libloader",
        "--collect-submodules", "platform_utils",
        "--hidden-import", "pynput.keyboard._win32",
        "--hidden-import", "pynput.mouse._win32",
        "--hidden-import", "win32com.client",
        # The installer half: install.py copies these into the game.
        "--hidden-import", "install",
    ]
    args += data("fallout2_access/offsets/*.json", "fallout2_access/offsets")
    for name in SCRIPTS:
        args += data("build/" + name, "build")
    args += data("config/f2_res.ini", "config")
    subprocess.check_call(args, cwd=ROOT)


def nvda_dll() -> str:
    import accessible_output2

    lib = os.path.join(os.path.dirname(accessible_output2.__file__), "lib")
    for name in ("nvdaControllerClient64.dll", "nvda_controller_client64.dll"):
        path = os.path.join(lib, name)
        if os.path.exists(path):
            return path
    local = os.path.join(ROOT, "nvdaControllerClient64.dll")
    return local if os.path.exists(local) else ""


def assemble() -> None:
    shutil.copy2(os.path.join(ROOT, "config", "access.ini"), OUT)
    lang = os.path.join(OUT, "lang")
    os.makedirs(lang, exist_ok=True)
    for path in glob.glob(os.path.join(ROOT, "lang", "*.ini")):
        shutil.copy2(path, lang)
    dll = nvda_dll()
    if not dll:
        sys.exit("no nvdaControllerClient64.dll found in accessible_output2 or the repo")
    shutil.copy2(dll, os.path.join(OUT, "nvdaControllerClient64.dll"))
    # The manual lives in docs\ in the repo and beside the program once installed.
    shutil.copy2(os.path.join(ROOT, "docs", "manual.html"), OUT)
    shutil.copy2(os.path.join(ROOT, "LICENSE"), OUT)


def main() -> int:
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    pyinstaller()
    assemble()
    print("frozen into {}".format(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
