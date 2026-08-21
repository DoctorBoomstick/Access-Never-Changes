"""Read the in-game script's output.

gl_world.ssl runs inside Fallout 2 and writes "WORLD:" lines to debug.log --
hex readouts, game-mode changes, calibration. This tails that file so the
Python side can speak them.

Why a log file rather than shared memory: sfall scripts can write strings with
debug_msg and little else, and the engine's own object names are only reachable
from inside the game. The file is the one channel that carries text out. It is
polled at the same 20Hz as everything else, which is well inside the reaction
time that matters here.

The game truncates debug.log on launch, so a shrinking file means a new session
and all remembered state is dropped.
"""

from __future__ import annotations

import os
import re
from typing import List, NamedTuple, Optional

PREFIX = "WORLD:"
# gl_combat.ssl writes on the same channel. Two scripts, one log file: they are
# kept as separate scripts so a bug in one cannot crash the other, but there is
# only one way for either to get text out of the engine.
COMBAT_PREFIX = "COMBAT:"
# The scanner also writes on this channel, from gl_world.ssl.
SCAN_PREFIX = "SCAN:"
# gl_inven.ssl, a third script, for the inventory and loot windows.
INVEN_PREFIX = "INVEN:"

# "WORLD:hex 17488 dist 0 : you, Tree|"
# Contents stop at the terminating bar. The engine appends its own debug output
# to our lines without a newline, and without the bar that noise was read as
# part of the object list and spoken aloud.
_HEX_RE = re.compile(r"WORLD:hex\s+(\d+)\s+dist\s+(\d+)\s*:\s*([^|]*)")
_MODE_RE = re.compile(r"WORLD:gamemode\s+(-?\d+)")
# Both forms report the current cursor mode: "cursormode" when it changed,
# "cursorok" when a press found it already correct. Parsing only the first left
# the mode unknown exactly when nothing had changed, which is the common case.
_CURSOR_RE = re.compile(r"WORLD:cursor(?:mode|ok)\s+(-?\d+)")


# "WORLD:status 48|48|8|10|8|1|"
_STATUS_RE = re.compile(
    r"WORLD:status\s+(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|"
)


def status_line(line: str) -> Optional[str]:
    """Turn a WORLD:status line into the sentence to say, or None.

    Health first, then action points, then armour class -- the order asked for,
    and the order they matter in when something is biting you.

    Action points are only a live figure during a fight. Outside one the engine
    still reports a running count, but it is not a number anyone is spending, so
    the maximum is given instead and worded as a capacity rather than a
    remainder. Saying "3 action points" while walking around would be true of
    nothing.
    """
    m = _STATUS_RE.match(line)
    if not m:
        return None
    hp, max_hp, ap, max_ap, ac, fighting = (int(g) for g in m.groups())
    parts = ["Health {} of {}.".format(hp, max_hp)]
    if fighting:
        parts.append("{} of {} action points.".format(ap, max_ap))
    else:
        parts.append("{} action points.".format(max_ap))
    parts.append("Armor class {}.".format(ac))
    return " ".join(parts)


_MENU_RE = re.compile(r"WORLD:menu (\w+)\s*([^|]*)\|?([^|]*)\|?([^|]*)\|?([^|]*)\|?")


def menu_line(line: str, aimed_at: Optional[str] = None) -> Optional[str]:
    """Turn a WORLD:menu line into the sentence to say, or None.

    The mod's own version of the icon strip a sighted player gets: everything
    the engine says can be done to this object, arrows to move, Enter to do it.

    `aimed_at` is what the pointer was actually put on when the list was built.
    The engine's action array is never cleared, only overwritten, so a list read
    at the wrong moment is a confident answer about the previous object -- and
    since it is never empty, that looks exactly like a good one. Python knows
    what it aimed at and the script names what it opened the menu for; if the
    two disagree the only honest thing is to say so rather than read out a menu
    for something else.
    """
    m = _MENU_RE.match(line)
    if not m:
        return None
    what = m.group(1)
    if what == "none":
        return "Nothing there to act on."
    if what == "empty":
        return "{}. Nothing you can do to it.".format(m.group(2).strip() or "That")
    if what == "closed":
        return "Closed."
    if what == "gone":
        return "That is no longer there."
    if what == "noroute":
        return ("{}. The game offers that, but the mod has no way to do it yet."
                .format(m.group(2).strip().capitalize()))
    if what == "open":
        name, count, first = (m.group(2).strip(), m.group(3).strip(),
                              m.group(4).strip())
        if aimed_at and name and aimed_at != name:
            return ("Read the wrong thing: pointed at {} but the game answered "
                    "for {}. Try again.".format(aimed_at, name))
        return "{}. {} actions. {}, 1 of {}.".format(
            name, count, first.capitalize(), count)
    if what == "at":
        label, index, count = (m.group(2).strip(), m.group(3).strip(),
                               m.group(4).strip())
        return "{}, {} of {}.".format(label.capitalize(), index, count)
    return None


