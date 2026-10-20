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
from . import worldlog
from ..i18n import tr

# Fallout 2's tile numbering is row-major with 200 tiles to a row, so a tile
# number splits into a row and a column that behave like coordinates. The screen
# axes are skewed relative to them (the map is drawn isometrically), which is
# what the matrix below is for.
TILES_PER_ROW = 200

# What the engine's cursor mode 0 means: a click walks to the tile under the
# pointer. Spelled out rather than imported from screens.py, which imports this
# module's neighbours and is not worth a cycle for one constant.
CURSOR_MOVEMENT = 0

# Modes 4 to 10 are the Skilldex skills, measured one at a time off the live
# Skilldex; screens.py names them. What matters here is only that the cursor is
# holding a skill the player armed, so the range is enough and the names are
# somebody else's business.
SKILL_CURSORS = range(4, 11)

_TARGET = re.compile(r"COMBAT:target (\d+)\|(\d+)\|([^|]*)")
_PREPARE = re.compile(r"WORLD:prepare (-?\d+)\|([^|]*)\|(-?\d+)\|(-?\d+)\|(\d*)"
                      r"(?:\|(-?\d+))?")

# How far above a hex to look for the critter standing on it, in pixels. Fallout
# picks critters by their drawn sprite rather than by the tile they occupy, so
# the pointer has to be on the figure, not on the ground beneath it.
#
# These are search steps, NOT a fixed offset, and that distinction was expensive:
# a hardcoded 12 pixels hit one ant and sailed clean over another. The engine is
# asked at each step whether it can see a target, so critter size, stance and
# screen position stop mattering.
# Upwards first, because a critter or a wall is drawn standing UP out of its
# hex, so the sprite is above the tile's centre.
#
# But not only upwards, which is what this was. **A brick of plastic explosive
# lying on the floor is drawn at or below the centre**, so walking the pointer
# up from the middle never touched it, obj_under_cursor reported nothing, and
# prepare_cursor fell through to "walkable ground" and chose the movement
# cursor. The click then walked onto the item instead of picking it up, with
# nothing anywhere saying why -- the hex readout named the item perfectly well
# the whole time, because that comes from the tile's object list rather than
# from the pointer.
#
# So the low half of the hex is searched too. It costs a few more probes on the
# misses and makes small things on the ground reachable at all.
TARGET_STEPS = (0, -4, -8, -12, -16, -20, -26, -32, 4, 8, 12, 16)

# The same hunt in two dimensions. Vertical alone finds a sprite that is not
# covered by anything, and fails the moment one is: an item on the floor beside
# a door is inside the door's sprite from top to bottom, so no amount of moving
# up or down reaches it. Sideways does, because the door does not extend across
# the whole hex.
#
# Ordered so the cheap cases stay cheap -- straight up first, then low, then
# out to the sides -- because every step costs a round trip to the game.
TARGET_OFFSETS = tuple(
    [(0, dy) for dy in TARGET_STEPS]
    + [(dx, dy) for dx in (-12, 12, -22, 22) for dy in (0, -8, 8, -16, 16)]
)

# Where to look for a spot inside the hex that is not covered by something
# else's sprite. Fallout draws tall objects over the hexes in front of them, so
# the centre of a perfectly walkable tile can be underneath a wall -- the
# pointer is on the right tile and the click lands on the wall. A sighted player
# solves this without noticing, by clicking a part of the hex they can see.
# Downwards first, because sprites lean upwards and the low edge of a hex is
# usually the clear part.
#
# **A hex is small, and this list has to fit inside one.** Rastered against a
# live game from a confirmed anchor on hex 20314: offsets out to +16 across and
# -10 across were already on neighbouring tiles, and during the aim itself a
# THREE pixel move changed which hex the pointer was over. An earlier version of
# this list reached 22 pixels either side on the theory that a wider search
# finds more clear ground. It does not. It leaves the hex, and a probe on the
# wrong hex is discarded, so widening the box bought nothing but latency.
#
# Only ever used now for the narrow case below where something under the pointer
# would really be acted on, so a handful of nearby spots is the right size.
CLEAR_STEPS = ((0, 0), (0, 4), (0, -4), (0, 8), (10, 0), (10, 4),
               (-6, 0), (-6, 4), (0, 12), (10, 8))

