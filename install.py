#!/usr/bin/env python3
"""Install Access Never Changes into a Fallout 2 installation.

    python install.py                      find the game automatically
    python install.py "D:\\Games\\Fallout2"  or say where it is
    python install.py --check              report what is wrong, change nothing

Copies the compiled scripts into the game's script folder and makes sure the
handful of settings the mod depends on are set.

**Settings are patched, not replaced.** Dropping in a whole ddraw.ini would be
simpler, but it is 44KB of sfall configuration and a player may well have tuned
it -- combat speed, difficulty, engine fixes, mod compatibility. Overwriting all
of that to change four keys is not a trade anyone asked for. Every file touched
is backed up first, and running this twice changes nothing the second time.

Pass --replace-config if you would rather have the reference files dropped in
wholesale; the backups are made either way.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))

# The settings the mod cannot work without, and why. Anything not listed here is
# none of our business.
REQUIRED = {
    "ddraw.ini": {
        # The scripts talk to the Python side by writing to debug.log. Without
        # this they run correctly and say nothing, which is indistinguishable
        # from not running at all.
        "DebugMode": "2",
        # gl_world.int and gl_combat.int are global scripts; this is the pattern
        # sfall uses to find them. It is sfall's own default, but a hand-edited
        # ini may have narrowed it.
        "GlobalScriptPaths": r"data\scripts\gl*.int,scripts\gl*.int,scripts\sfall\gl*.int",
    },
    "f2_res.ini": {
        # Exclusive-fullscreen DirectX starves the low-level keyboard hook the
        # mod's hotkeys rely on. Windowed is not a preference here.
        "WINDOWED": "1",
    },
}

SCRIPTS = ("gl_world.int", "gl_combat.int")

GAME_MARKERS = ("fallout2.exe", "master.dat")

COMMON_LOCATIONS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Fallout 2",
    r"C:\Program Files\Steam\steamapps\common\Fallout 2",
    r"C:\GOG Games\Fallout 2",
    r"C:\Program Files (x86)\GOG Galaxy\Games\Fallout 2",
    r"C:\Program Files (x86)\Black Isle\Fallout2",
]


def looks_like_fallout2(path: str) -> bool:
    return all(
        os.path.exists(os.path.join(path, marker)) for marker in GAME_MARKERS
    )


def find_game() -> Optional[str]:
    for path in COMMON_LOCATIONS:
        if looks_like_fallout2(path):
            return path
    return None


def read_ini(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()


def patch_ini(lines: List[str], wanted: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Set each key to its wanted value, in place. Returns (lines, changes).

    Only keys that already exist are rewritten, and only when the value differs.
    A key the file has never heard of is reported rather than appended: these
    files are section-structured, and a key appended to the wrong section is
    silently ignored by the game, which is a worse outcome than being told.
    """
    changes: List[str] = []
    remaining = dict(wanted)
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith(";") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                value = remaining.pop(key)
                current = stripped.split("=", 1)[1].strip()
                if current != value:
                    changes.append("{}: {} -> {}".format(key, current or "(empty)", value))
                    out.append("{}={}".format(key, value))
                    continue
        out.append(line)
    for key, value in remaining.items():
        changes.append("MISSING: {} (expected {}) -- set it by hand".format(key, value))
    return out, changes


def backup(path: str) -> str:
    dest = path + ".before-access-never-changes"
    if not os.path.exists(dest):
        shutil.copy2(path, dest)
    return dest


def install(game: str, check_only: bool, replace_config: bool) -> int:
    problems = 0

    print("Fallout 2: {}".format(game))
    if not looks_like_fallout2(game):
        print("  !! that does not look like a Fallout 2 install "
              "(no fallout2.exe / master.dat)")
        return 1

    ddraw = os.path.join(game, "ddraw.dll")
    if not os.path.exists(ddraw):
        print("  !! sfall is not installed (no ddraw.dll). The in-game half of "
              "this mod cannot run without it.")
        problems += 1
    else:
        print("  sfall: found")

    # -- scripts -------------------------------------------------------
    target = os.path.join(game, "data", "scripts")
    for name in SCRIPTS:
        src = os.path.join(HERE, "build", name)
        if not os.path.exists(src):
            print("  !! missing build/{} -- run build.py".format(name))
            problems += 1
            continue
        dst = os.path.join(target, name)
        same = os.path.exists(dst) and open(src, "rb").read() == open(dst, "rb").read()
        if check_only:
            print("  script {}: {}".format(name, "up to date" if same else "would install"))
        elif same:
            print("  script {}: up to date".format(name))
        else:
            os.makedirs(target, exist_ok=True)
            shutil.copy2(src, dst)
            print("  script {}: installed".format(name))

    # -- settings ------------------------------------------------------
    for filename, wanted in REQUIRED.items():
        path = os.path.join(game, filename)
        if not os.path.exists(path):
            print("  !! {} not found".format(filename))
            problems += 1
            continue

        reference = os.path.join(HERE, "config", filename)
        if replace_config and os.path.exists(reference) and not check_only:
            backup(path)
            shutil.copy2(reference, path)
            print("  {}: replaced with the reference copy "
                  "(original kept alongside it)".format(filename))
            continue

        lines = read_ini(path)
        patched, changes = patch_ini(lines, wanted)
        if not changes:
            print("  {}: already correct".format(filename))
            continue
        for change in changes:
            print("  {}: {}".format(filename, change))
            if change.startswith("MISSING"):
                problems += 1
        if not check_only and patched != lines:
            backup(path)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(patched) + "\n")
            print("  {}: written (original kept alongside it)".format(filename))

    # -- stale copies --------------------------------------------------
    #
    # This mod was developed inside a game folder before it became a repo, so
    # an older copy of the Python half may still be sitting there. Running that
    # one silently gives you an old mod, and the symptom -- a fix that plainly
    # works but appears to do nothing -- is maddening to chase. Only the two
    # .int files belong in the game folder; f2access.py runs from here.
    strays = [name for name in ("f2access.py", "fallout2_access", "tools")
              if os.path.exists(os.path.join(game, name))]
    if strays:
        print()
        print("  NOTE: an older copy of the mod is in the game folder:")
        for name in strays:
            print("        {}".format(os.path.join(game, name)))
        print("        DELETE THEM. Running that copy launches, attaches and")
        print("        announces things while being an old version, so fixes")
        print("        appear to have no effect and nothing says why. It has")
        print("        cost this project several rounds of debugging.")

    print()
    if check_only:
        print("Nothing was changed (--check).")
    if problems:
        print("{} problem(s) need your attention.".format(problems))
        return 1

    print("Ready. Start Fallout 2, then run:  python f2access.py")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game", nargs="?", help="path to the Fallout 2 folder")
    ap.add_argument("--check", action="store_true",
                    help="report what would change, change nothing")
    ap.add_argument("--replace-config", action="store_true",
                    help="overwrite ddraw.ini / f2_res.ini with the reference "
                         "copies instead of patching individual settings")
    args = ap.parse_args()

    game = args.game or find_game()
    if not game:
        print("Could not find Fallout 2. Pass the folder as an argument:")
        print('    python install.py "C:\\Path\\To\\Fallout 2"')
        return 1
    return install(os.path.abspath(game), args.check, args.replace_config)


if __name__ == "__main__":
    sys.exit(main())
