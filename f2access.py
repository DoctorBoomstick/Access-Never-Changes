#!/usr/bin/env python3
"""Fallout 2 screen reader accessibility.

Run this alongside the game:

    python f2access.py

Then play. Character creation is announced as you move through it.

Numpad 0-9 belong to the in-game script (gl_world.ssl), which walks a look
cursor around the hex grid. So this mod's own hotkeys live on the numpad
*operator* keys, which the script ignores:

    Numpad *   left click where the game cursor is
    Numpad -   right click (toggles the movement/command cursor)
    Numpad /   repeat the current item
    Numpad +   summary / where am I
    Numpad .   full description

Hotkeys need `pip install pynput`; without it everything else still works.

The game must run WINDOWED (WINDOWED=1 in f2_res.ini). Exclusive-fullscreen
DX9 starves the low-level keyboard hook.
"""

from __future__ import annotations

import argparse
import sys
import threading

from fallout2_access.app import App
from fallout2_access.speech.backends import get_speaker

# Numpad 0-9 are claimed by the in-game script (hex cursor movement), so the
# mod's own hotkeys live on the operator keys, which the script ignores.
HOTKEYS = {
    106: "click",     # numpad *   left click where the game cursor is
    109: "rclick",    # numpad -   right click (toggles movement/command cursor)
    111: "repeat",    # numpad /   repeat current item
    107: "summary",   # numpad +   summary / where am I
    110: "describe",  # numpad .   full description
}


def start_hotkeys(app: App) -> bool:
    try:
        from pynput import keyboard  # type: ignore
    except ImportError:
        print("[hotkeys] pynput not installed; hotkeys disabled", flush=True)
        print("[hotkeys]   pip install pynput", flush=True)
        return False

    def on_press(key):
        vk = getattr(key, "vk", None)
        what = HOTKEYS.get(vk)
        if not what:
            return
        if app.require_focus and not app._active():
            return
        try:
            app.action(what)
        except Exception as exc:  # a hotkey must never kill the listener
            print("[hotkeys] {}".format(exc), flush=True)

    listener = keyboard.Listener(on_press=on_press, suppress=False)
    listener.daemon = True
    listener.start()
    print(
        "[hotkeys] numpad *  left click   |  numpad -  right click\n"
        "[hotkeys] numpad /  repeat       |  numpad +  summary   |  numpad .  describe\n"
        "[hotkeys] (numpad 0-9 are handled inside the game by gl_world.ssl)",
        flush=True,
    )
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--speech", help="force a backend: nvda, sapi, accessible_output2")
    ap.add_argument(
        "--any-focus",
        action="store_true",
        help="announce even when the game is not the foreground window",
    )
    ap.add_argument("--no-hotkeys", action="store_true")
    args = ap.parse_args()

    speaker = get_speaker(prefer=args.speech)
    app = App(speaker=speaker, require_focus=not args.any_focus)

    if not args.no_hotkeys:
        start_hotkeys(app)

    try:
        app.run()
    except KeyboardInterrupt:
        print("\n[app] stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
