"""Read the world map out of the running game.

The world map is the one screen where the mod's usual division of labour turns
around. Everywhere else the in-game script is the source of truth, because only
a script can ask the engine what is on a hex or what is in a pot. Here every
answer is a plain structure in memory -- where you are, where you are going,
which places you know, what the ground is, which squares you have seen -- and
the Python half can read all of it directly. So the world map lives entirely on
this side, which also means it can be changed without restarting the game, which
nothing else in this mod can.

**The geometry, taken from the engine's own arithmetic rather than measured.**
At 0x004BC912 the engine computes its own scroll limits, and doing so spells the
whole layout out:

    tiles across          [0x0051DDF4]        4
    tiles in total        [0x0051DDF0]       20      so 5 rows
    tile size                                350 x 300 pixels
    world size                              1400 x 1500 pixels
    viewport                                 450 x 443 pixels
    max scroll            950, 1057   =   world - viewport, and both were read
                                            back live at those exact values

Each tile holds 7 x 6 subtiles of 50 x 50, so the world is a **28 x 30 grid of
subtiles** and that is the unit this module works in. sfall agrees: its
`get_terrain_name` bounds-checks x against `tilesAcross * 7` and y against
`(total / across) * 6` before multiplying both by 50.

**Screen and world, from the engine's own conversion.** At 0x004BFE7A the world
map turns a mouse position into a world position, and it is this and nothing
more:

    worldX = mouseX_within_window + scrollX - 22
    worldY = mouseY_within_window + scrollY - 21

which inverts exactly. That is why `to_screen` is arithmetic and not a servo:
the hex aimer has to learn its mapping because a tile number says nothing about
where the tile is drawn, and here the engine has told us.

**Names come from the game's message files, never from the area table.** The
area records do carry a `char name[40]`, and it is tempting because it is right
there -- but it holds city.txt's internal names: "abbey", "Car Outta Gas",
"Special Whale", "Sierra Army Base" where the game says "Sierra Army Depot".
Those are identifiers, not words for a player. The displayed name is
`map.msg[1500 + areaIndex]`, and an entrance's name is `map.msg[200 + 3*mapIdx]`
-- checked entry for entry against all five of Arroyo's entrances and all six of
Klamath's. Terrain is `worldmap.msg[1000 + n]`, which is five words: Desert,
Mountains, City, Coast, Unknown.
"""

from __future__ import annotations

import struct
from typing import Dict, List, NamedTuple, Optional, Tuple

from ..memory.process import Process
from ..msg.memlist import read_message_list

# -- addresses ---------------------------------------------------------------
#
# Signature-resolved at startup like everything else the mod reads; the values
# here are what the patterns matched on the build they were generated against.

WORLD_X = 0x00672E0C          # the player, in world pixels
WORLD_Y = 0x00672E10
DEST_X = 0x00672E5C           # where a click sent them, same units
DEST_Y = 0x00672E60
CURRENT_AREA = 0x00672E08     # index into the area table, or -1 for open country
TRAVELLING = 0x00672E1C       # non-zero while the marker is moving
SCROLL_X = 0x0051DE2C         # top-left of the viewport within the world
SCROLL_Y = 0x0051DE30

TILE_LIST = 0x0051DDEC        # -> array of tiles
TILE_COUNT = 0x0051DDF0       # 20
TILES_ACROSS = 0x0051DDF4     # 4

AREA_LIST = 0x0051DDF8        # -> array of areas
AREA_COUNT = 0x0051DDFC       # 61 on this install; RPU adds to city.txt

TOWN_ROWS = 0x0051DE94        # -> array of area indices, the right-hand list
TOWN_ROW_COUNT = 0x0051DE98
TOWN_SCROLL = 0x00672F10      # in pixels; one row is 27 of them

MSG_WORLDMAP = 0x00672FB0     # MessageList: terrain names, travel messages
MSG_MAP = 0x00631D48          # MessageList: area names, map names

