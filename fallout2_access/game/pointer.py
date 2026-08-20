"""Put the pointer on a screen point, and know that it got there.

The hex aimer in `aim.py` solves a harder version of this: it has to invert a
skewed isometric mapping it learns as it goes, because a tile number says
nothing about where the tile is drawn. A button is not like that. It has a
rectangle in screen pixels, so the only thing in the way is that the pointer
cannot be *placed* -- Fallout tracks its cursor from relative DirectInput
motion and ignores SetCursorPos entirely, and Windows accelerates relative
motion so the same command travels a different distance each time.

So this is the same shape of solution and a much simpler instance of it: nudge,
read where the pointer actually ended up, correct. It converges in a few steps
and, like the hex aimer, it reports whether it truly arrived rather than
assuming.

**Where the reading comes from, and why it is not memory.** The engine does keep
its cursor in a static pair of ints, and `GameMouse` reads them -- found by
asking the game where its pointer was and searching for exactly that pair, then
nudging and keeping only the candidates that still tracked.

Those addresses are correct and reading them is nearly free, which is why the
first version of this servo used them and why it did not work. The value is
refreshed when the engine processes an *input event*, not when the mouse moves:
synthetic motion sits in DirectInput's buffer until something makes the game
look. Nudge and read back and you are watching a number measured at fifteen
seconds stale, which the servo faithfully reported as "the pointer will not
move" while the pointer was moving exactly as commanded.

Tapping a key forces that refresh and returns the answer in the same breath,
which is what `ScriptMouse` does and what the hex aimer in `aim.py` has always
done -- it reads through a keypress per iteration and consequently never met
this problem. `GameMouse` stays for cheap one-off checks where nothing is being
driven; anything running a servo wants `ScriptMouse`.
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional, Tuple

from ..input.send import guarded_tap, move_mouse_relative, require_focus

# The engine's cursor position, x at the address and y four bytes later.
# Confirmed live against the game's own report: the script asks sfall where the
# pointer is, and these read back exactly the same numbers across every move
# tried, including while pinned against a screen edge.
MOUSE_X = 0x006AC750
# The same pair, elsewhere in the engine's data, and a genuine cross-check.
#
# Two other addresses survived the first narrowing and are deliberately NOT
# here. 0x00596C64 sat frozen at (688,532) -- it matched once, while the pointer
# happened to be still, and never moved again; treating it as a mirror made the
# integrity check fail every single time and reported a wrong address when the
# address was fine. A candidate that agrees once is a coincidence, not a
# confirmation, and only the ones that tracked through motion are kept.
MOUSE_MIRRORS = (0x006ABD74,)

# Close enough. Buttons here are tens of pixels across, so chasing the last
# pixel only risks oscillation for no gain.
TOLERANCE = 2

# Steps are kept SMALL on purpose, and this is the whole trick.
#
# Windows accelerates relative motion, and it accelerates it superlinearly: a
# single 278-pixel command was measured travelling about 720 pixels, which threw
# the pointer into a screen corner where it stuck and no amount of damping got
# it back. Small commands are barely accelerated at all, so a stride of a few
# dozen pixels behaves close to one-for-one and the servo converges instead of
# thrashing. It costs more steps and each step is cheap.
MAX_STEPS = 60
MAX_NUDGE = 48

# How far to step off a target the pointer already sits on, so that the
# engine sees motion arriving at it rather than a click out of nowhere.
NUDGE_OFF = 12


class GameMouse:
    """Where the engine thinks its pointer is."""

    def __init__(self, proc) -> None:
        self.proc = proc

    def read(self) -> Optional[Tuple[int, int]]:
        x = self.proc.read_i32(MOUSE_X)
        y = self.proc.read_i32(MOUSE_X + 4)
        if x is None or y is None:
            return None
        return x, y

    def agrees(self) -> bool:
        """Do the mirrors still say the same thing?

        Only meaningful when the pointer is STILL. The mirrors were found by
        sampling a settled pointer, and they matched; sampled mid-motion they
        diverge, which means they are not one variable read three ways but
        several related ones -- a current position and something lagging it by a
        frame or an event.

        So this is a diagnostic to run when nothing is moving, not a gate on the
        servo. Using it as a gate made every aim fail with a confident message
        about the address being wrong, when the address was fine and the check
        was measuring motion.
        """
        here = self.read()
        if here is None:
            return False
        for mirror in MOUSE_MIRRORS:
            x = self.proc.read_i32(mirror)
            y = self.proc.read_i32(mirror + 4)
            if (x, y) != here:
                return False
        return True


# How long to wait for the engine to notice a nudge before calling it a stall.
#
# Measured, and it is the whole reason an earlier version reported "the pointer
# will not move" while the pointer was moving perfectly well: three nudges were
# sent 120ms apart and the reading did not change once, yet the total
# displacement across them was exactly right. The moves were all landing and
# accumulating; the engine simply had not got round to updating the value the
# mod was reading. Reading back immediately measures our own impatience.
SETTLE_TIMEOUT = 0.5
SETTLE_POLL = 0.02


# The cursor BEFORE a game is loaded -- the main menu and the load screen.
#
# A separate pair from the in-game one, and it has to be: in-game the mod reads
# 0x006AC750, which at the menu sits frozen at dead centre for ever. These two
# track properly there, and they are eight bytes apart rather than adjacent,
# which is why they were disambiguated by moving one axis at a time instead of
# assuming a neighbouring pair.
#
# They also update PROMPTLY, unlike the in-game one -- so the menu can be
# servoed by reading memory, which is just as well, because there is no script
# running to ask before a game loads.
MENU_MOUSE_X = 0x006AC794
MENU_MOUSE_Y = 0x006AC79C


class MenuMouse:
    """Where the pointer is, before a game is loaded."""

    def __init__(self, proc) -> None:
        self.proc = proc

    def read(self) -> Optional[Tuple[int, int]]:
        x = self.proc.read_i32(MENU_MOUSE_X)
        y = self.proc.read_i32(MENU_MOUSE_Y)
        if x is None or y is None:
            return None
        return x, y


class ScriptMouse:
    """Where the pointer is, according to the game itself.

    Slower than reading memory and the only thing that actually works, for a
    reason worth writing down: the engine's cursor variable is refreshed when
    the game processes an INPUT EVENT, not when the mouse physically moves.
    Synthetic motion sits in DirectInput's buffer until something makes the
    game look, so a servo that only nudges and reads back watches a stale number
    -- measured at fifteen seconds behind, which the aim quite reasonably
    reported as "the pointer will not move".

    Tapping a key both forces that refresh and gets the answer, which is why the
    hex aimer -- which has always tapped a key per iteration -- never hit this.
    This is the same trick applied to UI targets, using the calibrate line that
    gl_world.ssl emits with a panel open.
    """

    LINE = re.compile(r"WORLD:(?:ui)?calib mouse=(-?\d+),(-?\d+)")

    def __init__(self, hwnd: int, log_path: str) -> None:
        self.hwnd = hwnd
        self.log_path = log_path
        self._pos: Optional[int] = None

    def _tail(self) -> str:
        try:
            size = os.path.getsize(self.log_path)
        except OSError:
            return ""
        if self._pos is None or self._pos > size:
            self._pos = size
            return ""
        with open(self.log_path, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(self._pos)
            chunk = fh.read()
            self._pos = fh.tell()
        return chunk

    def read(self, timeout: float = 0.6) -> Optional[Tuple[int, int]]:
        self._tail()                      # discard anything stale first
        guarded_tap(self.hwnd, "apostrophe", settle=0.05)
        deadline = time.time() + timeout
        found = None
        while time.time() < deadline:
            for line in self._tail().splitlines():
                m = self.LINE.search(line)
                if m:
                    found = (int(m.group(1)), int(m.group(2)))
            if found:
                return found
            time.sleep(0.02)
        return found


def _await_change(mouse, before: Tuple[int, int]
                  ) -> Optional[Tuple[int, int]]:
    """Wait for the engine to catch up with the last nudge."""
    deadline = time.time() + SETTLE_TIMEOUT
    while time.time() < deadline:
        now = mouse.read()
        if now is None:
            return None
        if now != before:
            return now
        time.sleep(SETTLE_POLL)
    return mouse.read()


def aim_to(proc, hwnd: int, x: int, y: int,
           tolerance: int = TOLERANCE, log_path: Optional[str] = None,
           reader=None) -> Tuple[bool, Optional[Tuple[int, int]], str]:
    """Move the pointer to a client-area point.

    Returns (ok, where_it_ended_up, why_not). `ok` is only True when the engine
    itself says the pointer is there -- never on our own belief about how far a
    nudge travelled.
    """
    # The game must be foreground before any of this means anything. Synthetic
    # motion reaches the engine's cursor only while it is the active window --
    # measured the hard way: an aim that never moved the pointer a single pixel
    # across fourteen steps, because the earlier readings had only worked at all
    # thanks to a keystroke that took focus as a side effect.
    require_focus(hwnd)

    # The script reader when we can have it: memory alone reads a value the
    # engine only refreshes when it processes input, so a pure nudge-and-read
    # servo watches a number that is many seconds behind the truth.
    mouse = reader or (ScriptMouse(hwnd, log_path) if log_path else GameMouse(proc))

    # How much engine motion one pixel of commanded motion produces. Windows
    # acceleration makes this vary, so it is measured every step rather than
    # assumed; this is only a starting guess.
    scale = 1.5
    stalls = 0
    moved_at_all = False

    for _ in range(MAX_STEPS):
        here = mouse.read()
        if here is None:
            return False, None, "cannot read the pointer position"
        dx, dy = x - here[0], y - here[1]
        if abs(dx) <= tolerance and abs(dy) <= tolerance:
            if moved_at_all:
                return True, here, ""
            # Already there, and nothing has been sent. That is not the same as
            # having arrived: GNW tracks which button the pointer entered, and a
            # click with no motion in front of it lands on a button the engine
            # does not think is hovered. Measured -- the pointer sat exactly on
            # a page control, the click was sent, and the page did not turn.
            #
            # So step off and come back, which costs two nudges and makes
            # "the pointer is on it" mean the engine agrees.
            move_mouse_relative(-NUDGE_OFF, 0, settle=0.04, hwnd=hwnd)
            time.sleep(0.03)
            moved_at_all = True
            continue
        moved_at_all = True

        # Aim at the remaining distance, but never stride further than the cap.
        # There is deliberately no damping term: overshoot here comes from
        # acceleration on a long stride, not from too high a gain, so the cure
        # is a short stride. Damping made it worse -- it shrank the steps that
        # would have walked the pointer back out of the corner it had been
        # thrown into, and then gave up.
        step_x = int(round(dx / scale))
        step_y = int(round(dy / scale))
        step_x = max(-MAX_NUDGE, min(MAX_NUDGE, step_x))
        step_y = max(-MAX_NUDGE, min(MAX_NUDGE, step_y))
        if step_x == 0 and dx:
            step_x = 1 if dx > 0 else -1
        if step_y == 0 and dy:
            step_y = 1 if dy > 0 else -1

        move_mouse_relative(step_x, step_y, settle=0.02, hwnd=hwnd)

        after = _await_change(mouse, here)
        if after is None:
            return False, here, "lost sight of the pointer"
        if after == here:
            # Really did not budge, even after waiting. Against a screen edge it
            # cannot, and the engine clamps hard there. The next step aims
            # somewhere else anyway, so tolerate a few rather than concluding
            # the pointer is broken.
            stalls += 1
            if stalls > 8:
                return False, after, "the pointer will not move"
            continue
        stalls = 0
        moved = abs(after[0] - here[0]) + abs(after[1] - here[1])
        asked = abs(step_x) + abs(step_y)
        # Learn the acceleration from what the nudge actually achieved. Only
        # from strides big enough for the ratio to mean something -- a one-pixel
        # step measures rounding, not acceleration.
        if asked >= 6:
            scale = max(0.5, min(6.0, float(moved) / asked))

    here = mouse.read()
    return False, here, "could not settle on that point"
