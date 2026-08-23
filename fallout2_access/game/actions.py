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


def highlighted(proc) -> Optional[int]:
    """Which menu icon the engine has lit, or None if it cannot be read.

    Sixteen bits. See the note on MENU_INDEX.
    """
    return proc.read_i16(MENU_INDEX)


def step_toward(index: int, target: int) -> int:
    """Which way to nudge the pointer to move the highlight toward `target`.

    Down increases the index, which was measured rather than assumed -- the
    menu can be drawn above the pointer as easily as below it, and getting this
    backwards walks the highlight to the far end and performs whatever is
    sitting there.
    """
    if index == target:
        return 0
    return 1 if index < target else -1


def perform(proc, aimer, hwnd, code: int, wanted: Optional[str] = None) -> tuple:
    """Choose `code` from the engine's own action menu, on the object aimed at.

    Returns (done, why_not).

    This is how look, talk and everything else the engine offers get done:
    not by reimplementing the action, but by working the menu a sighted player
    works. What makes that safe is that the engine publishes which icon is lit,
    so the pointer is crept along and the engine asked after every step. The
    button is released only when the engine's own answer is the icon the player
    chose -- never on our belief about how far the pointer has travelled.

    If the highlight cannot be walked onto the wanted icon, nothing is chosen:
    the pointer steps well clear and releases into empty space, which is the
    cancel gesture. Failing that way round is the safe one. Releasing on the
    wrong icon does something to somebody, and there is no undo in this game.
    """
    from ..input.send import mouse_down, mouse_up, move_mouse_relative

    ok, _reading, why = aimer.aim()
    if not ok:
        return False, why or "could not point at it"
    what, _offset = aimer.prepare(want_object=True, wanted=wanted)
    if not what:
        return False, "nothing under the pointer to act on"

    mouse_down("left")
    chosen = False
    reason = ""
    try:
        # The engine builds the list while the button is held, and resets the
        # highlight to the first icon. Reading either too early gets the
        # PREVIOUS menu, which is never empty and so looks entirely valid.
        time.sleep(0.6)
        codes = read_list(proc)
        if code not in codes:
            return False, "the engine is not offering that"
        target = codes.index(code)

        stuck = 0
        for _ in range(MAX_STEPS):
            index = highlighted(proc)
            if index is None:
                reason = "cannot read which action is highlighted"
                break
            direction = step_toward(index, target)
            if direction == 0:
                chosen = True
                break
            move_mouse_relative(0, direction * STEP_PX, settle=0.05, hwnd=hwnd)
            time.sleep(0.08)
            after = highlighted(proc)
            if after == index:
                # The highlight can legitimately not move -- an icon is about
                # twenty pixels tall and a step is eight. Only give up once it
                # has refused several times running, which is what hitting the
                # end of the menu looks like.
                stuck += 1
                if stuck > 6:
                    reason = "the highlight stopped moving"
                    break
            else:
                stuck = 0
        else:
            reason = "could not reach that action"
    finally:
        if chosen:
            # Release ON the icon. This is the click that performs it.
            mouse_up("left")
            time.sleep(0.35)
        else:
            move_mouse_relative(CANCEL_DX, CANCEL_DY, settle=0.05, hwnd=hwnd)
            time.sleep(0.2)
            mouse_up("left")
            time.sleep(0.25)
    return chosen, reason


def open_menu(proc, aimer, hwnd, wanted=None) -> tuple:
    """Fill the engine's action array, then hand over to the in-game menu.

    Two halves, split where the capability is. Only Python can put the pointer
    on the object and press, which is what makes the engine work out what is
    possible; only the script can swallow the arrow keys the menu is navigated
    with. So Python does the trip and taps the key that tells the script to
    read the array and take over.

    Returns (object_name, why_not). The script announces the menu itself, so
    nothing is said here -- one voice, not two.
    """
    from ..input.send import guarded_tap, mouse_down, mouse_up, move_mouse_relative

    ok, _reading, why = aimer.aim()
    if not ok:
        return None, why or "could not point at it"
    what, _offset = aimer.prepare(want_object=True, wanted=wanted)
    if not what:
        return None, "nothing under the pointer to act on"

    mouse_down("left")
    try:
        # Let the engine work out what is possible before handing over. The
        # array is never cleared, only overwritten, so reading it too early
        # gets the PREVIOUS object's list -- and since it is never empty, a
        # stale read looks exactly like a good one.
        time.sleep(0.6)
        # Hand over while the pointer is STILL ON THE OBJECT. The script asks
        # the engine what is under the pointer, and that has to be asked before
        # the pointer is moved off -- the first version tapped this after
        # stepping aside, which left the script to guess from the hex instead,
        # and on a tile holding both a door and a stone plate it guessed wrong.
        guarded_tap(hwnd, "m", settle=0.15)
    finally:
        # Only now step away, so releasing cannot land on the object and
        # perform its default action.
        move_mouse_relative(CANCEL_DX, CANCEL_DY, settle=0.05, hwnd=hwnd)
        time.sleep(0.2)
        mouse_up("left")
        time.sleep(0.25)
    return what, ""