# -- layout ------------------------------------------------------------------

TILE_W = 350
TILE_H = 300
SUBTILE = 50
SUB_ACROSS = TILE_W // SUBTILE   # 7
SUB_DOWN = TILE_H // SUBTILE     # 6

VIEW_W = 450
VIEW_H = 443
# Where the map picture starts inside the world map window. Not measured off a
# screenshot: these are the two constants the engine subtracts at 0x004BFE91
# when it converts a mouse position into a world position.
VIEW_LEFT = 22
VIEW_TOP = 21

WINDOW_W = 640
WINDOW_H = 480

TILE_STRIDE = 0x4D4           # 1236 = 60 header + 42 subtiles of 28
TILE_SUBTILES = 0x3C
SUBTILE_STRIDE = 28

AREA_STRIDE = 0x168           # 360
A_NAME = 0x00                 # char[40], city.txt's internal name -- not spoken
A_INDEX = 0x28
A_X = 0x2C
A_Y = 0x30
A_SIZE = 0x34
A_STATE = 0x40
A_ENTRANCE_COUNT = 0x4C
A_ENTRANCES = 0x50
ENTRANCE_STRIDE = 28
MAX_ENTRANCES = (AREA_STRIDE - A_ENTRANCES) // ENTRANCE_STRIDE   # 10

ROW_HEIGHT = 27               # the town list scrolls 27 pixels per row
ROWS_VISIBLE = 7

# Area and subtile states share these three values.
UNKNOWN = 0
KNOWN = 1
VISITED = 2
# city.txt's way of hiding an area from the map entirely.
INVISIBLE = -66

STATE_WORDS = {UNKNOWN: "unknown", KNOWN: "known", VISITED: "visited"}

# Message numbers. The bases are the engine's, the arithmetic is the engine's;
# only the choice of which to speak is ours.
MSG_AREA_BASE = 1500          # map.msg: one per area, in area order
MSG_MAP_BASE = 200            # map.msg: three entries per map, name first
MSG_MAP_STRIDE = 3
MSG_TERRAIN_BASE = 1000       # worldmap.msg

# The engine's own encounter-chance table, at 0x00672FB8: a subtile stores an
# index into this, one per part of the day, and this is the percentage. Read
# rather than assumed, and kept here because it is the difference between "you
# might be attacked here" and a number.
ENCOUNTER_CHANCE = 0x00672FB8
ENCOUNTER_CHANCE_COUNT = 6


# The town view gives its entrance buttons consecutive event codes starting
# here, and `inc ebp` sits outside the skip at 0x004C4BA8 -- so the code is
# 0x31 + the entrance's index in the array, whether or not the ones before it
# were drawn. Below 256, so these are keyboard codes: 49 is "1", and pressing
# it enters the first entrance with no pointer involved.
#
# The same shape as the dialogue screen, and the same limit. Ten entrances fit
# in the record and only the first nine have a number key; the tenth would come
# out as 58, which is a colon. Only the EPA has ten.
ENTRANCE_KEY_BASE = 0x31
ENTRANCE_KEYS = "123456789"


class Entrance(NamedTuple):
    """One way into a town, as city.txt describes it."""

    index: int
    known: bool
    x: int                    # where its button sits on the town picture
    y: int
    map_index: int
    elevation: int
    tile: int
    orientation: int
    name: str

    @property
    def available(self) -> bool:
        """Would the town view draw a button for this?

        Three conditions, and the engine tests all three in a row at
        0x004C4B4C: the entrance must be known, and neither coordinate may be
        -1. The last two are what stop this overstating -- Arroyo records five
        entrances and all five are marked known, but "Temple: Foyer" carries
        -1, -1 and is never drawn, so a player is looking at four.
        """
        return self.known and self.x != -1 and self.y != -1

    @property
    def key(self) -> str:
        """The number key that enters here, or "" past the ninth."""
        i = self.index
        return ENTRANCE_KEYS[i] if 0 <= i < len(ENTRANCE_KEYS) else ""


