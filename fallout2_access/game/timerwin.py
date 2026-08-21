"""The explosive timer: the countdown window, and setting it by construction.

Arming a charge in Fallout 2 opens a small window with an up arrow, a down
arrow, Done and Cancel. A sighted player reads the number off it. This mod
cannot, and the search for that number is worth recording because it failed
twice in instructive ways.

**It is not in the executable's globals, and not in sfall's.** Five presses of
the increase button moved nothing in either.

**The first heap candidate was a tally, not a position.** A word beside the
window rose by exactly one on every press, which looked conclusive until the
same word rose on the DECREASE button too -- 9 to 31 going down, 31 to 57 going
up, never clamping. That is a count of clicks. It is the identical false
positive the save screen produced, where a value "tracked" the selection by
rising on both arrows, and the lesson is the same: motion is not evidence,
motion in OPPOSITE directions is.

**So the number is not read at all.** It is caused, the way the save screen's
page and the inventory's scroll position are. Pressing the down arrow more times
than the range is long leaves the timer at its minimum *whatever it started at*,
and every step after that is arithmetic this module controls. Nothing to find,
nothing to drift, and it needs no address that a patch could move.

The range is the game's: ten seconds to three minutes, in ten-second steps.
"""

from __future__ import annotations

import time
from typing import Optional

# The window, by its size and by the two buttons only it has. Size alone is not
# enough -- COUNTERWIN is also used for moving a stack of items, and setting a
# countdown when you meant to split a pile of caps is not a mistake worth
# risking.
PANEL_WIDTH = 259
PANEL_HEIGHT = 162

STEP_UP = 6000
STEP_DOWN = 7000

# Ten seconds a step, ten seconds to three minutes.
SECONDS_PER_STEP = 10
MIN_STEPS = 1
MAX_STEPS = 18

# More presses than the range is long, so the floor is reached from anywhere.
# Two extra, because a click that goes astray costs nothing here and a timer
# that is one step from where the player thinks it is costs them the charge.
REWIND_PRESSES = MAX_STEPS + 2


def seconds(steps: int) -> int:
    return steps * SECONDS_PER_STEP


def say_time(steps: int) -> str:
    """The countdown, in words a person can act on.

    Minutes once there are any, because "one hundred and twenty seconds" is a
    number you have to convert while a charge is live.
    """
    total = seconds(steps)
    if total < 60:
        return "{} seconds".format(total)
    minutes, rest = divmod(total, 60)
    name = "{} minute{}".format(minutes, "" if minutes == 1 else "s")
    if not rest:
        return name
    return "{} {} seconds".format(name, rest)


def showing(proc) -> bool:
    """Is the timer on screen right now?

    Asked of GNW's list of OPEN windows, not of a search through the heap: a
    freed window keeps its fields, so a shape search answers yes for the rest of
    the session once the timer has been used. That mistake shipped once already
    on the save screen.
    """
    from . import uiwindow
    return uiwindow.live_window_with(
        proc, PANEL_WIDTH, PANEL_HEIGHT, STEP_UP) is not None


def find(finder):
    """The timer window, or None. Identified by its two step buttons."""
    win = finder.sized(PANEL_WIDTH, PANEL_HEIGHT)
    if win is None:
        return None
    if win.by_press(STEP_UP) is None or win.by_press(STEP_DOWN) is None:
        return None
    return win


class Timer:
    """Sets the countdown by driving the window's own buttons.

    Holds the value it has *caused*, never a value it has read. That is only
    trustworthy because it starts by forcing the minimum, and because every
    change is a click this object made.
    """

    def __init__(self, proc, hwnd, finder) -> None:
        self.proc = proc
        self.hwnd = hwnd
        self.finder = finder
        self.steps: Optional[int] = None

    @property
    def showing(self) -> bool:
        return find(self.finder) is not None

    def _click(self, code: int, times: int = 1) -> bool:
        """Aim once, click as many times as asked. The button does not move."""
        from ..input.send import guarded_click
        from .pointer import MenuMouse, aim_to

        win = find(self.finder)
        if win is None:
            return False
        button = win.by_press(code)
        if button is None:
            return False
        ok, _where, _why = aim_to(self.proc, self.hwnd, *button.centre(win),
                                  reader=MenuMouse(self.proc))
        if not ok:
            return False
        for _ in range(times):
            guarded_click(self.hwnd, "left", settle=0.12)
            time.sleep(0.05)
        return True

    def rewind(self) -> bool:
        """Force the countdown to its minimum, and know that it is there.

        The whole design rests on this: after more down-presses than the range
        is long, the timer is at ten seconds no matter what it showed before.
        """
        if not self._click(STEP_DOWN, REWIND_PRESSES):
            self.steps = None
            return False
        self.steps = MIN_STEPS
        return True

    def step(self, delta: int) -> Optional[int]:
        """Move the countdown by whole steps. Returns the new value, or None.

        Refuses rather than guesses when the value is unknown -- an unknown
        countdown adjusted by one is still unknown, and this is a number the
        player is about to trust with their life.
        """
        if self.steps is None:
            return None
        want = max(MIN_STEPS, min(MAX_STEPS, self.steps + delta))
        if want == self.steps:
            return self.steps          # already at an end; nothing to send
        code = STEP_UP if want > self.steps else STEP_DOWN
        if not self._click(code, abs(want - self.steps)):
            self.steps = None
            return None
        self.steps = want
        return want
