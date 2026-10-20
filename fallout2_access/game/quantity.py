"""The "Move Items" window: how many of a stack to move.

Fallout puts this up whenever a stack of more than one is dragged anywhere --
252 bottle caps onto a barter table, six stimpaks into a pot. It is a small
panel with an up arrow, a down arrow, Done and Cancel, and until now it was
invisible: the mod moved an item, the window appeared, and everything after
that went into a panel nobody had been told about.

**It is the same window as the explosive countdown**, which is the trap. Both
are 259x162, both carry the step buttons at 6000 and 7000, and the engine
tells them apart by a mode argument it keeps in a register. So a shape test
answers yes to both, and `timerwin.showing` did -- which meant a stack moved in
a shop was announced as a bomb being armed.

What separates them is what is underneath. The countdown is opened from the map
with nothing else on screen; this one only ever appears over an item window. So
the game mode decides, and the mode is something the engine states rather than
something inferred from a rectangle.

**The engine's own loop, read rather than guessed at.** It is one function at
0x0047688C, and it takes the mode in EAX and the size of the stack in EBX:

    mode 4   moving items      starts at 1, floor 1, one at a time
    mode 5   the countdown     starts at 60, floor 10, ten at a time, and
                               refuses anything that is not a multiple of ten

Every caller in the executable that moves an item passes 4; the only caller
that passes 5 is the one that arms a charge. That is where `STARTS_AT` comes
from -- `mov ebx, 1` at 0x004768A3 -- so the floor does not have to be forced
first the way the countdown's does. The count itself lives in that EBX for as
long as the window is up: the routine that draws it takes it as an argument and
stores it nowhere, so there is no address to point at and nothing to read.

    up      0x1770  6000    add one
    down    0x1B58  7000    take one away
    all     0x1388  5000    set it to the whole stack
    Done    0x000D    13    accept -- a keyboard code, so Enter works
    Cancel  0x001B    27    cancel -- likewise Escape

**The number can be typed, and that is how this module sets it.** At
0x00476A48 the loop takes any key from '0' to '9' as a digit of the count --
count = count * 10 + digit, clearing first if the last thing to touch the
number was a button -- and at 0x00476A7B it takes a backspace as dividing it by
ten. Both only in mode 4. So the count can be put on an exact number with no
pointer at all: backspace it down to nothing, then type what it should be.

That beats clicking the up arrow for three separate reasons. It needs no aim,
which matters more here than anywhere else in the mod, because this window is a
modal loop of the engine's own and the aim depends on a script answering a key
while that loop is running. It is one keystroke per digit instead of one aim
and a click per unit -- twenty presses to move twenty stimpaks, each one a
second of pointer-driving. And it is an ABSOLUTE value, so a count that has
drifted out of step with the screen is corrected by the next press rather than
carrying its error forward: what this module says is what the window now shows.

**It is also why Enter answered with the error sound.** Accepting is checked at
0x004768EA and takes the count only while it is between the floor and the size
of the stack; outside that it plays `iisxxxx1` -- the game's "no" -- and asks
again. Nothing the player did could put the count out of range, but the mod
could and did: after a drag it tapped numpad 0 to ask the in-game script for
the new list totals, that window was already up, and it reads numpad 0 as the
digit zero. The question "how many?" was answered "none" by the mod, silently,
before the player had touched anything. See `App._ask_totals`.
"""

from __future__ import annotations

import time
from typing import Optional

from ..input.send import FocusLost, guarded_click, guarded_tap
from . import uiwindow
from ..i18n import tr
from .. import words

PANEL_WIDTH = 259
PANEL_HEIGHT = 162

STEP_UP = 6000
STEP_DOWN = 7000
TAKE_ALL = 5000

# Both keyboard codes, and both therefore reachable without the pointer.
ACCEPT_KEY = "enter"
CANCEL_KEY = "escape"

# Where the count starts when the window opens. The engine sets this itself at
# 0x004768A3 -- `mov ebx, 1` -- for the item-move mode, so it is a fact about
# the engine rather than an assumption this module is making.
STARTS_AT = 1

# Backspaces sent before typing a number, to be sure the field is empty first.
# Each one divides the count by ten and the engine caps it at 99999, so five
# empties any number it can be holding; the sixth is there because a keystroke
# costs a hundredth of a second and a half-cleared field would type a number
# nobody asked for.
CLEAR_KEY = "backspace"
CLEAR_PRESSES = 6

# Long enough for the engine's modal loop to take the key, short enough that
# typing a three-digit number is not something the player waits through. The
# loop does nothing between keys but redraw two digits.
TYPE_SETTLE = 0.03


def showing(proc) -> bool:
    """Is a counter window open? Asked of GNW's list of OPEN windows.

    A freed window keeps its fields, so a search through the heap answers yes
    for the rest of the session once one has been used -- a mistake this
    project has already shipped once, on the save screen.
    """
    return window(proc) is not None


def window(proc):
    """The open counter window, or None. Identified by its two step buttons.

    Shape and buttons cannot separate this from the countdown, and nothing here
    tries: `screens.detect` decides which of the two is up from the game mode
    and only then asks this module. Anything that used this to mean "the
    quantity window specifically" would be wrong half the time.
    """
    win = uiwindow.live_window_with(proc, PANEL_WIDTH, PANEL_HEIGHT, STEP_UP)
    if win is None:
        return None
    return win if win.by_press(STEP_DOWN) is not None else None