class Area(NamedTuple):
    """A place on the world map."""

    index: int
    name: str                 # the game's word, from map.msg
    x: int                    # world pixels
    y: int
    size: int
    state: int                # UNKNOWN / KNOWN / VISITED
    entrances: List[Entrance]

    @property
    def subtile(self) -> Tuple[int, int]:
        return (self.x // SUBTILE, self.y // SUBTILE)

    @property
    def ways_in(self) -> List[Entrance]:
        """The entrances the town view actually offers."""
        return [e for e in self.entrances if e.available]

    @property
    def on_map(self) -> bool:
        """Would a sighted player see a marker for this?

        The area table is not a list of towns. Two thirds of it is random
        encounter sites, the special encounters, and three Ranger safe houses
        -- all of which sit at real coordinates and none of which is drawn
        until it is found. Announcing them would be handing over a map the game
        has not given, which is the one thing this mod does not do.
        """
        return self.state in (KNOWN, VISITED)


class Subtile(NamedTuple):
    """One 50x50 square of the world."""

    x: int                    # 0..27
    y: int                    # 0..29
    terrain: int
    state: int                # UNKNOWN / KNOWN / VISITED
    encounter_chance: Tuple[int, int, int]   # indices, by part of the day
    encounter_type: int

    @property
    def seen(self) -> bool:
        return self.state in (KNOWN, VISITED)


class Layout(NamedTuple):
    """The world's dimensions, read from the running game rather than assumed.

    Hardcoding 28 by 30 would work on every unmodified install and break
    silently on a mod that adds a row of tiles -- the reads would still succeed
    and would describe the wrong square. The engine keeps both numbers.
    """

    tiles_across: int
    tile_count: int

    @property
    def tiles_down(self) -> int:
        return self.tile_count // self.tiles_across if self.tiles_across else 0

    @property
    def width(self) -> int:
        return self.tiles_across * SUB_ACROSS

    @property
    def height(self) -> int:
        return self.tiles_down * SUB_DOWN

    def contains(self, sx: int, sy: int) -> bool:
        return 0 <= sx < self.width and 0 <= sy < self.height


def layout(proc: Process) -> Optional[Layout]:
    across = proc.read_i32(TILES_ACROSS)
    total = proc.read_i32(TILE_COUNT)
    if not across or not total or across <= 0 or total <= 0:
        return None
    if total % across:
        return None
    return Layout(tiles_across=across, tile_count=total)


# -- where things are --------------------------------------------------------


def player(proc: Process) -> Optional[Tuple[int, int]]:
    """The player's position, in world pixels."""
    x = proc.read_i32(WORLD_X)
    y = proc.read_i32(WORLD_Y)
    if x is None or y is None:
        return None
    return (x, y)


def player_subtile(proc: Process) -> Optional[Tuple[int, int]]:
    pos = player(proc)
    return None if pos is None else (pos[0] // SUBTILE, pos[1] // SUBTILE)


def destination(proc: Process) -> Optional[Tuple[int, int]]:
    """Where the engine is walking the player, in world pixels.

    Zero means no destination rather than the top-left corner: the engine sets
    both to 0 when it is not travelling, and 0,0 is deep in the ocean where
    nobody can walk anyway.
    """
    x = proc.read_i32(DEST_X)
    y = proc.read_i32(DEST_Y)
    if x is None or y is None or (x == 0 and y == 0):
        return None
    return (x, y)


def travelling(proc: Process) -> bool:
    return bool(proc.read_i32(TRAVELLING))


def scroll(proc: Process) -> Optional[Tuple[int, int]]:
    x = proc.read_i32(SCROLL_X)
    y = proc.read_i32(SCROLL_Y)
    if x is None or y is None:
        return None
    return (x, y)


def current_area(proc: Process) -> Optional[int]:
    """Index of the area the player is standing on, or None in open country."""
    index = proc.read_i32(CURRENT_AREA)
    return None if index is None or index < 0 else index


# -- the world's ground ------------------------------------------------------


def subtile(proc: Process, sx: int, sy: int) -> Optional[Subtile]:
    """One square of the world.

    Subtiles are stored **row-major within their tile**, which is worth stating
    because reading them the other way round does not look wrong. Column-major
    produces a plausible-looking grid whose terrain runs in diagonal stripes,
    and the first pass at this was column-major and reported the player's own
    square as unexplored. Two things settle it: sfall computes its subtile key
    as `y * (across * 7) + x`, and read row-major the westernmost two columns of
    the world come out as Coast for their entire height, which is the Pacific.
    """
    shape = layout(proc)
    if shape is None or not shape.contains(sx, sy):
        return None
    base = proc.read_ptr(TILE_LIST)
    if not base:
        return None
    tile = (sy // SUB_DOWN) * shape.tiles_across + (sx // SUB_ACROSS)
    if not 0 <= tile < shape.tile_count:
        return None
    within = (sy % SUB_DOWN) * SUB_ACROSS + (sx % SUB_ACROSS)
    addr = base + tile * TILE_STRIDE + TILE_SUBTILES + within * SUBTILE_STRIDE
    blob = proc.read(addr, SUBTILE_STRIDE)
    if not blob or len(blob) < SUBTILE_STRIDE:
        return None
    fields = struct.unpack("<7i", blob)
    return Subtile(x=sx, y=sy, terrain=fields[0], state=fields[6],
                   encounter_chance=(fields[2], fields[3], fields[4]),
                   encounter_type=fields[5])


def encounter_percent(proc: Process, index: int) -> Optional[int]:
    """Turn a subtile's chance index into the percentage the engine uses."""
    if not 0 <= index < ENCOUNTER_CHANCE_COUNT:
        return None
    return proc.read_i32(ENCOUNTER_CHANCE + index * 4)


# -- the places --------------------------------------------------------------


def _messages(proc: Process, global_addr: int) -> Dict[int, str]:
    listing = read_message_list(proc, global_addr)
    if listing is None:
        return {}
    return listing.by_num()


def terrain_names(proc: Process) -> Dict[int, str]:
    """The five words the game has for ground, keyed by terrain index."""
    msgs = _messages(proc, MSG_WORLDMAP)
    return {num - MSG_TERRAIN_BASE: text
            for num, text in msgs.items()
            if MSG_TERRAIN_BASE <= num < MSG_TERRAIN_BASE + 64}


def areas(proc: Process) -> List[Area]:
    """Every area in city.txt, named in the game's own words.

    All of them, including the ones the player has never heard of. Filtering is
    left to the caller through `Area.on_map`, because two callers want different
    things: the scanner must only ever offer places the game has shown, while
    "what am I standing on" has to be able to name a place whose marker is not
    drawn.
    """
    base = proc.read_ptr(AREA_LIST)
    count = proc.read_i32(AREA_COUNT)
    if not base or not count or count <= 0:
        return []
    blob = proc.read_chunked(base, AREA_STRIDE * count)
    if len(blob) < AREA_STRIDE * count:
        return []
    names = _messages(proc, MSG_MAP)
    out: List[Area] = []
    for i in range(count):
        off = i * AREA_STRIDE
        index = struct.unpack_from("<i", blob, off + A_INDEX)[0]
        x, y, size = struct.unpack_from("<3i", blob, off + A_X)
        state = struct.unpack_from("<i", blob, off + A_STATE)[0]
        n_ent = struct.unpack_from("<i", blob, off + A_ENTRANCE_COUNT)[0]
        # The index in the record is the one map.msg is keyed by. It has matched
        # the position in the table on every install seen, but reading it is
        # free and trusting the position is an assumption.
        name = names.get(MSG_AREA_BASE + index)
        if not name:
            # No message for it. Fall back to city.txt's internal name rather
            # than to silence -- an odd-looking name is still a name, and this
            # is what a content mod that adds an area without a message will
            # hit.
            name = blob[off:off + 40].split(b"\0")[0].decode("cp1252", "replace")
        entrances: List[Entrance] = []
        for e in range(max(0, min(n_ent, MAX_ENTRANCES))):
            eo = off + A_ENTRANCES + e * ENTRANCE_STRIDE
            known, ex, ey, map_index, elevation, tile, orientation = \
                struct.unpack_from("<7i", blob, eo)
            entrances.append(Entrance(
                index=e, known=bool(known), x=ex, y=ey, map_index=map_index,
                elevation=elevation, tile=tile, orientation=orientation,
                name=names.get(MSG_MAP_BASE + map_index * MSG_MAP_STRIDE, "")))
        out.append(Area(index=i, name=name, x=x, y=y, size=size, state=state,
                        entrances=entrances))
    return out


def known_areas(proc: Process) -> List[Area]:
    """The places the game has actually shown the player."""
    return [a for a in areas(proc) if a.on_map]


def area_at(proc: Process, sx: int, sy: int,
            table: Optional[List[Area]] = None) -> Optional[Area]:
    """The area whose marker sits on this subtile, if the player knows it."""
    table = areas(proc) if table is None else table
    for a in table:
        if a.on_map and a.subtile == (sx, sy):
            return a
    return None


def town_rows(proc: Process) -> List[int]:
    """The area indices behind the seven-row list, in the order it shows them.

    The engine builds this when the world map opens and the seven buttons index
    straight into it, offset by the scroll position. Reading it rather than
    rebuilding it from the area table is the whole point: whatever the engine
    put in this array is exactly what a sighted player is looking at, including
    the order.
    """
    base = proc.read_ptr(TOWN_ROWS)
    count = proc.read_i32(TOWN_ROW_COUNT)
    if not base or not count or count <= 0:
        return []
    blob = proc.read_chunked(base, 4 * count)
    if len(blob) < 4 * count:
        return []
    return list(struct.unpack("<%di" % count, blob))


def town_scroll_row(proc: Process) -> int:
    """Which entry of the list is at the top of the seven visible rows."""
    pixels = proc.read_i32(TOWN_SCROLL)
    return 0 if not pixels else pixels // ROW_HEIGHT


# -- screen and world --------------------------------------------------------


def to_screen(proc: Process, wx: int, wy: int,
              window_left: int, window_top: int) -> Optional[Tuple[int, int]]:
    """Where a world position is drawn, in absolute screen pixels.

    Returns None when it is not on screen at all, which is a real answer and not
    a failure: the viewport shows 450x443 of a 1400x1500 world, so most of the
    world is off the edge at any moment and has to be scrolled to before it can
    be clicked.
    """
    offset = scroll(proc)
    if offset is None:
        return None
    vx = wx - offset[0]
    vy = wy - offset[1]
    if not (0 <= vx < VIEW_W and 0 <= vy < VIEW_H):
        return None
    return (window_left + VIEW_LEFT + vx, window_top + VIEW_TOP + vy)


def to_world(scroll_x: int, scroll_y: int, mx: int, my: int) -> Tuple[int, int]:
    """The engine's own mouse-to-world conversion, from 0x004BFE7A."""
    return (mx + scroll_x - VIEW_LEFT, my + scroll_y - VIEW_TOP)


def centre_scroll(wx: int, wy: int, shape: Layout) -> Tuple[int, int]:
    """The scroll offset the engine picks when it centres on a position.

    Its own arithmetic, at 0x004C05C7: subtract half a viewport and clamp. Worth
    reproducing rather than approximating, because this is how the mod works out
    whether a target will be reachable after pressing Home.
    """
    max_x = shape.tiles_across * TILE_W - VIEW_W
    max_y = shape.tiles_down * TILE_H - VIEW_H
    x = min(max(wx - 203, 0), max(max_x, 0))
    y = min(max(wy - 200, 0), max(max_y, 0))
    return (x, y)
