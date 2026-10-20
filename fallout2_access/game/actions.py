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
from typing import List, Optional, Tuple
from ..i18n import tr

# One word per available action, zero-terminated, rebuilt on every menu.
ACTION_LIST = 0x00596C3C

# How many icons the menu is showing, and which one is lit.
#
# Measured live on Klint, whose menu is [talk, look, use an item, use a skill]:
# the count read 5, one more than the list, because the trailing zero is not
# only a terminator -- it is a real fifth icon, Cancel. And the index started
# at 0 when the menu opened, rose as the pointer went down, and stopped at 4.
#
# **The index is sixteen bits.** Read as a word it counts 0,1,2,3,4; read as a
# dword it reads 16580608 upward, because something else lives in the top half.
# That is the kind of mistake that produces a number which increments
# convincingly and means nothing at all.
MENU_COUNT = 0x00518D14
MENU_INDEX = 0x00518D1C

# How far to nudge the pointer between asking the engine what is lit. Measured
# at roughly 20 pixels per icon, so this is comfortably less than one -- the
# point is to creep up on the answer, not to predict it. Nothing here depends
# on the spacing being right: the engine is asked after every step.
STEP_PX = 8

# A bound on the walk, not a measurement. Long enough to cross any menu the
# engine builds at this spacing, short enough that a stuck index gives up
# quickly rather than dragging the pointer down the screen.
MAX_STEPS = 40

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
def names() -> dict:
    return {
        CANCEL: tr("act.cancel", "cancel"),
        DROP: tr("act.drop", "drop something here"),
        INVENTORY: tr("act.use_item_on", "use an item on it"),
        LOOK: tr("act.look", "look at it"),
        ROTATE: tr("act.rotate", "turn it"),
        TALK: tr("act.talk", "talk to it"),
        USE: tr("act.use", "use it"),
        UNLOAD: tr("act.unload", "unload it"),
        USE_SKILL: tr("act.use_skill", "use a skill on it"),
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
    return names().get(code) or tr("act.unknown", "action {code}", code=code)


def highlighted(proc) -> Optional[int]:
    """Which menu icon the engine has lit, or None if it cannot be read.

    Sixteen bits. See the note on MENU_INDEX.
    """
    return proc.read_i16(MENU_INDEX)
