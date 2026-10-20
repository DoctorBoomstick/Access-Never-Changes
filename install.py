#!/usr/bin/env python3
"""Install Access Never Changes into a Fallout 2 installation.

    python install.py                      find the game automatically
    python install.py "D:\\Games\\Fallout2"  or say where it is
    python install.py --check              report what is wrong, change nothing
    python install.py --uninstall          take the mod back out

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
        # The gl_*.int files are global scripts; this is the pattern sfall uses
        # to find them. It is sfall's own default, but a hand-edited ini may
        # have narrowed it.
        "GlobalScriptPaths": r"data\scripts\gl*.int,scripts\gl*.int,scripts\sfall\gl*.int",
        # Quick save. Not a convenience -- without it there is no way to save at
        # all, because picking a slot on the save screen needs a mouse.
        #
        # sfall's own comment on this setting says it exactly: quick saving with
        # the F6 key "without picking a slot beforehand" requires AutoQuickSave,
        # and it ships disabled. So F6 fell back to opening the save screen, and
        # a player who cannot use that screen could not make a first save, which
        # meant replaying from character creation on every single test.
        #
        # Quick saves go on their own page so that the ten ordinary slots are
        # left alone: F6 cycles through the page it is given, overwriting as it
        # goes, and that is not something to point at saves anyone is keeping.
        "ExtraSaveSlots": "1",
        "AutoQuickSave": "1",
        "AutoQuickSavePage": "1",
        # Reload, on R. sfall's own description of the setting is "a key to
        # press to reload your currently equipped weapon or use the active
        # item", and it ships disabled.
        #
        # **The engine's reload, not one the mod builds.** Fallout puts reload
        # in the same rotation as the firing modes on the weapon slot, so
        # reaching it without sight means cycling a mode nobody can read to a
        # position nobody can see, then LEFT clicking the slot -- which in any
        # other position of that rotation attacks. Every part of that is a
        # thing to get wrong. This key skips the whole of it, costs the action
        # points the engine says it costs, and needs no pointer at all.
        #
        # 19 is the DX scancode for R, which the manual's key list leaves free.
        "ReloadWeaponKey": "19",
        # **Lets the scripts call the engine's own action functions.** The
        # action menu's Use, Look, Talk and use-an-item-on are carried out by
        # calling exactly what the engine's menu calls, so nothing has to be
        # pointed at -- which is the only way to reach something drawn behind
        # a wall. sfall refuses call_offset without this, silently; the
        # scripts check it and fall back to pointing when it is off.
        #
        # 1, not 2: 2 also turns off sfall's check on which addresses may be
        # touched, and nothing here needs that.
        "AllowUnsafeScripting": "1",
        # **Which high resolution patch is in charge.**
        #
        # 1 uses sfall's built-in one; 0 hands the job to an external
        # f2_res.dll if the folder has one. Both exist in most installs, so
        # this is a live choice rather than a formality, and the Restoration
        # Project ships a ddraw.ini with it set to 0.
        #
        # The mod needs the built-in one because it needs the window and the
        # configuration to agree. Under the external patch the title bar read
        # "Fallout II @640x480x1" while f2_res.ini said 1024x768 -- so every
        # screen coordinate the mod worked out was for a screen that was not
        # there, and the pointer landed nowhere. The symptom is specific and
        # worth recognising: the map reads out perfectly, because that is the
        # script talking, and nothing that needs the mouse works at all --
        # cannot walk, cannot move an item to a hand, "cannot point at that"
        # about everything.
        #
        # Compare the two titles to tell at a glance which is running. sfall's
        # own says so: "FALLOUT II @sfall 4.4.8 : 1024x768 [DX9]".
        "HiResMode": "1",
        # **Windowed, and this is the setting that decides it -- not the one in
        # f2_res.ini.**
        #
        # sfall's own comment two lines above this option says so: "If using
        # the hi-res patch by Mash, this option will always be read from the
        # main ddraw.ini file". With HiResMode=1 above, `Mode` wins and
        # f2_res.ini's WINDOWED is simply not consulted. The installer set only
        # WINDOWED for a long time, and on any install shipping Mode=4 that was
        # a setting written, reported as written, and ignored.
        #
        # 4 is DX9 fullscreen and it breaks the pointer completely. DirectX
        # puts up a window of its own -- class D3DProxyWindow, covering the
        # screen -- and parks Fallout's real window off at -25600. Everything
        # the mod does with the mouse is then computed against a window that is
        # not on the screen, and the failure is silent: no call errors, aims
        # simply grind through their step count and give up. It presents as the
        # mod being slow, and that is exactly how it was reported.
        #
        # 5 is DX9 windowed. 6 (fullscreen windowed) is untested here and is
        # deliberately not chosen: it is a different window arrangement and the
        # thing that broke was a window arrangement.
        "Mode": "5",
    },
    "f2_res.ini": {
        # Kept, and no longer relied on. This is the external hi-res patch's
        # own switch; it is correct to set it, and it decides nothing while
        # HiResMode=1 hands the choice to ddraw.ini's Mode above.
        "WINDOWED": "1",
    },
    "fallout2.cfg": {
        # **The other half of DebugMode, and the one that was missing.**
        #
        # DebugMode=2 in ddraw.ini turns Fallout's debug patch on and points it
        # at debug.log. It does NOT decide what gets written there -- that is
        # this file's job, and sfall's own comment beside DebugMode says so:
        # "you do still need to set the appropriate lines in fallout2.cfg".
        #
        # With show_script_messages=0 the engine's own chatter reaches the log
        # and every debug_msg from gl_world.ssl is dropped on the floor. The
        # scripts run perfectly; nothing can hear them. That is indistinguishable
        # from the scripts not loading, and it cost a session to tell apart:
        # ddraw.ini was correct, the .int files were in place and up to date,
        # sfall logged a clean startup with no errors, and the log filled with
        # engine output while holding not one WORLD: line.
        #
        # A fresh install rewrites fallout2.cfg with this at 0, so it is not a
        # one-time setup step -- it comes back every time the game is
        # reinstalled, which is exactly when someone is least likely to suspect
        # a config file they did not touch.
        #
        # The symptom is a good one to recognise: with no script talking, the
        # Python side has no game mode, falls back to reading memory flags, and
        # cannot tell a loaded map from the premade-character screen -- so it
        # announces "character selection" at somebody standing in Arroyo.
        "show_script_messages": "1",
    },
}

# Three separate global scripts on purpose. Each registers its own hooks and
# repeat rate independently, so the split costs nothing -- and gl_world has hard
# crashed the engine twice during development. A bug while reading a container
# should not be able to take the hex cursor down with it.
SCRIPTS = ("gl_world.int", "gl_combat.int", "gl_inven.int", "gl_dialog.int")

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


# Where to remember the folder you actually play, when it is not one of the
# usual ones. Kept beside the code and out of git: it is a fact about this
# machine, not about the mod.
GAME_PATH_FILE = os.path.join(HERE, ".game-path")
GAME_PATH_ENV = "F2_GAME"


def chosen_game() -> Optional[str]:
    """The folder this machine has been told to use, if any."""
    env = os.environ.get(GAME_PATH_ENV, "").strip().strip('"')
    if env and looks_like_fallout2(env):
        return env
    try:
        with open(GAME_PATH_FILE, "r", encoding="utf-8") as fh:
            saved = fh.read().strip().strip('"')
    except OSError:
        return None
    return saved if saved and looks_like_fallout2(saved) else None


def find_game() -> Optional[str]:
    """The folder to install into.

    An explicit choice wins over the usual locations, and that ordering is the
    point. With two installs on one machine -- a clean one for development and
    a modded one to play -- guessing picks whichever is listed first, installs
    there, and reports complete success. The next launch then runs the copy
    that was not updated, so a fix that landed perfectly appears to have done
    nothing, and the thing you go looking at is the fix.

    Set it with `--game PATH --remember`, or the F2_GAME environment variable.
    """
    picked = chosen_game()
    if picked:
        return picked
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


BACKUP_SUFFIX = ".before-access-never-changes"


def backup(path: str) -> str:
    dest = path + BACKUP_SUFFIX
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

    if getattr(sys, "frozen", False):
        print("Ready.")
    else:
        print("Ready. Start Fallout 2, then run:  python f2access.py")
    return 0


def setting_values(lines: List[str], keys) -> Dict[str, str]:
    """The value each of `keys` has in an ini file, first occurrence wins.

    The same rule `patch_ini` writes by, so what is read back here is exactly
    what was there before it wrote.
    """
    found: Dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith(";") and "=" in stripped:
            key, value = (part.strip() for part in stripped.split("=", 1))
            if key in keys and key not in found:
                found[key] = value
    return found


def uninstall(game: str) -> int:
    """Take the scripts out and put back the settings install() changed.

    **The settings, not the files.** The backups are whole copies of each file
    from before the first install, and copying them back would also undo
    everything the player changed in the months since -- a difficulty, a
    combat speed, another mod's lines. So only the keys this mod sets are
    restored, to the values the backup holds, and the backup is then removed
    so that a later install starts from the file as it is.
    """
    problems = 0
    print("Fallout 2: {}".format(game))
    target = os.path.join(game, "data", "scripts")
    for name in SCRIPTS:
        path = os.path.join(target, name)
        if os.path.exists(path):
            try:
                os.remove(path)
                print("  script {}: removed".format(name))
            except OSError as exc:
                print("  !! script {}: {}".format(name, exc))
                problems += 1

    for filename, wanted in REQUIRED.items():
        path = os.path.join(game, filename)
        saved = path + BACKUP_SUFFIX
        if not os.path.exists(saved):
            print("  {}: no backup, left as it is".format(filename))
            continue
        if not os.path.exists(path):
            print("  {}: missing, left alone".format(filename))
            continue
        before = setting_values(read_ini(saved), wanted)
        lines = read_ini(path)
        patched, changes = patch_ini(lines, before)
        try:
            if patched != lines:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(patched) + "\n")
            os.remove(saved)
        except OSError as exc:
            print("  !! {}: {}".format(filename, exc))
            problems += 1
            continue
        for change in changes:
            print("  {}: {}".format(filename, change))
        print("  {}: restored".format(filename))

    print()
    if problems:
        print("{} problem(s) need your attention.".format(problems))
        return 1
    print("Removed.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game", nargs="?", help="path to the Fallout 2 folder")
    ap.add_argument("--check", action="store_true",
                    help="report what would change, change nothing")
    ap.add_argument("--replace-config", action="store_true",
                    help="overwrite ddraw.ini / f2_res.ini with the reference "
                         "copies instead of patching individual settings")
    ap.add_argument("--remember", action="store_true",
                    help="save this folder as the one to use from now on")
    ap.add_argument("--uninstall", action="store_true",
                    help="remove the scripts and restore the settings")
    args = ap.parse_args(argv)

    if args.remember:
        if not args.game:
            print("--remember needs a folder: install.py PATH --remember")
            return 1
        if not looks_like_fallout2(args.game):
            print("{} does not look like Fallout 2".format(args.game))
            return 1
        with open(GAME_PATH_FILE, "w", encoding="utf-8") as fh:
            fh.write(args.game)
        print("remembered: {}".format(args.game))

    game = args.game or find_game()
    if not game:
        print("Could not find Fallout 2. Pass the folder as an argument:")
        print('    python install.py "C:\\Path\\To\\Fallout 2"')
        return 1
    if args.uninstall:
        return uninstall(os.path.abspath(game))
    return install(os.path.abspath(game), args.check, args.replace_config)


if __name__ == "__main__":
    sys.exit(main())