# Printed by the same key, just before the calibration line: where the
# interface bar is, which is the bottom of the map a click can reach.
_BAR = re.compile(r"WORLD:win under=\S+ ifacebar=\S+ onbar=\S+ "
                  r"barrect=(-?\d+),(-?\d+) (\d+)x(\d+)")

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

# Keep the pointer off the window edges and off the interface bar. Fallout
# scrolls the map when the pointer reaches a screen edge, which would move the
# very thing being aimed at, and the bar along the bottom swallows clicks.
#
# **This used to be 80 pixels from every edge and 180 from the bottom, and that
# box was most of the misses.** The scroll needs the very edge, not 80 pixels
# of it, and at 1024x768 the bar is 100 tall -- the script reports it at
# y=668. So a strip of visible map round three sides could not be pointed at.
# One session's log: 16 of 156 aims failed, and 12 of them were the pointer
# parked on the box's edge -- nine in a row at y=588, three at x=944 -- with
# the hex a row or two beyond it and plainly on screen. That is why exit grids,
# out at the edge of the view, were the worst, and why walking a few steps
# "fixed" it: the view re-centred and brought the hex inside the box.
#
# So the edges get a few pixels, and the bottom is the bar's own top edge as
# the script reports it. BOTTOM_MARGIN is only for a reading without it.
MARGIN = 8
BOTTOM_MARGIN = 108

MAX_STEPS = 10
MAX_NUDGE = 320  # pixels per step; a whole-screen lunge overshoots wildly

# How many times to ask for a calibration line before calling it a failure.
# A bound, not a measurement: three taps costs at most a couple of seconds on
# the way to a refusal that would otherwise have been spoken after one.
READ_ATTEMPTS = 3


class Reading(NamedTuple):
    x: int
    y: int
    under: int      # hex the pointer is over
    look: int       # hex the player selected with the numpad
    width: int
    height: int
    obj: str        # what the engine says a click would act on, "" for nothing
    bar_top: Optional[int] = None   # the interface bar's top edge, if known

    def lowest(self) -> int:
        """The lowest y the pointer may go to: just above the interface bar."""
        if self.bar_top is not None and 0 < self.bar_top <= self.height:
            return self.bar_top - MARGIN
        return self.height - BOTTOM_MARGIN

    def pinned(self, slack: int = 2) -> bool:
        """Is the pointer up against the edge of where it may go?

        A miss here is a hex the pointer could not reach rather than one it
        could not settle on: the view does not reach that far.
        """
        return (self.x <= MARGIN + slack or self.x >= self.width - MARGIN - slack
                or self.y <= MARGIN + slack or self.y >= self.lowest() - slack)

    @property
    def on_target(self) -> bool:
        return self.under == self.look


def _rowcol(tile: int):
    return divmod(tile, TILES_PER_ROW)


# Matching an object name lives with the readout that produces the names, in
# worldlog, because the action menu's own cross-check needs exactly the same
# comparison. Two copies of "is this the same object?" is how the two halves
# drift apart, which is the shape of the bug this whole change is fixing.
_wanted_names = worldlog.wanted_names
_names_match = worldlog.names_match


