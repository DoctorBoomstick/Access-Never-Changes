"""Where the mod's own files live, run from the repo or installed.

Installed, the mod is one folder inside the game's:

    <Fallout 2>\\Access Never Changes\\
        AccessNeverChanges.exe
        access.ini          the player's settings
        lang\\english.ini    every word the mod says; add a file to translate
        f2access.log
        _internal\\          the frozen program -- nothing to edit in here

The settings and the words sit BESIDE the program, as plain files, not inside
it. A translator needs to open them in Notepad and a player needs to change a
setting without rebuilding anything, and the frozen program's own folder is
neither readable nor stable across releases.

Inside the game folder because that folder is writable by whoever plays: the
game saves there. So everything here can be edited without asking for admin,
wherever the game was installed.

Run from the repo, the same names resolve against the repo root instead, so
`python f2access.py` reads the same `lang\\` and `access.ini` the installer
ships.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

CONFIG_NAME = "access.ini"
LANG_DIR_NAME = "lang"
LOG_NAME = "f2access.log"
INSTALL_LOG_NAME = "install.log"

GAME_MARKERS = ("fallout2.exe", "master.dat")


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """The folder the player sees: beside the exe, or the repo root."""
    if frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_path() -> str:
    return os.path.join(app_dir(), CONFIG_NAME)


def lang_dir() -> str:
    return os.path.join(app_dir(), LANG_DIR_NAME)


def log_path() -> str:
    return os.path.join(app_dir(), LOG_NAME)


def install_log_path() -> str:
    return os.path.join(app_dir(), INSTALL_LOG_NAME)


def looks_like_fallout2(path: str) -> bool:
    return bool(path) and all(
        os.path.exists(os.path.join(path, m)) for m in GAME_MARKERS)


def game_dir(configured: str = "") -> Optional[str]:
    """The game this copy belongs to: the setting, else the folder it sits in."""
    configured = (configured or "").strip().strip('"')
    if configured and looks_like_fallout2(configured):
        return configured
    parent = os.path.dirname(app_dir())
    return parent if looks_like_fallout2(parent) else None
