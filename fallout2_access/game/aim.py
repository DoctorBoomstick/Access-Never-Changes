"""Put the mouse pointer on a chosen hex.

Fallout 2 only walks where you click, so a blind player needs the pointer moved
onto a hex they picked by keyboard. Two facts, both measured rather than
assumed, shape how this works.

**The view will not come to the pointer.** `tile_set_center` scrolls the map,
but the view snaps back to being centred on the player, so the original design
-- park the look cursor at screen centre and click the middle -- could never
work. Measurements show the hex under a stationary pointer tracking the
*player's* tile with a fixed offset of about two hex rows. So the pointer has to
go to the hex instead.

**Pointer motion is accelerated, so position cannot be computed.** Sending a
60-pixel delta moved the cursor 59 pixels once and 87 pixels the next time --
Windows pointer acceleration. Anything that calculates "the target is 214 pixels
right" and sends that will miss, and miss differently each time.

So this servos with feedback. Numpad 2 makes the in-game script report the
pointer position, the hex under it and the look cursor together, in one line, so
each iteration measures where it actually ended up rather than trusting where it
aimed. It converges in a handful of steps and, crucially, it *verifies*: the
caller is told whether the pointer really is on the requested hex. Nothing
clicks on a maybe.
"""

from __future__ import annotations

import re
import time
from typing import NamedTuple, Optional

from ..input.send import guarded_tap, move_mouse_relative, park_pointer

# Fallout 2's tile numbering is row-major with 200 tiles to a row, so a tile
# number splits into a row and a column that behave like coordinates. The screen
# axes are skewed relative to them (the map is drawn isometrically), which is
# what the matrix below is for.
TILES_PER_ROW = 200

_TARGET = re.compile(r"COMBAT:target (\d+)\|(\d+)\|([^|]*)")

# How far above a hex to look for the critter standing on it, in pixels. Fallout
# picks critters by their drawn sprite rather than by the tile they occupy, so
# the pointer has to be on the figure, not on the ground beneath it.
#
# These are search steps, NOT a fixed offset, and that distinction was expensive:
# a hardcoded 12 pixels hit one ant and sailed clean over another. The engine is
# asked at each step whether it can see a target, so critter size, stance and
# screen position stop mattering.
TARGET_STEPS = (0, -4, -8, -12, -16, -20, -26, -32)

_CALIB = re.compile(
    r"WORLD:calib mouse=(-?\d+),(-?\d+) btns=(-?\d+) under=(-?\d+) "
    r"cursor=(-?\d+) match=(-?\d+) screen=(\d+)x(\d+) obj=([^|]*)\|"
)

# Verified end to end against a live game on 2026-08-19: cursor holds at 0
# across four consecutive world reads, the aim matches the chosen hex, the click
# lands with cursor 0, and the player walks 17488 -> 17687 -> 17686. With
# Lockpick armed, the skill survives stepping the look cursor and a full aim.

# Screen-pixel motion to (row, column) motion, measured live: 59 pixels right
# moved one row down and two columns back; 87 pixels down moved five rows and
# three columns. These are only a starting guess -- the servo re-measures the
# response on every iteration and corrects itself, so they need to be roughly
# right, not exactly right.
J_ROW_PER_X = 0.016
J_COL_PER_X = -0.031
J_ROW_PER_Y = 0.063
J_COL_PER_Y = 0.040

# Keep the pointer away from the window edges. Fallout scrolls the map when the
# pointer reaches a screen edge, which would move the very thing being aimed at,
# and the interface bar along the bottom swallows clicks entirely.
MARGIN = 80
BOTTOM_MARGIN = 180

MAX_STEPS = 10
MAX_NUDGE = 320  # pixels per step; a whole-screen lunge overshoots wildly


class Reading(NamedTuple):
    x: int
    y: int
    under: int      # hex the pointer is over
    look: int       # hex the player selected with the numpad
    width: int
    height: int
    obj: str        # what the engine says a click would act on, "" for nothing

    @property
    def on_target(self) -> bool:
        return self.under == self.look


def _rowcol(tile: int):
    return divmod(tile, TILES_PER_ROW)