# "WORLD:useobj try Impenetrable Door|"
_USEOBJ_RE = re.compile(r"WORLD:useobj (\w+)\s*([^|]*)\|?")


def use_obj_line(line: str) -> Optional[str]:
    """Turn a WORLD:useobj line into the sentence to say, or None.

    "Use it" -- the hand icon. Nothing could reach this before: the mod only
    ever selects the movement or targeting cursor, so a click on a door walked
    into it instead of opening it, and opening one needs the command cursor the
    mod never picks.

    Like the item version, finishing says nothing. The engine reports what
    happened in its own words through the display window, which is already read
    aloud, and it knows whether the door was locked.
    """
    m = _USEOBJ_RE.match(line)
    if not m:
        return None
    what, target = m.group(1), m.group(2).strip()
    if what == "notarget":
        return "Nothing there to use."
    if what == "try":
        return "Using {}.".format(target or "it")
    return None


# "WORLD:useitem try Plastic Explosives|Impenetrable Door|"
_USEITEM_RE = re.compile(r"WORLD:useitem (\w+)\s*([^|]*)\|?([^|]*)\|?")


def use_item_line(line: str) -> Optional[str]:
    """Turn a WORLD:useitem line into the sentence to say, or None.

    Four outcomes, and the wording keeps them apart because they need
    different things done about them: nothing in your hand, nothing to use it
    on, the attempt starting, and the attempt returning.

    "Done" deliberately does not claim success. The engine runs the object's own
    handler, and whether a door opens or a lock refuses is something the game
    says in its own words through the display window -- which this mod already
    reads aloud. Inventing a verdict here would put a second, less informed
    voice on top of the one that actually knows.
    """
    m = _USEITEM_RE.match(line)
    if not m:
        return None
    what, item, target = m.group(1), m.group(2).strip(), m.group(3).strip()
    if what == "empty":
        return "Your hands are empty. Ready an item first."
    if what == "notarget":
        return "Nothing there to use it on."
    if what == "try":
        return "Using {} on {}.".format(item or "that", target or "it")
    return None      # "done" carries diagnostics; the game's own words follow


class HexReading(NamedTuple):
    tile: int
    distance: int
    contents: str

    def announce(self) -> str:
        """What to say when the cursor lands here."""
        what = self.contents.strip() or "empty"
        if self.distance == 0:
            return what
        return "{}, {} hex{}".format(what, self.distance, "" if self.distance == 1 else "es")


class WorldLog:
    def __init__(self, path: str) -> None:
        self.path = path
        self._pos = 0
        self.game_mode: Optional[int] = None
        self.cursor_mode: Optional[int] = None
        self.last_hex: Optional[HexReading] = None
        self.session_live = False
        # Bumped every time the script announces itself, which it does once per
        # game load. The display window's buffer is reallocated at the same
        # moment, so this is what tells the reader its anchor has gone stale --
        # loading a save without restarting the game left it pointing at freed
        # heap, and the game's own words went quiet with nothing to show why.
        self.ready_count = 0

    def reset(self) -> None:
        self._pos = 0
        self.game_mode = None
        self.cursor_mode = None
        self.last_hex = None
        self.session_live = False
        self.ready_count = 0

    def poll(self) -> List[str]:
        """Return new WORLD: lines, updating cached state."""
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return []

        if size < self._pos:
            # Truncated: the game relaunched.
            self.reset()

        out: List[str] = []
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._pos)
                chunk = fh.read()
                self._pos = fh.tell()
        except OSError:
            return []

        for line in chunk.splitlines():
            if SCAN_PREFIX in line:
                out.append(line[line.index(SCAN_PREFIX):].strip())
                continue
            if COMBAT_PREFIX in line:
                combat = line[line.index(COMBAT_PREFIX):].strip()
                out.append(combat)
                if combat.startswith("COMBAT:ready"):
                    self.session_live = True
                continue
            if INVEN_PREFIX in line:
                inven = line[line.index(INVEN_PREFIX):].strip()
                out.append(inven)
                if inven.startswith("INVEN:ready"):
                    self.session_live = True
                continue
            if PREFIX not in line:
                continue
            line = line[line.index(PREFIX):].strip()
            out.append(line)

            if line.startswith("WORLD:ready"):
                self.session_live = True
                self.ready_count += 1
                continue

            m = _MODE_RE.match(line)
            if m:
                self.game_mode = int(m.group(1))
                self.session_live = True
                continue

            m = _CURSOR_RE.match(line)
            if m:
                self.cursor_mode = int(m.group(1))
                self.session_live = True
                continue

            m = _HEX_RE.match(line)
            if m:
                self.last_hex = HexReading(
                    tile=int(m.group(1)),
                    distance=int(m.group(2)),
                    contents=m.group(3).strip(),
                )
        return out
