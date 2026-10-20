"""A cursor for the world map, and a scanner for the places on it.

The same idea as the look cursor on a loaded map, moved onto the other grid the
game keeps. `gl_world.ssl` walks a cursor over hexes and reads out what is on
each; this walks one over the world map's 28 x 30 grid of subtiles and reads out
the ground, the fog and the places.

**The numpad means here what it looks like it means.** On a hex grid it cannot:
a hex has six neighbours and no north, so numpad 8 and 2 had to be built out of
a staircase of north-east and north-west steps that drifts sideways as it
climbs. The world map is a square grid, so all eight are real directions and one
press is one square in the direction the key is drawn in.

    7 NW   8 N    9 NE
    4 W           6 E          5 = back to the player
    1 SW   2 S    3 SE

**The scanner keeps its own keys and changes what it counts.** On a map it steps
through the things on the floor; here it steps through the places on the map,
because that is what the world map has instead of objects. `[` and `]` walk
them, `/` puts the cursor on the one being read out -- exactly the three keys
that already do this on a map, doing the same job on different nouns. There is
no category or instance level: locations are one kind of thing and each is
itself, so shift and ctrl have nothing to select between and are left alone.

**Two rules from the rest of the mod decide what gets said, and both cut things
out.**

Nothing is announced that a sighted player could not see. That is why an
unexplored square is announced as unexplored and nothing else, rather than
naming the ground under the fog -- the engine draws those black, so the terrain
is genuinely not on screen. It is why unknown areas are never offered by the
scanner even though every one of them is sitting in the area table with its
coordinates. And it is why the encounter odds, which the reader can see plainly
in every subtile record, are never spoken: the game does not draw them.

The other is that a step should be short. This cursor is walked twenty times in
a row, and a readout that takes three seconds to say makes the grid unusable.
So a step says only what changed, and the full account waits for a key that asks
for it.
"""

from __future__ import annotations

from typing import List, NamedTuple, Optional, Tuple

from ..memory.process import Process
from . import worldmap
from ..i18n import tr
from .. import words

# Numpad to a step, as the keys are laid out. Two of these -- north and south --
# are the ones the hex grid could not offer.
STEPS = {
    "nw": (-1, -1), "n": (0, -1), "ne": (1, -1),
    "w": (-1, 0), "e": (1, 0),
    "sw": (-1, 1), "s": (0, 1), "se": (1, 1),
}

def bearing(dx: int, dy: int) -> str:
    """Which way `dx, dy` points, to the nearest eighth.

    Screen coordinates, so y grows downward and south is +1. Written out rather
    than computed with atan2 so that the eight exact directions -- which is
    what stepping the cursor produces -- are exact rather than rounded.
    """
    # Eight points, because the grid has eight neighbours. The hex scanner has
    # six and they are the engine's own rotations; these are ours, for the
    # same reason the category words are: the game has no word for "north
    # east of you" on the world map because it never needs to say one.
    #
    # Off the axes, the diagonals are only named when the two components are
    # close enough for the diagonal to be the honest answer. Two squares east
    # and nine south is south, not south east.
    ax, ay = abs(dx), abs(dy)
    if ax * 2 < ay:
        dx = 0
    elif ay * 2 < ax:
        dy = 0
    return words.compass(dx, dy)


def steps_away(dx: int, dy: int) -> int:
    """How many presses of the cursor keys would cover this.

    The diagonal moves, so the distance that matters is the larger of the two
    components rather than their sum or their hypotenuse. This is the same
    promise the hex cursor's distance makes -- it is a count of moves, not a
    measurement -- and it is the number a player can act on.
    """
    return max(abs(dx), abs(dy))


def _distance(dx: int, dy: int) -> str:
    n = steps_away(dx, dy)
    if n == 0:
        return tr("worldmap.here", "here")
    if n == 1:
        distance = tr("worldmap.one_square", "1 square")
    else:
        distance = tr("worldmap.squares", "{count} squares", count=n)
    return tr("worldmap.where", "{direction} {distance}",
              direction=bearing(dx, dy), distance=distance).strip()