class Quantity:
    """Drives the window, and knows the number because it caused it.

    `count` is only ever changed by this object, starting from the 1 the engine
    put there. It is not a reading and does not pretend to be one: the number
    is in a register in the engine's modal loop and there is nothing to read.
    What keeps that honest is that every change is TYPED as a whole number
    rather than nudged -- so if the count and the screen ever disagree, the
    next press ends the disagreement instead of preserving it.

    `most` is the size of the stack, when the caller knows it. Without it the
    count is left un-clamped rather than clamped to a guess, because the engine
    stops at the real maximum whether or not this module knows what it is --
    so an unknown maximum makes the spoken number drift high, while a wrong one
    would make it drift on every stack.
    """

    def __init__(self, proc, hwnd) -> None:
        self.proc = proc
        self.hwnd = hwnd
        self.count: int = STARTS_AT
        self.most: Optional[int] = None
        # Digits the player has typed since the count was last set any other
        # way, or "" when they have not been typing.
        self.typed = ""

    def reset(self, most: Optional[int] = None) -> None:
        self.count = STARTS_AT
        self.most = most
        self.typed = ""

    @property
    def showing(self) -> bool:
        return window(self.proc) is not None

    def _type(self, value: int) -> bool:
        """Put the count on exactly `value`, by typing it at the window.

        Checked against the OPEN window list first and every time, never
        against a remembered one. Digits sent when this window is not up do not
        vanish: in a conversation they are the reply numbers, and on the map
        they arm skills. The check is what makes this safe to bind to a key.
        """
        if self.hwnd is None or not self.showing:
            return False
        # Only as many backspaces as the field can be holding. Six every time
        # is what made each step cost the best part of a second, for a field
        # that usually holds one or two digits. The two spare cover a digit
        # the player typed that reached the engine before this did.
        clear = min(CLEAR_PRESSES, len(str(max(self.count, 0))) + 2)
        try:
            for _ in range(clear):
                guarded_tap(self.hwnd, CLEAR_KEY, settle=TYPE_SETTLE)
            for digit in str(int(value)):
                guarded_tap(self.hwnd, digit, settle=TYPE_SETTLE)
        except (FocusLost, OSError):
            return False
        return True

    def _click(self, code: int, times: int = 1) -> bool:
        """Aim once, click as many times as asked. The button does not move."""
        from .pointer import aim_ui

        win = window(self.proc)
        if win is None:
            return False
        button = win.by_press(code) or win.by_code(code)
        if button is None:
            return False
        ok, _where, _why = aim_ui(self.proc, self.hwnd, *button.centre(win))
        if not ok:
            return False
        for _ in range(times):
            guarded_click(self.hwnd, "left", settle=0.1)
            time.sleep(0.03)
        return True

    def step(self, delta: int) -> Optional[str]:
        """Up or down by `delta`. Returns what to say, or None if it failed.

        A big step stops at the end rather than refusing: ten fewer from four
        is one, not "one is the fewest" with the count left where it was.
        """
        self.typed = ""
        start = self.count if self.count > 0 else (self.most or STARTS_AT)
        want = start + delta
        if self.most is not None:
            want = min(want, self.most)
        want = max(want, STARTS_AT)
        if want == start and self.count > 0:
            if delta < 0:
                return tr("quantity.fewest", "One is the fewest.")
            return tr("quantity.all_n", "{count} is all of them.", count=self.most)
        if not self._type(want):
            return None
        self.count = want
        return self.say()

    def digit(self, d: int) -> Optional[str]:
        """A digit the player typed on the number row.

        The engine takes digits in this window itself, but whether its first
        one starts afresh or adds to the 1 it opened with depends on what last
        touched the number -- 0x00476A48 -- and the mod cannot see that. So the
        mod keeps the number the player is typing and puts the field on exactly
        that after every digit. What the player hears is then what is there.
        """
        typed = (self.typed + str(d)).lstrip("0")
        if not typed:
            self.typed = ""
            return tr("quantity.zero", "Zero is not a number of things.")
        value = int(typed)
        capped = self.most is not None and value > self.most
        if capped:
            value = self.most
            typed = str(value)
        if not self._type(value):
            return None
        self.typed = typed
        self.count = value
        if capped:
            return tr("quantity.all_n", "{count} is all of them.", count=value)
        return str(value)

    def all(self) -> Optional[str]:
        """The whole stack, through the window's own button for it.

        Worth having as its own key rather than as a lot of up presses: taking
        all of something is the common case, and the engine has a control for
        it that lands exactly on the maximum without this module needing to
        know what the maximum is. That exactness is why the button is tried
        first even though it costs an aim -- typing the number the script last
        reported would be acting on the mod's belief about the stack, where the
        button acts on the engine's knowledge of it.
        """
        if self._click(TAKE_ALL):
            if self.most is not None:
                self.count = self.most
                return self.say()
            # The engine knows the number and this module does not. Say what is
            # true rather than inventing a figure.
            self.count = -1
            return tr("quantity.all", "All of them.")
        # The aim failed, which inside this window is the likely half: it is a
        # modal loop of the engine's own. Fall back to typing, which needs
        # nothing pointed at -- but only where the stack size is known, since
        # there is no number to type otherwise.
        if self.most is not None and self._type(self.most):
            self.count = self.most
            return self.say()
        return None

    def say(self) -> str:
        if self.count < 0:
            return tr("quantity.all", "All of them.")
        if self.most is not None:
            return words.of(self.count, self.most) + "."
        return str(self.count)

    def accept(self) -> bool:
        """Take it. The engine's own key, so nothing is aimed at.

        Refuses when the window is not open. Enter is harmless on most screens
        and not on all of them, and the mod's idea of which screen is up is a
        tick behind the game's.
        """
        return self._key(ACCEPT_KEY)

    def cancel(self) -> bool:
        return self._key(CANCEL_KEY)

    def _key(self, key: str) -> bool:
        if self.hwnd is None or not self.showing:
            return False
        try:
            guarded_tap(self.hwnd, key, settle=0.2)
        except (FocusLost, OSError):
            return False
        return True
