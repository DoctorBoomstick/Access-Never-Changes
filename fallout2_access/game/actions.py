"""What the engine will let you do to the thing under the pointer.

Fallout answers this itself. Hold the button on an object and it builds a menu
of icons -- the eye, the hand, the backpack, the skilldex -- and it decides that
list from the object's own flags and type. That list is the answer to "what can
I do here", and it is the engine's answer rather than a set of rules
reimplemented over here and quietly drifting out of step.

**It is not a window.** Nothing appeared in GNW's window list when the menu was
open; Fallout draws it as an oversized mouse cursor instead. That killed the
obvious approach -- the one that reads the save screen's buttons -- and is why
this reads memory instead.

The list lives at `ACTION_LIST`, one word per icon, rebuilt and zero-terminated
every time the menu is built. Found by holding the button on an object while
running the identical pointer movements with the button UP as a control: the
world ticks either way, so the hundreds of words that move in both runs are
noise, and four consecutive words that moved only in the held run are not.

Confirmed to follow the object rather than being a constant:

    Pot          [6, 3, 2, 8]
    Stone Bench  [3, 2, 8]

A pot can be opened and a bench cannot, and the bench's list is short by exactly
one entry -- which is what identifies 6 as Use. The others are named from the
engine's own ordering; an unrecognised code is announced as a number rather than
guessed at, the same way cursor modes are.
"""

from __future__ import annotations

import struct
import time
from typing import List, Optional

# One word per available action, zero-terminated, rebuilt on every menu.
ACTION_LIST = 0x00596C3C

# The menu is a handful of icons; well past any real list, and a bound rather
# than a measurement, so it only stops a runaway read.
MAX_ACTIONS = 12

CANCEL = 0
DROP = 1
INVENTORY = 2
LOOK = 3
ROTATE = 4
TALK = 5
USE = 6
UNLOAD = 7
USE_SKILL = 8

# What to say for each. USE is the measured one -- it is the entry a Stone Bench
# does not get and a Pot does. The rest come from the engine's ordering and are
# consistent with what appeared on a container, but they have not each been
# performed and watched, so anything not in this table is reported as a bare
# number rather than named. A wrong name here would describe an action the
# player cannot check.
NAMES = {
    CANCEL: "cancel",
    DROP: "drop something here",
    INVENTORY: "use an item on it",
    LOOK: "look at it",
    ROTATE: "turn it",
    TALK: "talk to it",
    USE: "use it",
    UNLOAD: "unload it",
    USE_SKILL: "use a skill on it",
}

# How far to shove the pointer before letting go. The menu is a narrow vertical
# strip drawn at the cursor, and a release ON it CHOOSES -- so this has to be
# far enough sideways to be off it beyond doubt.
CANCEL_DX = 300
CANCEL_DY = 120


def read_list(proc) -> List[int]:
    """The actions the engine has built, in menu order.

    Only meaningful while the menu is up. Between menus the array still holds
    the last one built, so a read taken at rest describes whatever was last
    pointed at -- which is why nothing here reads it without holding the button
    first.
    """
    blob = proc.read_chunked(ACTION_LIST, 4 * MAX_ACTIONS)
    if not blob:
        return []
    out: List[int] = []
    for i in range(min(MAX_ACTIONS, len(blob) // 4)):
        code = struct.unpack_from("<i", blob, i * 4)[0]
        if code == 0:
            break                 # the terminator, and also CANCEL
        if not (0 < code < 64):
            break                 # not a menu code; stop rather than invent one
        out.append(code)
    return out


def name(code: int) -> str:
    return NAMES.get(code, "action {}".format(code))


def describe(codes) -> str:
    """One sentence listing what can be done, or that nothing can."""
    if not codes:
        return "Nothing you can do to it."
    return "You can " + ", ".join(name(c) for c in codes) + "."


def probe(proc, aimer, hwnd) -> tuple:
    """Ask the engine what it would offer for the selected object.

    Holds the button so the menu is built, reads the list, then releases well
    clear of the strip. Returns (object_name, codes, why_not).

    **The release is the dangerous half.** On the strip it chooses an action, so
    the pointer is shoved a long way sideways first. Nothing else here touches
    the world: no icon is picked and the menu is cancelled every time.
    """
    from ..input.send import mouse_down, mouse_up, move_mouse_relative

    ok, _reading, why = aimer.aim()
    if not ok:
        return None, [], why or "could not point at it"

    what, _offset = aimer.prepare(want_object=True)
    if not what:
        return None, [], "nothing under the pointer to act on"

    mouse_down("left")
    try:
        # Let the engine build the menu before reading it. Reading in the same
        # breath as the press gets the PREVIOUS object's list, which is the one
        # mistake this array makes easy: it is never empty, so a stale read
        # looks exactly like a good one.
        time.sleep(0.6)
        codes = read_list(proc)
    finally:
        move_mouse_relative(CANCEL_DX, CANCEL_DY, settle=0.05, hwnd=hwnd)
        time.sleep(0.25)
        mouse_up("left")
        time.sleep(0.3)
    return what, codes, ""
