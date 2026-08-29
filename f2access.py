#!/usr/bin/env python3
"""Fallout 2 screen reader accessibility.

Run this alongside the game:

    python f2access.py

Then play. Character creation is announced as you move through it.

Numpad 0-9 belong to the in-game script (gl_world.ssl), which walks a look
cursor around the hex grid. So this mod's own hotkeys live on the numpad
*operator* keys, which the script ignores:

    Numpad +   left mouse button
    Numpad -   right mouse button (cycles the cursor mode)
    Numpad *   summary / where am I
    Numpad /   repeat the current item
    Numpad .   full description

Saving and loading use the game's own keys, not this mod's: F6 quick saves and
F7 quick loads, with no screen and no pointer involved. The mod watches the
savegame folder and says when one lands.

Hotkeys need `pip install pynput`; without it everything else still works.

The game must run WINDOWED (WINDOWED=1 in f2_res.ini). Exclusive-fullscreen
DX9 starves the low-level keyboard hook.
"""

from __future__ import annotations

import argparse
import sys
import threading

from fallout2_access.app import App
from fallout2_access.version import banner
from fallout2_access.speech.backends import get_speaker

# Numpad 0-9 are claimed by the in-game script (hex cursor movement), so the
# mod's own hotkeys live on the operator keys, which the script ignores.
# The two mouse buttons sit on numpad + and -, next to each other and
# unmistakable by feel. Everything else is a readout, so a misfire costs a
# sentence rather than an action.
HOTKEYS = {
    107: "click",     # numpad +   LEFT mouse button
    109: "rclick",    # numpad -   RIGHT mouse button (cycles the cursor mode)
    106: "summary",   # numpad *   summary / where am I
    111: "repeat",    # numpad /   repeat the current item
    110: "describe",  # numpad .   full description
    # In a conversation only. Everywhere else these belong to the hex cursor
    # inside the game, and the mod ignores them -- gl_dialog.ssl is what stops
    # the engine reading them as reply numbers while a conversation is up,
    # which it was doing: numpad 4 said the fourth thing on the list.
    #
    # **The arrows are the keys to reach for. The numpad is kept because it is
    # what the old documentation taught.** Both are bound to the same three
    # actions, and both physically produce the same virtual keys -- see
    # `key_vk` below for the trap that sat under all six of them.
    38: "dlg_prev",   # Up         previous reply
    40: "dlg_next",   # Down       next reply
    # **The numpad's three middle keys carry their own names, not the arrows'.**
    # They used to be bound straight to dlg_prev/dlg_next/dlg_say, which was
    # fine while numpad 8 and Up could only ever mean the same thing. The world
    # map broke that: there the arrow keys are the engine's own, and they scroll
    # the view, while the numpad walks this mod's cursor. One name for both keys
    # would have meant pressing Up scrolled the map AND moved the cursor, and
    # the player hearing about one of the two.
    #
    # So the physical keys are told apart here and `App._do_action` maps them
    # back together on every screen except the world map. Nothing about
    # dialogue or the Pip-Boy changes.
    104: "num8",      # numpad 8   -- Up, when Num Lock is on
    98: "num2",       # numpad 2   -- Down, when Num Lock is on
    101: "num5",      # numpad 5   re-read / back to the player
    12: "num5",       # Clear      -- numpad 5 with Num Lock off
    # The world map's cursor. A square grid has eight neighbours, so unlike the
    # hex cursor inside the game every one of these is a real direction.
    # Claimed here rather than in gl_world.ssl because on the world map the
    # script declines every key -- WORLDMAP is in its MAP_HIDDEN set -- and the
    # engine binds none of the numpad, so nothing is being taken from anybody.
    103: "wm_nw",     # numpad 7
    105: "wm_ne",     # numpad 9
    100: "wm_w",      # numpad 4
    102: "wm_e",      # numpad 6
    97: "wm_sw",      # numpad 1
    99: "wm_se",      # numpad 3
    # The scanner, on the same three keys it uses inside the game. On a map
    # gl_world.ssl reads these itself and this mod never sees them; on the world
    # map no script is listening, so they are read here.
    219: "wm_scan_prev",   # [
    221: "wm_scan_next",   # ]
    191: "wm_scan_jump",   # /
    # T is deliberately NOT here. It is the engine's own key for the town view
    # and it already works; binding it would press it twice. The mod watches
    # for that view opening instead and reads it out, which also covers the
    # other way in -- clicking your own marker on the map.
}


def key_vk(key) -> "int | None":
    """The Windows virtual key behind a pynput key event.

    **This is why the reply keys did nothing for anybody, ever.** The listener
    used to read `key.vk` and give up when it was missing, and pynput hands the
    listener two different shapes: an ordinary character key arrives as a
    `KeyCode`, which has a `vk`, while anything pynput recognises as a special
    key arrives as a `Key` enum member, which does not. `Key.up` keeps its
    virtual key one level down, in `Key.up.value.vk`.

    So `getattr(key, "vk", None)` was None for every arrow press, and the
    hotkey was dropped before any of the dialogue code ran.

    That one line accounts for the whole history of this feature. Num Lock is
    what decides which shape the numpad arrives in -- with it on, numpad 8 is a
    KeyCode with vk 104 and worked; with it off, Windows reports VK_UP, pynput
    calls that `Key.up`, and it vanished here. Which is why the keys worked for
    whoever wrote them and for nobody else, and why binding the arrows as well
    fixed nothing at all: the arrows took the same missing branch.

    Both shapes are asked, in order. Nothing else about the listener changes.
    """
    vk = getattr(key, "vk", None)
    if vk is not None:
        return vk
    # A Key enum member: the KeyCode it wraps is its value.
    return getattr(getattr(key, "value", None), "vk", None)


def start_hotkeys(app: App) -> bool:
    try:
        from pynput import keyboard  # type: ignore
    except ImportError:
        print("[hotkeys] pynput not installed; hotkeys disabled", flush=True)
        print("[hotkeys]   pip install pynput", flush=True)
        return False

    def on_press(key):
        what = HOTKEYS.get(key_vk(key))
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
        "[hotkeys] numpad +  LEFT click   |  numpad -  RIGHT click\n"
        "[hotkeys] numpad *  summary      |  numpad /  repeat    |  numpad .  describe\n"
        "[hotkeys] on a map: numpad 0-9 and the brackets are handled inside the game\n"
        "[hotkeys] on the world map: numpad 1-9 walk the cursor, [ ] / scan places",
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
    ap.add_argument(
        "--no-step-sound",
        action="store_true",
        help="do not tick once per hex while you walk",
    )
    args = ap.parse_args()

    print(banner(), flush=True)
    speaker = get_speaker(prefer=args.speech)
    app = App(speaker=speaker, require_focus=not args.any_focus,
              step_sound=not args.no_step_sound)

    if not args.no_hotkeys:
        start_hotkeys(app)

    try:
        app.run()
    except KeyboardInterrupt:
        print("\n[app] stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
