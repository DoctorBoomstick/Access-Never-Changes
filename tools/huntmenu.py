#!/usr/bin/env python3
"""Can the engine's own action menu be driven, and does it say where it is?

The mod reads the engine's action list and offers it, but cannot *choose* from
it: the menu is not a GNW window -- it is drawn as an oversized cursor -- so
there are no button rectangles to click, and picking an entry means moving the
pointer the right distance and letting go. Guessing that distance is exactly
the kind of thing this project refuses to do, because a release on the wrong
icon performs the wrong action on somebody and the player cannot see that it
happened.

fallout2-ce says two more globals sit beside the action list:

    0x00596C3C  the actions, one word each      -- already confirmed here
    0x00518D14  how many there are
    0x00518D1C  which one is highlighted right now

and that the highlight moves by *relative* mouse travel, roughly ten pixels per
entry, rather than by absolute position. If that is true on this build then the
menu needs no geometry at all: nudge, ask the engine which entry is lit, stop
when it is the one the player chose. Same shape as the aimer -- act only on
what the game confirms, never on where we believe we put the pointer.

This tool tests it. It holds the button on whatever the look cursor is on,
walks the pointer down in small steps, and prints what the engine says after
each one.

**It chooses nothing.** The release happens far off the menu, which is the
cancel gesture the mod already uses. Nothing is performed on the object.

    python tools/huntmenu.py               walk down 8 steps
    python tools/huntmenu.py --dy 6 --steps 16

The game must be running, focused, and the look cursor must be on something.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fallout2_access.game import actions  # noqa: E402
from fallout2_access.game.aim import Aimer  # noqa: E402
from fallout2_access.input.send import (  # noqa: E402
    FocusLost, find_game_window, is_foreground, mouse_down, mouse_up,
    move_mouse_relative,
)
from fallout2_access.memory import FALLOUT_EXE_NAMES, Process, ProcessNotFound  # noqa: E402

MENU_COUNT = 0x00518D14
MENU_INDEX = 0x00518D1C


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dy", type=int, default=10,
                    help="pixels to nudge the pointer per step")
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--settle", type=float, default=0.15)
    ap.add_argument("--wait", type=float, default=0.0, metavar="SECONDS",
                    help="wait this long for the game to come to the front "
                         "before starting -- typing at whoever is running this "
                         "takes focus away from it")
    args = ap.parse_args()

    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except ProcessNotFound as exc:
        print("not attached: {}".format(exc))
        return 2
    hwnd = find_game_window(proc.pid)
    if hwnd is None:
        print("no game window")
        return 2
    if args.wait and not is_foreground(hwnd):
        print("waiting up to {:.0f}s for the game to come to the front ..."
              .format(args.wait), flush=True)
        deadline = time.time() + args.wait
        while time.time() < deadline and not is_foreground(hwnd):
            time.sleep(0.25)
    if not is_foreground(hwnd):
        print("the game is not focused -- switch to it and run this again")
        return 2
    # It takes a moment for the game to settle after being alt-tabbed to, and
    # the first pointer move of a probe is the one most likely to be eaten.
    time.sleep(0.5)

    log_path = os.path.join(proc.directory, "debug.log")
    aimer = Aimer(hwnd, log_path)

    def state():
        return (proc.read_i32(MENU_COUNT), proc.read_i32(MENU_INDEX))

    print("at rest (no menu open):  count={} index={}".format(*state()))

    ok, _reading, why = aimer.aim()
    if not ok:
        print("could not aim: {}".format(why or "unknown"))
        return 1
    what, _at = aimer.prepare(want_object=True)
    if not what:
        print("nothing under the pointer to act on")
        return 1
    print("pointing at: {}".format(what))

    mouse_down("left")
    try:
        # The engine builds the list while the button is held. Reading before
        # it has finished gets the PREVIOUS object's menu, which is never empty
        # and so looks exactly like a good read.
        time.sleep(0.6)
        codes = actions.read_list(proc)
        count, index = state()
        print("menu open: {} ({})".format(
            [actions.name(c) for c in codes], codes))
        print("           count={} index={}  <- does count match the list?"
              .format(count, index))

        for step in range(1, args.steps + 1):
            move_mouse_relative(0, args.dy, settle=0.05, hwnd=hwnd)
            time.sleep(args.settle)
            count, index = state()
            named = (actions.name(codes[index])
                     if index is not None and 0 <= index < len(codes) else "?")
            print("  step {:>2} (+{:>3}px): index={} count={}  -> {}".format(
                step, step * args.dy, index, count, named))
    except FocusLost:
        print("focus was lost mid-probe")
    finally:
        # Cancel, exactly the way the mod cancels: step well off the strip
        # before letting go, so the release cannot land on an icon.
        move_mouse_relative(actions.CANCEL_DX, actions.CANCEL_DY,
                            settle=0.05, hwnd=hwnd)
        time.sleep(0.2)
        mouse_up("left")
        time.sleep(0.25)
    print("cancelled -- nothing was performed")
    print("at rest again:           count={} index={}".format(*state()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