class Aimer:
    """Drives the pointer onto the look cursor's hex, and says whether it got there."""

    def __init__(self, hwnd: int, log_path: str) -> None:
        self.hwnd = hwnd
        self.log_path = log_path
        self._pos = None
        # Learned response, refined as we go.
        self.j = [J_ROW_PER_X, J_COL_PER_X, J_ROW_PER_Y, J_COL_PER_Y]

    # -- sensing --------------------------------------------------------

    def _tail(self) -> str:
        import os

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

    def read(self, timeout: float = 0.8) -> Optional[Reading]:
        """Ask the game where the pointer is. None if it did not answer."""
        self._tail()  # discard anything stale first
        guarded_tap(self.hwnd, "numpad2", settle=0.06)
        deadline = time.time() + timeout
        found = None
        while time.time() < deadline:
            for line in self._tail().splitlines():
                m = _CALIB.search(line)
                if m:
                    found = Reading(
                        x=int(m.group(1)), y=int(m.group(2)),
                        under=int(m.group(4)), look=int(m.group(5)),
                        width=int(m.group(7)), height=int(m.group(8)),
                        obj=m.group(9).strip(),
                    )
            if found:
                return found
            time.sleep(0.03)
        return None

    def confirm_object(self):
        """Nudge upward until the engine says a click would act on something.

        DISABLED while `obj=` is empty. Calibration no longer asks
        obj_under_cursor, because that query changes the action cursor as a side
        effect and calibration is what the aim servo runs several times per
        click -- so verifying an object cost every click its cursor mode. The
        combat path still verifies through HOOK_TARGETOBJECT, which is a hook
        rather than a query and disturbs nothing.

        Returns (name, dy), or (None, dy) if nothing was ever reported. The
        caller must not click on (None, ...) when it expected an object: an
        unconfirmed click acts on empty ground and, in combat, spends the action
        points anyway.

        Fallout picks objects by their drawn sprite, which stands above the hex
        they occupy, so a pointer sitting dead centre on a hex is aimed at the
        ground beneath whatever is standing there. The offset is searched for
        rather than assumed -- a fixed 12 pixels landed on one ant and sailed
        clean over the next.

        This asks `obj_under_cursor`, which answers in every cursor mode, so the
        same routine serves walking, attacking and using a skill. The earlier
        version asked HOOK_TARGETOBJECT, which only fires for the combat
        targeting cursor and so could never have verified a lockpick.
        """
        prev = 0
        for dy in TARGET_STEPS:
            if dy != prev:
                move_mouse_relative(0, dy - prev, settle=0.05, hwnd=self.hwnd)
                prev = dy
            r = self.read()
            if r is None:
                return None, prev
            if r.obj:
                return r.obj, dy
        return None, prev

    # -- solving --------------------------------------------------------

    def _solve(self, d_row: int, d_col: int):
        """Screen delta that should produce this row/column change."""
        a, c, b, d = self.j  # [[a b],[c d]] * (dx,dy) = (d_row, d_col)
        det = a * d - b * c
        if abs(det) < 1e-9:
            return None
        dx = (d * d_row - b * d_col) / det
        dy = (a * d_col - c * d_row) / det
        return dx, dy

    def _learn(self, dx_px: int, dy_px: int, d_row: int, d_col: int) -> None:
        """Correct the model from what the last move actually achieved.

        Only meaningful when the move was mostly along one axis; a blended move
        cannot be attributed to one axis or the other without more algebra than
        this is worth.
        """
        if abs(dx_px) > 20 and abs(dy_px) < 5:
            self.j[0] = d_row / dx_px
            self.j[1] = d_col / dx_px
        elif abs(dy_px) > 20 and abs(dx_px) < 5:
            self.j[2] = d_row / dy_px
            self.j[3] = d_col / dy_px

    # -- the servo ------------------------------------------------------

    def aim(self, trace=None) -> tuple:
        """Move the pointer onto the look hex.

        Returns (ok, reading, reason). `ok` is only True when the game itself
        confirms the pointer is on the requested hex -- never on our own belief
        about where we put it.
        """
        # Start from a known-safe pointer position. A session's worth of
        # relative moves can leave the Windows cursor at a window edge, where
        # the engine scrolls the map continuously and no aim can converge.
        park_pointer(self.hwnd)
        r = self.read()
        if r is None:
            return False, None, "the game did not report the cursor position"

        # Damping. Without it the servo overshoots small corrections and
        # oscillates for ever: a 28-pixel step hopped from the hex one short of
        # the target to the hex one past it, then back, indefinitely. Whenever a
        # step fails to reduce the error, the stride is halved, which turns that
        # oscillation into a bisection onto the hex between them.
        gain = 1.0
        prev_err = None

        for _ in range(MAX_STEPS):
            if r.on_target:
                return True, r, ""

            ur, uc = _rowcol(r.under)
            lr, lc = _rowcol(r.look)
            err = abs(lr - ur) + abs(lc - uc)
            if prev_err is not None and err >= prev_err:
                gain *= 0.5
                if gain < 0.02:
                    return False, r, "cannot land exactly on that hex"
            prev_err = err

            step = self._solve(lr - ur, lc - uc)
            if step is None:
                return False, r, "cannot work out which way to move"
            dx, dy = step[0] * gain, step[1] * gain

            # Clamp to the safe box, and to a sane step size.
            dx = max(-MAX_NUDGE, min(MAX_NUDGE, dx))
            dy = max(-MAX_NUDGE, min(MAX_NUDGE, dy))
            target_x = min(max(r.x + dx, MARGIN), r.width - MARGIN)
            target_y = min(max(r.y + dy, MARGIN), r.height - BOTTOM_MARGIN)
            want_x, want_y = target_x - r.x, target_y - r.y
            dx, dy = int(round(want_x)), int(round(want_y))
            # A damped step can round away to nothing while still being the
            # right idea. Move one pixel rather than stalling.
            if dx == 0 and dy == 0:
                if abs(want_x) >= abs(want_y) and abs(want_x) > 0.1:
                    dx = 1 if want_x > 0 else -1
                elif abs(want_y) > 0.1:
                    dy = 1 if want_y > 0 else -1
                else:
                    return False, r, "that hex is off the edge of the view"

            move_mouse_relative(dx, dy, settle=0.05, hwnd=self.hwnd)
            nxt = self.read()
            if nxt is None:
                return False, r, "lost contact with the game"

            if trace:
                trace(r, (dx, dy), nxt)

            moved_x, moved_y = nxt.x - r.x, nxt.y - r.y
            nr, nc = _rowcol(nxt.under)
            self._learn(moved_x, moved_y, nr - ur, nc - uc)
            r = nxt

        return r.on_target, r, "" if r.on_target else "could not settle on that hex"
