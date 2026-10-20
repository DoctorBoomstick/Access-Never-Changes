"""Fake process memory, laid out the way the game really lays it out.

The save/load screen is recognised by its window being open, not by a flag, so
testing that recognition means building windows -- a pointer array, window
structs, and a linked list of buttons. That is more scaffolding than a fake
flag, and it buys the thing the flag could not: a test that can express "a
640x480 panel is open but it is the character sheet, not the save screen",
which is the case that a size-only check gets wrong.
"""

from __future__ import annotations

import struct

from fallout2_access.game import uiwindow

# Somewhere plausible for a heap. Nothing depends on the values.
WINDOW_BASE = 0x0A000000
BUTTON_BASE = 0x0B000000
STRIDE = 0x1000


class FakeMemory:
    """A byte-addressed fake with the two reads the real Process offers."""

    directory = r"C:\game"

    def __init__(self, values=None):
        self.bytes = {}
        self.values = dict(values or {})

    # -- building ----------------------------------------------------------

    def poke(self, addr: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.bytes[addr + i] = b

    def set_i32(self, addr: int, value: int) -> None:
        self.values[addr] = value

    # -- the Process interface used by the code under test -----------------

    def read_i32(self, addr):
        if addr in self.values:
            return self.values[addr]
        blob = self.read_chunked(addr, 4)
        if blob is None:
            return None
        return struct.unpack("<i", blob)[0]

    def read_chunked(self, addr, size):
        out = bytearray()
        for i in range(size):
            byte = self.bytes.get(addr + i)
            if byte is None:
                return None
            out.append(byte)
        return bytes(out)

    def read(self, addr, size):
        return self.read_chunked(addr, size)

    def read_u32(self, addr):
        if addr in self.values:
            return self.values[addr] & 0xFFFFFFFF
        blob = self.read_chunked(addr, 4)
        if blob is None:
            return None
        return struct.unpack("<I", blob)[0]

    def read_ptr(self, addr):
        return self.read_u32(addr)

    def read_i16(self, addr):
        blob = self.read_chunked(addr, 2)
        if blob is None:
            return None
        return struct.unpack("<h", blob)[0]

    def read_cstring(self, addr, max_len=256, encoding="cp1252"):
        out = bytearray()
        for i in range(max_len):
            byte = self.bytes.get(addr + i)
            if byte is None:
                break
            if byte == 0:
                break
            out.append(byte)
        if not out:
            return None
        return bytes(out).decode(encoding, errors="replace")

    def module_at(self, name, directory):
        return None


def memory_with_dialogue(reply, options, msglist=751, msgid=121,
                         count=None, values=None) -> FakeMemory:
    """A fake showing this conversation on screen.

    `count` defaults to len(options) but can be set lower on purpose, which is
    the case that matters: the engine never clears this array, it only
    overwrites it, so entries past the count are the *previous* conversation's
    replies sitting there fully readable.
    """
    from fallout2_access.game import dialogue

    mem = FakeMemory(values)
    mem.set_i32(dialogue.REPLY_MSGLIST, msglist)
    mem.set_i32(dialogue.REPLY_MSGID, msgid)
    mem.set_i32(dialogue.WINDOW, 6)
    mem.poke(dialogue.REPLY_TEXT, reply.encode("cp1252") + b"\x00")
    mem.set_i32(dialogue.OPTION_COUNT,
                len(options) if count is None else count)
    for index, text in enumerate(options):
        addr = (dialogue.OPTIONS + index * dialogue.OPTION_STRIDE
                + dialogue.OPTION_TEXT)
        # With the bullet the engine really puts in front of every reply.
        mem.poke(addr, b"\x95 " + text.encode("cp1252") + b"\x00")
    return mem


def _button(addr: int, press: int, nxt: int, rect=(0, 0, 10, 10),
            release: int = -1, bid: int = 1) -> bytes:
    blob = bytearray(b"\x00" * uiwindow.B_SIZE)
    left, top, right, bottom = rect
    struct.pack_into("<6i", blob, uiwindow.B_ID, bid, 0,
                     left, top, right, bottom)
    struct.pack_into("<i", blob, uiwindow.B_PRESS, press)
    struct.pack_into("<i", blob, uiwindow.B_RELEASE, release)
    struct.pack_into("<I", blob, uiwindow.B_NEXT, nxt)
    return bytes(blob)


def _window(wid: int, left: int, top: int, width: int, height: int,
            buttons_head: int) -> bytes:
    blob = bytearray(b"\x00" * uiwindow.W_SIZE)
    struct.pack_into("<8i", blob, 0, wid, 0, left, top,
                     left + width - 1, top + height - 1, width, height)
    struct.pack_into("<I", blob, uiwindow.W_BUTTONS, buttons_head)
    return bytes(blob)


def memory_with_windows(windows, values=None) -> FakeMemory:
    """Build a fake process showing exactly these windows as OPEN.

    `windows` is a list of (width, height, [press codes]). They are written into
    GNW's pointer array, so anything NOT listed here is not open -- which is the
    whole point: a window struct sitting in the heap unreferenced is a freed
    window, and treating one as visible is the bug this replaced.
    """
    mem = FakeMemory(values)
    pointers = []
    for index, (width, height, presses) in enumerate(windows):
        waddr = WINDOW_BASE + index * STRIDE
        head = 0
        for j, press in enumerate(reversed(list(presses))):
            baddr = BUTTON_BASE + (index * 16 + j) * STRIDE
            mem.poke(baddr, _button(baddr, press, head))
            head = baddr
        mem.poke(waddr, _window(index + 1, 0, 0, width, height, head))
        pointers.append(waddr)

    blob = b"".join(struct.pack("<I", p) for p in pointers)
    blob = blob.ljust(4 * uiwindow.MAX_WINDOWS, b"\x00")
    mem.poke(uiwindow.WINDOW_LIST, blob)
    mem.set_i32(uiwindow.WINDOW_COUNT, len(pointers))
    return mem


def memory_with_placed_windows(windows, values=None) -> FakeMemory:
    """The same, but each window has a position as well as a size.

    `windows` is a list of (left, top, width, height). The character editor's
    name, age and sex dialogs are all exactly 139x72 and are told apart by
    which of the three buttons they opened under, so a fake that puts every
    window at the origin cannot express the case at all -- it would agree with
    any implementation, including a wrong one.
    """
    mem = FakeMemory(values)
    pointers = []
    for index, (left, top, width, height) in enumerate(windows):
        waddr = WINDOW_BASE + index * STRIDE
        mem.poke(waddr, _window(index + 1, left, top, width, height, 0))
        pointers.append(waddr)

    blob = b"".join(struct.pack("<I", p) for p in pointers)
    blob = blob.ljust(4 * uiwindow.MAX_WINDOWS, b"\x00")
    mem.poke(uiwindow.WINDOW_LIST, blob)
    mem.set_i32(uiwindow.WINDOW_COUNT, len(pointers))
    return mem


def memory_with_release_windows(windows, values=None) -> FakeMemory:
    """Windows whose buttons carry their code in the RELEASE field.

    Which is how the Pip-Boy's are built, and the distinction is not cosmetic:
    a reader that only looks at `press` sees that panel as having no controls
    at all. `windows` is a list of (width, height, [(release, left, top)]),
    and each button is given the Pip-Boy's real row size so the rectangles a
    test asserts on are the shape the game really uses.

    `buttons` is given **head first**, which is the order GNW really holds them
    in: it prepends, so the newest button is the one you meet first. That is
    what lets a test express a page whose rows sit on top of an older page's
    leftovers, which is the situation the real panel is in most of the time.
    """
    mem = FakeMemory(values)
    pointers = []
    for index, (width, height, buttons) in enumerate(windows):
        waddr = WINDOW_BASE + index * STRIDE
        head = 0
        for j, (release, left, top) in enumerate(reversed(list(buttons))):
            baddr = BUTTON_BASE + (index * 64 + j) * STRIDE
            rect = (left, top, left + 349, top + 9)
            mem.poke(baddr, _button(baddr, -1, head, rect=rect,
                                    release=release, bid=100 + j))
            head = baddr
        mem.poke(waddr, _window(index + 1, 0, 0, width, height, head))
        pointers.append(waddr)

    blob = b"".join(struct.pack("<I", p) for p in pointers)
    blob = blob.ljust(4 * uiwindow.MAX_WINDOWS, b"\x00")
    mem.poke(uiwindow.WINDOW_LIST, blob)
    mem.set_i32(uiwindow.WINDOW_COUNT, len(pointers))
    return mem


def memory_with_pipboy(rows=(), values=None, stale=()) -> FakeMemory:
    """The Pip-Boy as the engine really presents it.

    `rows` is a list of (release code, top) for the page on screen; `stale` is
    the same for a page that was opened earlier and whose row buttons the
    engine never destroyed -- which really happens, and is why `pipboy.rows`
    has to know where the live run ends.
    """
    from fallout2_access.game import pipboy

    controls = [(pipboy.ALARM_CLOCK, 124, 13),
                (pipboy.STATUS, 53, 340),
                (pipboy.AUTOMAPS, 53, 394),
                (pipboy.ARCHIVES, 53, 423),
                (pipboy.CLOSE, 53, 449)]
    # Head first, and within a page the rows are met highest-code first: the
    # engine creates them in ascending order and prepends each one. Getting
    # this backwards would have the tests agree with a `rows()` that walked
    # from the wrong end.
    buttons = ([(code, 254, top) for code, top in reversed(list(rows))]
               + [(code, 254, top) for code, top in reversed(list(stale))]
               + list(reversed(controls)))
    return memory_with_release_windows(
        [(pipboy.PANEL_WIDTH, pipboy.PANEL_HEIGHT, buttons)], values)


QUEST_TABLE_AT = 0x0C300000
HOLODISK_TABLE_AT = 0x0C310000
GLOBALS_AT = 0x0C320000


def with_pipboy_tables(mem: FakeMemory, quests=(), holodisks=(),
                       variables=(), movies=()) -> FakeMemory:
    """Give a fake the tables the Pip-Boy builds its lists from.

    `quests` is (location, description, gvar, display, completed) tuples,
    `holodisks` is (gvar, name, text), `variables` is the game's global
    variable array and `movies` the indices of the films that have been seen.

    Written as the engine writes them -- a heap array and a static pointer and
    count -- because the case that matters most is the one where the pointer is
    null: both tables are freed the moment the panel closes, so "not there" is
    an ordinary state and not a fault.
    """
    from fallout2_access.game import pipboy

    def table(addr, rows, ptr_at, count_at):
        blob = b"".join(struct.pack("<%di" % len(r), *r) for r in rows)
        mem.poke(addr, blob)
        mem.set_i32(ptr_at, addr)
        mem.set_i32(count_at, len(rows))

    table(QUEST_TABLE_AT, list(quests), pipboy.QUEST_TABLE, pipboy.QUEST_COUNT)
    table(HOLODISK_TABLE_AT, list(holodisks), pipboy.HOLODISK_TABLE,
          pipboy.HOLODISK_COUNT)
    mem.poke(GLOBALS_AT,
             b"".join(struct.pack("<i", v) for v in variables))
    mem.set_i32(pipboy.GAME_GLOBALS, GLOBALS_AT)
    seen = bytearray(pipboy.MOVIE_LAST + 1)
    for index in movies:
        seen[index] = 1
    mem.poke(pipboy.MOVIES_SEEN, bytes(seen))
    return mem


def close_top_window(mem: FakeMemory) -> FakeMemory:
    """Close the last window the way GNW really closes one.

    Not by clearing the pointer -- that is what the code wrongly assumed and
    what a naive fake would do, agreeing with the bug. The engine drops the
    count and leaves the pointer in place, so the struct stays readable and
    valid for as long as nothing else reuses the slot.
    """
    count = mem.read_i32(uiwindow.WINDOW_COUNT) or 0
    mem.set_i32(uiwindow.WINDOW_COUNT, max(0, count - 1))
    return mem


# -- the world map -----------------------------------------------------------
#
# Laid out the way the engine lays it out, for the same reason the window fakes
# are: the thing worth testing is the arithmetic between world pixels, subtiles
# and tiles, and a fake that stored subtiles in a flat dict would agree with any
# indexing the code happened to use. This one puts them row-major inside their
# tile, which is where they really are, so reading them column-major fails here
# exactly as it failed against the game.

WM_TILES_AT = 0x0C000000
WM_AREAS_AT = 0x0C100000
WM_ROWS_AT = 0x0C200000
WM_MSG_MAP_AT = 0x0C300000
WM_MSG_WORLD_AT = 0x0C400000
WM_TEXT_AT = 0x0C500000


def _message_list(mem: FakeMemory, global_addr: int, entries_at: int,
                  text_at: int, messages) -> int:
    """Write a MessageList the way the engine parses one, and point at it.

    Returns the address just past the strings, so several lists can be laid
    down one after another.
    """
    cursor = text_at
    blob = bytearray()
    for num, text in sorted(messages.items()):
        raw = text.encode("cp1252") + b"\0"
        mem.poke(cursor, raw)
        blob += struct.pack("<iiII", num, 0, 0, cursor)
        cursor += len(raw)
    mem.poke(entries_at, bytes(blob))
    mem.set_i32(global_addr, len(messages))
    mem.set_i32(global_addr + 4, entries_at)
    return cursor


def memory_with_worldmap(player=(174, 123), areas=(), subtiles=None,
                         rows=(), tiles_across=4, tile_count=20,
                         scroll=(0, 0), destination=(0, 0), travelling=0,
                         current_area=-1, terrain=None, values=None):
    """A world map, as the engine holds one.

    `areas` is a sequence of dicts with name, x, y, state and entrances;
    `subtiles` maps (x, y) to (terrain, state). Anything not named gets
    unexplored desert, which is what most of the world is.
    """
    from fallout2_access.game import worldmap

    mem = FakeMemory(values)
    mem.set_i32(worldmap.WORLD_X, player[0])
    mem.set_i32(worldmap.WORLD_Y, player[1])
    mem.set_i32(worldmap.SCROLL_X, scroll[0])
    mem.set_i32(worldmap.SCROLL_Y, scroll[1])
    mem.set_i32(worldmap.DEST_X, destination[0])
    mem.set_i32(worldmap.DEST_Y, destination[1])
    mem.set_i32(worldmap.TRAVELLING, travelling)
    mem.set_i32(worldmap.CURRENT_AREA, current_area)
    mem.set_i32(worldmap.TILES_ACROSS, tiles_across)
    mem.set_i32(worldmap.TILE_COUNT, tile_count)
    mem.set_i32(worldmap.TILE_LIST, WM_TILES_AT)
    mem.set_i32(worldmap.AREA_LIST, WM_AREAS_AT)
    mem.set_i32(worldmap.AREA_COUNT, len(areas))
    mem.set_i32(worldmap.TOWN_ROWS, WM_ROWS_AT)
    mem.set_i32(worldmap.TOWN_ROW_COUNT, len(rows))
    mem.set_i32(worldmap.TOWN_SCROLL, 0)
    for i in range(worldmap.ENCOUNTER_CHANCE_COUNT):
        mem.set_i32(worldmap.ENCOUNTER_CHANCE + i * 4, (0, 6, 15, 27, 43, 100)[i])

    # The tiles, and their subtiles row-major within each.
    subtiles = dict(subtiles or {})
    for tile in range(tile_count):
        base = WM_TILES_AT + tile * worldmap.TILE_STRIDE
        mem.poke(base, bytes(worldmap.TILE_STRIDE))
        tx, ty = tile % tiles_across, tile // tiles_across
        for sy in range(worldmap.SUB_DOWN):
            for sx in range(worldmap.SUB_ACROSS):
                gx = tx * worldmap.SUB_ACROSS + sx
                gy = ty * worldmap.SUB_DOWN + sy
                ground, state = subtiles.get((gx, gy), (0, worldmap.UNKNOWN))
                off = (worldmap.TILE_SUBTILES
                       + (sy * worldmap.SUB_ACROSS + sx) * worldmap.SUBTILE_STRIDE)
                mem.poke(base + off, struct.pack(
                    "<7i", ground, 0, 1, 1, 1, 6, state))

    # The areas.
    names = {}
    for i, area in enumerate(areas):
        base = WM_AREAS_AT + i * worldmap.AREA_STRIDE
        mem.poke(base, bytes(worldmap.AREA_STRIDE))
        mem.poke(base, area.get("internal", area["name"]).encode("cp1252")[:39] + b"\0")
        mem.poke(base + worldmap.A_INDEX, struct.pack(
            "<4i", i, area["x"], area["y"], area.get("size", 1)))
        # State and the town picture's art id, which the engine tests together
        # before it will show a town map.
        mem.poke(base + worldmap.A_STATE,
                 struct.pack("<2i", area.get("state", worldmap.UNKNOWN),
                             area.get("label_fid", 0x0600009C)))
        entrances = area.get("entrances", ())
        mem.poke(base + worldmap.A_ENTRANCE_COUNT,
                 struct.pack("<i", len(entrances)))
        for e, ent in enumerate(entrances):
            mem.poke(base + worldmap.A_ENTRANCES + e * worldmap.ENTRANCE_STRIDE,
                     struct.pack("<7i", ent.get("known", 1), ent.get("x", 100),
                                 ent.get("y", 100), ent.get("map", 4 + e),
                                 -1, -1, 0))
            names[worldmap.MSG_MAP_BASE
                  + ent.get("map", 4 + e) * worldmap.MSG_MAP_STRIDE] = \
                ent.get("name", "Way {}".format(e))
        names[worldmap.MSG_AREA_BASE + i] = area["name"]

    mem.poke(WM_ROWS_AT, b"".join(struct.pack("<i", r) for r in rows))

    # map.msg holds the area and map names; worldmap.msg holds the terrain.
    after = _message_list(mem, worldmap.MSG_MAP, WM_MSG_MAP_AT, WM_TEXT_AT, names)
    ground = terrain or {0: "Desert", 1: "Mountains", 2: "City", 3: "Coast"}
    _message_list(mem, worldmap.MSG_WORLDMAP, WM_MSG_WORLD_AT, after,
                  {worldmap.MSG_TERRAIN_BASE + k: v for k, v in ground.items()})
    return mem