class Aimer:
    """Drives the pointer onto the look cursor's hex, and says whether it got there."""

    def __init__(self, hwnd: int, log_path: str) -> None:
        self.hwnd = hwnd
        self.log_path = log_path
        self._pos = None
        # Learned response, refined as we go.
        self.j = [J_ROW_PER_X, J_COL_PER_X, J_ROW_PER_Y, J_COL_PER_Y]
        # What was covering the hex the last time a clear spot could not be
        # found. Set by prepare(), read only to word the refusal.
        self.blocked_by: Optional[str] = None
        # Set by an object hunt that failed with the pointer on the hex and the
        # engine naming nothing there: what the readout named is drawn on the
        # floor and cannot be picked -- Dirt, Weeds -- so a click is a walk.
        self.bare = False

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
        guarded_tap(self.hwnd, "apostrophe", settle=0.06)
        deadline = time.time() + timeout
        found = None
        seen = ""
        bar_top = None
        while time.time() < deadline:
            chunk = self._tail()
            seen += chunk
            for line in chunk.splitlines():
                b = _BAR.search(line)
                if b and int(b.group(4)) > 0:
                    bar_top = int(b.group(2))
                m = _CALIB.search(line)
                if m:
                    found = Reading(
                        x=int(m.group(1)), y=int(m.group(2)),
                        under=int(m.group(4)), look=int(m.group(5)),
                        width=int(m.group(7)), height=int(m.group(8)),
                        obj=m.group(9).strip(),
                        bar_top=bar_top,
                    )
            if found:
                return found
            time.sleep(0.03)
        # Say what DID arrive. A miss here is spoken to the player as "the game
        # did not report the cursor position", which is true and useless: it
        # cannot distinguish a key that never reached the script from a reply
        # that arrived mangled. The engine writes its own debug output onto our
        # lines without a newline in between -- a real log holds
        # "PROBE:key 2Dialogue Reaction: Said Neutral" -- so a splice through
        # the middle of a calibration line fails this pattern while looking
        # perfectly fine to a human reading the file. Printing the tail is what
        # makes the next occurrence identifiable instead of anonymous.
        if seen.strip():
            print("[aim] no calibration line in: {!r}".format(seen[-300:]),
                  flush=True)
        else:
            print("[aim] the script said nothing at all after the calibrate key",
                  flush=True)
        return None

    def _probe(self, per_step: float = 0.25):
        """Ask the script to set the cursor, and report what it found there.

        Returns (mode, object_name, hex_under_pointer, look_hex, flat,
        object_hex) or None. `flat` is the engine's FLAG_FLAT: the thing under
        the pointer is drawn lying on the floor rather than standing up out of
        the hex. `object_hex` is the hex that thing stands on, -1 if nothing
        was named or the script is too old to say.
        """
        self._tail()
        guarded_tap(self.hwnd, "backslash", settle=0.08)
        deadline = time.time() + per_step
        while time.time() < deadline:
            found = _PREPARE.findall(self._tail())
            if found:
                mode, name, under, look, flat, tile = found[-1]
                return (int(mode), name.strip(), int(under), int(look),
                        flat == "1", int(tile) if tile else -1)
            time.sleep(0.03)
        return None

    def prepare(self, want_object: bool, per_step: float = 0.25,
                wanted=None):
        """Set the cursor for the click, and find a spot where it will land.

        Being on the right hex is not enough. Fallout draws tall objects over
        the hexes in front of them, so the middle of a walkable tile can sit
        underneath a wall: the pointer is on the correct tile and the click hits
        the wall. Measured on an ordinary empty hex -- aim matched, and the
        engine reported "Wall" under the pointer.

        So the pointer is walked around inside the hex until the engine agrees.
        For an object, upwards, onto its sprite. For bare ground, downwards and
        sideways, off whatever is leaning over it.

        `wanted` is what the player was TOLD is on this hex -- one name or all
        of them. Without it this takes the first object the engine offers, which
        is wrong whenever something taller is drawn over the one you chose: a
        brick of explosive lying beside a door answered "Impenetrable Door" to
        every probe, and the click was set up for the door.

        **All of them, not the first of them.** Insisting on a single name is
        what made every door in the game unclickable. A sliding door sits on a
        Door Track, so the hex reads "Door Track, Door", and taking the first
        field meant demanding "Door Track" while the engine said "Door" to all
        thirty-two probes in a row -- pointer on the right hex, engine agreeing,
        every answer thrown away, and "cannot point at that" spoken about a door
        the pointer was sitting on. Measured on hex 24308 in the Arroyo caves.

        Matching against every name the readout gave is both safer and simpler.
        The engine picks which object a click acts on; this only checks that its
        choice is one of the things the player has been told is there. There is
        no second guess to get wrong.

        **But the first acceptable answer is not the best one.** Accepting any
        of them meant accepting whichever the engine happened to name at the
        spot the aim left the pointer, and on a door hex that is the Door Track
        -- so the search stopped on its first probe, the click was set up for a
        length of rail, and a lockpick armed for the door was spent on it.
        Seven times in one session's log, each one silent, because using a
        skill on scenery that has no answer for it is not an error the engine
        reports. The same session picked the lock first try from one tile
        further along, where the pointer happened to land on the door instead.

        So a flat object does not end the search. FLAG_FLAT is the engine's own
        word for what lies on the floor -- rails, rugs, splatters -- and what
        stands up out of a hex is what a sighted player points at. The flat
        answer is kept as a fallback rather than discarded, so a hex whose only
        contents lie flat is still reachable; it just no longer wins over
        something standing on top of it.

        Returns (name, offset). `name` is the object the click would act on, or
        None. For bare ground, None with an offset found is success; None with
        no clear spot means the caller should not click -- and `blocked_by` then
        names what was in the way, because "behind Wall" is a fact a player can
        act on and "behind something" is not.
        """
        prev = (0, 0)
        candidates = list(TARGET_OFFSETS) if want_object else list(CLEAR_STEPS)
        acceptable = _wanted_names(wanted)
        self.blocked_by = None
        # Did the engine ever say "nothing" with the pointer on the hex? Read
        # by the caller after an object hunt fails: see `bare`.
        self.bare = False
        # The best flat answer seen so far, and where it was seen. Only used if
        # the whole search goes by without anything standing up out of the hex.
        underfoot = None
        # What was drawn over the hex instead, counted, to name in a refusal.
        covering = {}
        # Is there anything to choose BETWEEN? A flat answer is only the wrong
        # one when the hex holds something else that could be the right one.
        # Told about a single object -- a rug on its own, or the one name the
        # action menu hands over -- the engine's answer is the answer, and
        # walking all thirty-two offsets to arrive back at it would be several
        # seconds of silence bought for nothing.
        choosing = len(acceptable) > 1

        for dx, dy in candidates:
            if (dx, dy) != prev:
                move_mouse_relative(dx - prev[0], dy - prev[1],
                                    settle=0.05, hwnd=self.hwnd)
                prev = (dx, dy)
            probe = self._probe(per_step)
            if probe is None:
                continue
            mode, name, under, look, flat = probe[:5]
            tile = probe[5] if len(probe) > 5 else -1
            # **The object, not the pointer, has to be on the hex.** A critter
            # behind a bar is only clickable at its head, which is drawn over
            # the hex BEHIND it. The engine said "Sajag" there, correctly, and
            # this threw it away for being off the hex -- seven times in one
            # session, and five more on the Dunton brothers behind their table.
            # The script now says which hex the named thing stands on, and if
            # that is the one chosen, the pointer is wherever it had to be.
            reached = (want_object and bool(name) and tile == look
                       and (not acceptable or _names_match(name, acceptable)))
            if under != look and not reached:
                continue          # drifted off the hex entirely
            if want_object and not name and under == look:
                self.bare = True
            if want_object and name:
                if acceptable and not _names_match(name, acceptable):
                    covering[name] = covering.get(name, 0) + 1
                    continue          # something else is drawn over it
                if tile >= 0 and tile != look:
                    # The right name on the wrong object: something of the same
                    # kind standing next door, drawn over this hex. **Never a
                    # fallback.** It briefly was, and a locker on a wall hex,
                    # hidden behind the next wall along, was "clicked" by
                    # looking at that wall -- six times, while the readout said
                    # Wall, Locker. The thing on the hex is a different object
                    # whatever it is called, so this is cover, not an answer.
                    covering[name] = covering.get(name, 0) + 1
                    continue
                if flat and choosing:
                    # Keep looking. See the note above: this is the door track
                    # under the door, and stopping here is what spent the skill
                    # on it.
                    if underfoot is None:
                        underfoot = (name, prev)
                    continue
                return name, prev
            if not want_object:
                if not name:
                    return None, prev
                # Something IS drawn over the hex -- and that is usually fine.
                #
                # Ask the engine what a click would do rather than assuming it
                # would hit the sprite. With the movement cursor Fallout walks
                # to the tile under the pointer and does not care what is drawn
                # over it, so a wall across a walkable hex costs nothing.
                #
                # Measured, because this file assumed the opposite for months.
                # On hex 20314 every probe that stayed on the hex answered
                # "Wall" or "Cave Wall", the search gave up, and the mod refused
                # the walk. Clicking anyway, with mode 0 and the wall still
                # squarely under the pointer, produced WORLD:arrive 20314 dist 2
                # and cost the 2 action points the walk was worth. The refusal
                # had never been checked against an actual click; it was
                # inferred from obj_under_cursor naming something, which names
                # something almost everywhere on a Fallout map.
                #
                # A non-movement cursor is the case that really would act on the
                # sprite -- an item drawn across a walkable tile arms the
                # command cursor, and clicking picks the item up instead of
                # walking. That is worth stepping aside for, and it is what the
                # remaining offsets are for.
                #
                # **Unless the player armed a skill, which is not a walk going
                # wrong.** This test used to be `mode == CURSOR_MOVEMENT` alone,
                # and an armed skill sets the cursor to 4 through 10, so it
                # could never pass: every probe fell through to blocked_by, the
                # search ran out, and the click was refused with "that hex is
                # behind Wall". First aid on yourself is where that was found --
                # your own hex holds no object to point at, so the search takes
                # this branch -- but nothing about it was particular to healing
                # or to yourself. Arming any skill and choosing any hex with
                # nothing nameable on it produced the same refusal.
                #
                # The refusal above protects a WALK from landing on a sprite.
                # Somebody who armed Lockpick from the number row was not
                # walking, and the engine applies the skill to what it picks on
                # that hex -- which is exactly what a sighted player gets for
                # clicking there.
                if mode == CURSOR_MOVEMENT or mode in SKILL_CURSORS:
                    return None, prev
                self.blocked_by = name

        if want_object and underfoot is not None:
            # Nothing on this hex stands up, so the thing lying on it is the
            # thing that was meant. Go back to where the engine said so, and
            # probe once more: the script sets the cursor from what is under
            # the pointer, and the last probe was somewhere else.
            name, at = underfoot
            if at != prev:
                move_mouse_relative(at[0] - prev[0], at[1] - prev[1],
                                    settle=0.05, hwnd=self.hwnd)
                prev = at
                self._probe(per_step)
            return name, prev
        if want_object and covering:
            self.blocked_by = max(covering, key=covering.get)
        return (None, prev) if want_object else (False, prev)

    # -- solving --------------------------------------------------------

    def _solve(self, d_row: int, d_col: int):
        """Screen delta that should produce this row/column change.

        A singular model is recovered from rather than reported. It used to
        return None, the caller turned that into "cannot work out which way to
        move", and because the aimer lives as long as the session that refusal
        was permanent -- every click, every hex, until the mod was restarted.

        The measured starting values are always available and are known to be
        roughly right, so falling back to them costs one slightly clumsy aim
        that then re-measures itself. `_learn` no longer writes the row of zeros
        that caused this, and this is the backstop for whatever does it next.
        """
        a, c, b, d = self.j  # [[a b],[c d]] * (dx,dy) = (d_row, d_col)
        det = a * d - b * c
        if abs(det) < 1e-9:
            print("[aim] learned response went singular ({}); "
                  "falling back to the measured defaults".format(self.j),
                  flush=True)
            self.j = [J_ROW_PER_X, J_COL_PER_X, J_ROW_PER_Y, J_COL_PER_Y]
            a, c, b, d = self.j
            det = a * d - b * c
        dx = (d * d_row - b * d_col) / det
        dy = (a * d_col - c * d_row) / det
        return dx, dy

    def _learn(self, dx_px: int, dy_px: int, d_row: int, d_col: int) -> None:
        """Correct the model from what the last move actually achieved.

        Only meaningful when the move was mostly along one axis; a blended move
        cannot be attributed to one axis or the other without more algebra than
        this is worth.

        **A move that crossed no hex boundary teaches nothing, and believing it
        broke every click in the session.** A hex is about thirty pixels across,
        so a twenty-odd pixel step landing inside the one it started in is
        ordinary rather than exceptional. Taken as a measurement it says "moving
        along this axis changes the row by zero and the column by zero", which
        writes a row of zeros into the matrix, and a matrix with a zero row has
        no inverse -- so `_solve` returned None from then on and every aim, on
        every hex, answered "cannot work out which way to move".

        Captured in a live log, and the step that did it is unremarkable:

            mouse=472,334  under=20465     22 pixels right
            mouse=494,334  under=20465     same hex, so d_row = d_col = 0
            mouse=494,334  ...             the pointer never moved again

        The aimer lives as long as the session, so one such step poisoned it
        until the mod was restarted. That is why it read as "combat broke
        clicking" -- combat scrolls the map and provokes more corrections, so it
        is simply where the odds caught up.
        """
        if d_row == 0 and d_col == 0:
            return
        if abs(dx_px) > 20 and abs(dy_px) < 5:
            self.j[0] = d_row / dx_px
            self.j[1] = d_col / dx_px
        elif abs(dy_px) > 20 and abs(dx_px) < 5:
            self.j[2] = d_row / dy_px
            self.j[3] = d_col / dy_px

    # -- the servo ------------------------------------------------------

    def walk_toward(self) -> Optional[int]:
        """The hex to walk to on the way to one out of view, or None.

        Called with the pointer left where a failed aim pinned it, at the edge
        of the view on the side the hex is. The engine is asked what a click
        there would do, and the answer is only yes for a plain walk: anything
        else -- a door, an item, an armed skill -- would act on whatever
        happens to be at the edge, which nobody chose.
        """
        probe = self._probe()
        if probe is None:
            return None
        mode, _name, under, look = probe[:4]
        if mode != CURSOR_MOVEMENT or under == look or under < 0:
            return None
        return under

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
        # Ask more than once before giving up. A single dropped line used to end
        # the whole action -- one tap, one 0.8 second window, and a refusal the
        # player could not tell from a real one. Everything else in this mod
        # re-asks the engine until it answers; this did not, and combat is
        # exactly where it would bite, because that is when the engine writes
        # the most of its own output and the frame times are longest.
        r = None
        for _ in range(READ_ATTEMPTS):
            r = self.read()
            if r is not None:
                break
        if r is None:
            return False, None, tr("aim.no_report",
                                   "the game did not report the cursor position")

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
                    return False, r, tr("aim.inexact", "cannot land exactly on that hex")
            prev_err = err

            step = self._solve(lr - ur, lc - uc)
            if step is None:
                return False, r, tr("aim.no_way", "cannot work out which way to move")
            dx, dy = step[0] * gain, step[1] * gain

            # Clamp to the safe box, and to a sane step size.
            dx = max(-MAX_NUDGE, min(MAX_NUDGE, dx))
            dy = max(-MAX_NUDGE, min(MAX_NUDGE, dy))
            target_x = min(max(r.x + dx, MARGIN), r.width - MARGIN)
            target_y = min(max(r.y + dy, MARGIN), r.lowest())
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
                    return False, r, tr("aim.off_view",
                                        "that hex is off the edge of the view")

            move_mouse_relative(dx, dy, settle=0.05, hwnd=self.hwnd)
            nxt = self.read()
            if nxt is None:
                return False, r, tr("aim.lost_game", "lost contact with the game")

            if trace:
                trace(r, (dx, dy), nxt)

            moved_x, moved_y = nxt.x - r.x, nxt.y - r.y
            nr, nc = _rowcol(nxt.under)
            self._learn(moved_x, moved_y, nr - ur, nc - uc)
            r = nxt

        return r.on_target, r, "" if r.on_target else tr(
            "aim.unsettled_hex", "could not settle on that hex")