def _sentence(parts: List[str]) -> str:
    """Join the pieces of a readout into sentences.

    Only the first letter is touched, and `str.capitalize` is not used: it
    lowercases everything after it, which turns the game's own "Temple: Foyer"
    into "Temple: foyer". The words in here come from the game's message files
    and this mod does not get to restyle them.
    """
    said = [p[:1].upper() + p[1:] for p in parts if p]
    return ". ".join(said) + "." if said else ""


class Reading(NamedTuple):
    """Everything true about one square, so the phrasing can be chosen later."""

    x: int
    y: int
    terrain: Optional[str]        # None where the fog hides it
    state: int
    area: Optional[worldmap.Area]
    on_player: bool
    dx: int
    dy: int

    @property
    def seen(self) -> bool:
        return self.state in (worldmap.KNOWN, worldmap.VISITED)

    def step(self) -> str:
        """What a single press of a cursor key says.

        Short on purpose. The place first when there is one, because that is
        the reason to be looking at this square at all; then the ground; then
        where it is. "You are here" replaces the distance rather than joining
        it, since "here, 0 squares" is noise.
        """
        parts: List[str] = []
        if self.area is not None:
            parts.append(self.area.name)
        parts.append(self.terrain if self.seen and self.terrain
                     else tr("worldmap.unexplored", "unexplored"))
        parts.append(tr("worldmap.you_are_here", "you are here") if self.on_player
                     else _distance(self.dx, self.dy))
        return _sentence(parts)

    def full(self) -> str:
        """What the describe key says: the same square, at length.

        This is where the difference between a square the player has walked and
        one they have only seen from a distance is spoken. The engine draws
        those differently -- black, dimmed, clear -- so a sighted player has the
        distinction and this mod owes it to them, but it is not worth a syllable
        on every one of twenty presses.
        """
        parts: List[str] = []
        if self.area is not None:
            parts.append("{}, {}".format(
                self.area.name, worldmap.state_word(self.area.state)))
            ways = [e.name for e in self.area.ways_in if e.name]
            if ways:
                if len(ways) == 1:
                    parts.append(tr("worldmap.one_way_in", "1 way in: {ways}",
                                    ways=ways[0]))
                else:
                    parts.append(tr("worldmap.ways_in", "{count} ways in: {ways}",
                                    count=len(ways), ways=", ".join(ways)))
        if not self.seen:
            parts.append(tr("worldmap.unexplored", "unexplored"))
        else:
            parts.append(self.terrain or tr("worldmap.unknown_ground", "unknown ground"))
            if self.state == worldmap.KNOWN:
                parts.append(tr("worldmap.seen", "seen but not travelled"))
        parts.append(tr("worldmap.you_are_here", "you are here") if self.on_player
                     else _distance(self.dx, self.dy))
        parts.append(tr("worldmap.square", "square {x}, {y}", x=self.x, y=self.y))
        return _sentence(parts)


class WorldCursor:
    """Where the player is looking on the world map.

    Holds a position and nothing else. Every reading is taken from the game at
    the moment it is asked for, which is the same discipline the rest of the mod
    keeps: remembering what was on a square is how speech drifts out of step
    with a world that moved underneath it.
    """

    def __init__(self) -> None:
        self.x: Optional[int] = None
        self.y: Optional[int] = None
        # The scanner's position in the list of known places, and whether it
        # has ever been moved. The first press should read out the nearest
        # place rather than stepping past it -- starting at 0 and immediately
        # advancing means the place you are standing on is the last one you
        # hear about, which is the wrong way round.
        self.scan_index: int = 0
        self._scanned: bool = False
        self._last: Optional[str] = None

    def reset(self) -> None:
        self.x = None
        self.y = None
        self.scan_index = 0
        self._scanned = False
        self._last = None

    # -- moving --------------------------------------------------------------

    def snap(self, proc: Process) -> bool:
        """Put the cursor back on the player."""
        here = worldmap.player_subtile(proc)
        if here is None:
            return False
        self.x, self.y = here
        return True

    def ensure(self, proc: Process) -> bool:
        """Make sure there is a cursor, without moving one that exists."""
        if self.x is None or self.y is None:
            return self.snap(proc)
        return True

    def step_by(self, proc: Process, dx: int, dy: int) -> Tuple[bool, str]:
        """Move one square. Returns whether it moved, and why not if it did not.

        The edge of the world stops the cursor rather than wrapping it, and says
        so. Silently refusing to move is the failure mode that matters here:
        pressing east four times and hearing the same square four times reads as
        the mod having stopped working, when what happened is that the Pacific
        is there.
        """
        if not self.ensure(proc):
            return False, tr("worldmap.closed", "The world map is not open.")
        shape = worldmap.layout(proc)
        if shape is None:
            return False, tr("worldmap.unreadable", "Cannot read the world map.")
        nx, ny = self.x + dx, self.y + dy
        if not shape.contains(nx, ny):
            return False, tr("worldmap.edge", "Edge of the map.")
        self.x, self.y = nx, ny
        return True, ""

    def goto(self, x: int, y: int) -> None:
        self.x, self.y = x, y

    # -- reading -------------------------------------------------------------

    def read(self, proc: Process,
             table: Optional[List[worldmap.Area]] = None) -> Optional[Reading]:
        if self.x is None or self.y is None:
            return None
        square = worldmap.subtile(proc, self.x, self.y)
        if square is None:
            return None
        here = worldmap.player_subtile(proc)
        dx = self.x - here[0] if here else 0
        dy = self.y - here[1] if here else 0
        names = worldmap.terrain_names(proc)
        return Reading(
            x=self.x, y=self.y,
            terrain=names.get(square.terrain),
            state=square.state,
            area=worldmap.area_at(proc, self.x, self.y, table),
            on_player=(here == (self.x, self.y)),
            dx=dx, dy=dy,
        )

    def say_step(self, proc: Process) -> Optional[str]:
        reading = self.read(proc)
        if reading is None:
            return None
        self._last = reading.step()
        return self._last

    def say_full(self, proc: Process) -> Optional[str]:
        reading = self.read(proc)
        return None if reading is None else reading.full()

    def repeat(self) -> Optional[str]:
        return self._last

    # -- the scanner ---------------------------------------------------------

    def places(self, proc: Process) -> List[worldmap.Area]:
        """The places the scanner will offer, nearest to the player first.

        Only the ones the game has shown. The area table holds sixty-one
        entries and fifty-nine of them are unknown at the start of a game --
        every random encounter site, every special encounter, all three Ranger
        safe houses -- and reading them out would be handing over the map.
        """
        here = worldmap.player_subtile(proc) or (0, 0)

        def away(area: worldmap.Area) -> int:
            sx, sy = area.subtile
            return steps_away(sx - here[0], sy - here[1])

        return sorted(worldmap.known_areas(proc), key=away)

    def scan(self, proc: Process, delta: int) -> Optional[str]:
        """Step through the places. `delta` is +1 for `]` and -1 for `[`.

        Wraps, like the hex scanner does, because a list you can fall off the
        end of makes you count your presses.
        """
        found = self.places(proc)
        if not found:
            return tr("worldmap.no_places", "No places on the map yet.")
        if self._scanned:
            self.scan_index = (self.scan_index + delta) % len(found)
        else:
            # First press: the nearest place, which is index 0 already.
            self.scan_index = min(self.scan_index, len(found) - 1)
            self._scanned = True
        area = found[self.scan_index]
        here = worldmap.player_subtile(proc) or area.subtile
        sx, sy = area.subtile
        self._last = _sentence([
            "{}, {}".format(area.name,
                            worldmap.state_word(area.state)),
            _distance(sx - here[0], sy - here[1]),
            words.of(self.scan_index + 1, len(found)),
        ])
        return self._last

    def scan_jump(self, proc: Process) -> Optional[str]:
        """Put the cursor on the place being read out.

        Says nothing itself. The square readout that follows describes where the
        cursor landed, in the same words every other move uses, and saying it
        twice helps nobody -- which is the rule the hex scanner's jump already
        follows.
        """
        found = self.places(proc)
        if not found:
            return tr("worldmap.no_places", "No places on the map yet.")
        if not 0 <= self.scan_index < len(found):
            self.scan_index = 0
        self.goto(*found[self.scan_index].subtile)
        return None
