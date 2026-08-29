"""Read the engine's own windows and buttons out of memory.

Fallout 2 draws its interface with GNW, and GNW keeps, for every open window, a
linked list of its buttons -- each with a rectangle and the event codes it
raises. That list is the answer to the question this mod kept running into: a
blind player cannot point at a thing, and until now the mod could not say where
any UI thing *was*.

It is worth being precise about why this beats the alternatives that were on
the table:

**Better than hardcoded pixels.** The rectangles are read from the running game,
so a different resolution, a patch, or the high-res patch moving a window
changes nothing here. Nothing is measured off a screenshot and frozen.

**Better than a scroll-offset hunt.** The six rows of an inventory list turn out
to be six separate buttons with consecutive event codes, so which row is which
is something the engine states rather than something we work out from a scroll
position we would have had to go and find.

**And it found a keyboard route nobody expected.** Event codes below 256 are
keyboard codes: GNW's input loop puts button presses and key presses in one
stream, so a button whose code is 65 is a button that `A` already presses.
Measured live -- the loot window's TAKE ALL carries code 65, and pressing `A`
moved the pot's contents into the player's pack with no pointer involved at all.
That is a whole class of interface that was assumed to need aiming and does not.

**Layout**, confirmed against the live process by finding the interface bar --
whose rectangle the in-game script reports independently through sfall -- and
checking the struct that holds it. The bar reported 112,668 800x100 and id 4;
the struct at that address reads id 4, flags 2, rect 112,668,911,767, 800, 100.
Nothing here is inferred from a decompilation; it is inferred from a window the
game itself told us the shape of.
"""

from __future__ import annotations

import struct
from typing import Dict, List, NamedTuple, Optional

# -- Window --------------------------------------------------------------
W_ID = 0x00
W_FLAGS = 0x04
W_LEFT = 0x08
W_TOP = 0x0C
W_RIGHT = 0x10
W_BOTTOM = 0x14
W_WIDTH = 0x18
W_HEIGHT = 0x1C
W_BUTTONS = 0x30      # head of the button list
W_SIZE = 0x40

# -- Button --------------------------------------------------------------
B_ID = 0x00
B_FLAGS = 0x04
B_LEFT = 0x08
B_TOP = 0x0C
B_RIGHT = 0x10
B_BOTTOM = 0x14
B_ENTER = 0x18
B_EXIT = 0x1C
B_PRESS = 0x20        # the code raised when the button is pressed
B_RELEASE = 0x24
B_NEXT = 0x78
B_SIZE = 0x7C

# An event code below this is a keyboard code, and the key that produces it
# presses the button.
#
# Above it does NOT mean "only a click will do", which this comment used to say.
# Fallout keeps the nav cluster at 256 + scancode -- 328 up, 331 left, 333
# right, 336 down, 329 and 337 the page keys -- so those are keyboard codes too.
# The save screen's page arrows carry exactly those as their mouse-UP codes,
# which is a fact about how the buttons were built and not an invitation to
# press the key: tried on the live screen, left and right arrow did nothing
# while the same buttons clicked worked. Read it as a hint to test, never as a
# route to assume.
KEY_CODE_MAX = 256

# Sanity bounds. A window cannot be bigger than any screen the game runs at,
# and these bounds are what stop a heap coincidence being read as a window.
MAX_SCREEN = 4096
MAX_BUTTONS = 128


class Button(NamedTuple):
    id: int
    flags: int
    left: int         # window-relative
    top: int
    right: int
    bottom: int
    press: int        # event code raised on press
    addr: int
    # The code raised when the button is RELEASED, which for some screens is
    # the only one there is. Every button in the Pip-Boy carries -1 in `press`
    # and its real code here -- so does every button on the interface bar, where
    # the Pip-Boy's own 'p' lives. A reader that only looked at `press` saw
    # those windows as having no working buttons at all, which is exactly how
    # the Pip-Boy managed to look unreachable while GNW was describing it fully.
    release: int = -1

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1

    @property
    def key(self) -> Optional[int]:
        """The keyboard code that presses this button, if one does.

        This is the discovery that changes what is reachable without a pointer.
        """
        if 0 < self.press < KEY_CODE_MAX:
            return self.press
        return None

    def centre(self, window: "Window") -> tuple:
        """Absolute client coordinates of the middle of this button."""
        return (window.left + (self.left + self.right) // 2,
                window.top + (self.top + self.bottom) // 2)


class Window(NamedTuple):
    id: int
    flags: int
    left: int
    top: int
    width: int
    height: int
    addr: int
    buttons: List[Button]

    def by_press(self, code: int) -> Optional[Button]:
        for b in self.buttons:
            if b.press == code:
                return b
        return None

    def by_code(self, code: int) -> Optional[Button]:
        """The button this code belongs to, whichever field carries it.

        Screens are not consistent about which of the two they use, and being
        wrong about it does not read as "wrong field" -- it reads as the screen
        having no buttons. Ask for the code and let the button say where it
        keeps it.
        """
        for b in self.buttons:
            if code in (b.press, b.release):
                return b
        return None

    def keyed(self) -> Dict[int, Button]:
        """Every button a key already presses, by keyboard code."""
        return {b.key: b for b in self.buttons if b.key is not None}


def _read_buttons(proc, head: int) -> List[Button]:
    """Walk the button list from `head`."""
    out: List[Button] = []
    seen = set()
    node = head
    while node and node not in seen and len(out) < MAX_BUTTONS:
        seen.add(node)
        blob = proc.read_chunked(node, B_SIZE)
        if not blob or len(blob) < B_SIZE:
            break
        bid, flags, l, t, r, b = struct.unpack_from("<6i", blob, B_ID)
        press = struct.unpack_from("<i", blob, B_PRESS)[0]
        release = struct.unpack_from("<i", blob, B_RELEASE)[0]
        nxt = struct.unpack_from("<I", blob, B_NEXT)[0]
        # A button's rectangle is window-relative and cannot be inside out.
        # This is what stops the walk following a stale pointer into noise.
        if not (0 <= l <= r < MAX_SCREEN and 0 <= t <= b < MAX_SCREEN):
            break
        out.append(Button(id=bid, flags=flags, left=l, top=t, right=r,
                          bottom=b, press=press, addr=node, release=release))
        node = nxt
    return out


def _plausible(wid: int, l: int, t: int, r: int, b: int, w: int, h: int) -> bool:
    """Does this look like a window rather than a heap coincidence?

    The width and height fields must agree with the rectangle. That one check
    does nearly all the work: four unrelated integers almost never satisfy it.
    """
    if not (0 < wid < 10000):
        return False
    if not (0 <= l < r < MAX_SCREEN and 0 <= t < b < MAX_SCREEN):
        return False
    if w != r - l + 1 or h != b - t + 1:
        return False
    return 0 < w < MAX_SCREEN and 0 < h < MAX_SCREEN


# GNW's array of pointers to the windows that are actually OPEN, in draw order,
# ending at the first null. Found by taking windows identified by shape and
# searching the executable's static data for their addresses: five of them
# turned up four bytes apart, which is an array or nothing.
#
# This is the difference between "a window with this shape exists somewhere in
# the heap" and "this window is on screen", and the difference is not academic.
# Searching by shape finds FREED windows too -- they keep their fields, which is
# why `find_window_at` prefers the richest match -- so once the save screen had
# been opened, a dead 640x480 struct sat in the heap for the rest of the session
# and answered "yes, the save screen is showing" for ever after.
WINDOW_LIST = 0x006ADE58

# How many of those entries are real. **Closing a window does not clear its
# pointer** -- measured: the inventory was closed, the world resumed ticking,
# and its slot still held a perfectly valid 499x377 window struct. GNW drops the
# count and leaves the pointer where it lies.
#
# So a reader that walks until the first null reports windows that are shut, and
# it does so exactly when it matters most: the window that closes is usually the
# top one, which is the last entry, so its stale pointer is the one still there.
# That is the same failure as the flag this list replaced -- a screen that will
# not go away -- arrived at by a different route.
#
# It sits 204 bytes past the array, so the array is 51 entries.
WINDOW_COUNT = 0x006ADF24
MAX_WINDOWS = (WINDOW_COUNT - WINDOW_LIST) // 4


def live_window_addresses(proc) -> List[int]:
    """The address of every window currently open, in draw order."""
    count = proc.read_i32(WINDOW_COUNT)
    if count is None or count <= 0:
        return []
    count = min(count, MAX_WINDOWS)
    blob = proc.read_chunked(WINDOW_LIST, 4 * count)
    if not blob:
        return []
    out: List[int] = []
    for i in range(min(count, len(blob) // 4)):
        ptr = struct.unpack_from("<I", blob, i * 4)[0]
        if ptr:
            out.append(ptr)
    return out


def live_windows(proc, buttons: bool = False) -> List[Window]:
    """Every window currently open, read through GNW's own list.

    `buttons` is off by default because walking a button list costs a read per
    button and most callers only want the shapes.
    """
    out: List[Window] = []
    for addr in live_window_addresses(proc):
        blob = proc.read_chunked(addr, W_SIZE)
        if not blob or len(blob) < W_SIZE:
            continue
        wid, flags, l, t, r, b, w, h = struct.unpack_from("<8i", blob, 0)
        if not _plausible(wid, l, t, r, b, w, h):
            continue
        head = struct.unpack_from("<I", blob, W_BUTTONS)[0]
        out.append(Window(id=wid, flags=flags, left=l, top=t, width=w, height=h,
                          addr=addr,
                          buttons=_read_buttons(proc, head) if (buttons and head)
                          else []))
    return out


def live_window_with(proc, width: int, height: int, press: Optional[int] = None,
                     release: Optional[int] = None) -> Optional[Window]:
    """An open window of this size carrying a button with this event code.

    Size alone is not enough to name a screen: at this resolution the character
    sheet, the Pipboy and the save screen are all 640x480 panels. The button is
    what says which one it is.

    `press` and `release` are separate because which field a screen uses is a
    fact about how its buttons were built, not something to be inferred: the
    save screen's page arrows answer to `press` and every Pip-Boy control
    answers to `release`. A caller that asks the wrong one finds nothing, and
    "nothing" is indistinguishable from "that screen is not up".
    """
    for win in live_windows(proc):
        # Size first, buttons only for the few that match. This runs on every
        # poll tick, and walking the button list of every open window -- the
        # interface bar alone has ten -- to answer a question the size already
        # settles is work for nothing.
        if (win.width, win.height) != (width, height):
            continue
        blob = proc.read_chunked(win.addr, W_SIZE)
        if not blob or len(blob) < W_SIZE:
            continue
        head = struct.unpack_from("<I", blob, W_BUTTONS)[0]
        buttons = _read_buttons(proc, head) if head else []
        if press is not None and any(b.press == press for b in buttons):
            return win._replace(buttons=buttons)
        if release is not None and any(b.release == release for b in buttons):
            return win._replace(buttons=buttons)
    return None


def find_windows(proc, want_id: Optional[int] = None) -> List[Window]:
    """Every open GNW window, newest allocations last.

    Scanned for by shape rather than read from a fixed address, because the
    window list is heap and moves every launch -- the same reason the message
    ring has to be found rather than addressed.

    **Slow, and not for the running mod.** This walks every four-byte offset of
    every writable region, which on a live game is tens of millions of unpacks
    and takes ten seconds or more. It exists for exploring an unfamiliar screen
    from a tool. Anything that already knows the rectangle it wants -- which
    means anything the script has reported -- must use `find_window_at`, which
    searches for the rectangle as bytes and returns in a moment.
    """
    out: List[Window] = []
    for region in proc.regions(writable_only=True):
        data = proc.read_chunked(region.base, region.size)
        if len(data) < W_SIZE:
            continue
        for off in range(0, len(data) - W_SIZE, 4):
            wid, flags, l, t, r, b, w, h = struct.unpack_from("<8i", data, off)
            if not _plausible(wid, l, t, r, b, w, h):
                continue
            if want_id is not None and wid != want_id:
                continue
            head = struct.unpack_from("<I", data, off + W_BUTTONS)[0]
            buttons = _read_buttons(proc, head) if head else []
            out.append(Window(id=wid, flags=flags, left=l, top=t, width=w,
                              height=h, addr=region.base + off,
                              buttons=buttons))
    return out


def find_window_at(proc, left: int, top: int, width: int, height: int,
                   first_region: Optional[int] = None) -> Optional[Window]:
    """The window with exactly this rectangle, and the most buttons.

    Preferred over searching by id, because the in-game script can ask sfall for
    a window's rectangle directly -- so matching on it means the struct we found
    is *confirmed* by the engine rather than assumed from a layout guess. Ids
    repeat across windows; a rectangle at a given moment does not.

    More than one struct can carry the same rectangle: freed windows are left
    behind in the heap with their fields intact, and taking the first match
    found a dead one whose button list was a single degenerate entry. The live
    window is the one with buttons in it, so the richest match wins.

    **Searched as bytes, not by walking offsets.** The four rectangle fields are
    a sixteen-byte needle, so `bytes.find` does the whole hunt inside C. The
    obvious alternative -- step every four bytes and unpack a candidate struct --
    is what `find_windows` does, and on a live game that is tens of millions of
    unpacks: measured at ten to twelve seconds, during which the mod went
    completely silent, which is precisely the failure this project treats as
    worse than a wrong answer. It ran on every window open and every click.
    """
    rect = struct.pack("<4i", left, top, left + width - 1, top + height - 1)
    best: Optional[Window] = None
    regions = list(proc.regions(writable_only=True))
    if first_region is not None:
        # Look where it was last time first. Windows are reallocated constantly
        # but tend to land back in the same arena, so this usually turns a
        # 290 MB sweep into one small read.
        regions.sort(key=lambda r: not (r.base <= first_region < r.base + r.size))
    for index, region in enumerate(regions):
        data = proc.read_chunked(region.base, region.size)
        if len(data) >= W_SIZE:
            at = data.find(rect)
            while at >= 0:
                start = at - W_LEFT      # the rect sits at +0x08 in the struct
                if start >= 0 and start + W_SIZE <= len(data):
                    win = _window_from(proc, data, region.base, start)
                    if win is not None and (best is None
                                            or len(win.buttons) > len(best.buttons)):
                        best = win
                at = data.find(rect, at + 1)
        # If the hint paid off, stop. Reading the remaining quarter of a
        # gigabyte to look for a better match than a live window with buttons
        # in it is the whole cost this is trying to avoid.
        if index == 0 and first_region is not None and best is not None and best.buttons:
            return best
    return best


class WindowFinder:
    """Finds windows by rectangle, and remembers where it looked last.

    The search itself reads every writable region -- about 290 MB on a live
    game, which is two seconds however fast the matching is. Two seconds is
    nothing for a one-off tool and unacceptable inside a loop that is supposed
    to answer a keypress, so this remembers two things: the exact address a
    rectangle was found at, and the region it was in.

    A repeat lookup then costs one 64-byte read. The address is re-validated
    rather than trusted -- windows are freed and reallocated constantly, so a
    remembered address is a hypothesis, and the rectangle it holds is the test.
    """

    def __init__(self, proc) -> None:
        self.proc = proc
        self._addr: dict = {}          # rect -> struct address
        self._region: Optional[int] = None

    def _read(self, addr: int) -> Optional[Window]:
        blob = self.proc.read_chunked(addr, W_SIZE)
        if not blob or len(blob) < W_SIZE:
            return None
        return _window_from(self.proc, blob, addr, 0)

    def sized(self, width: int, height: int) -> Optional[Window]:
        """A window found by its size, cached the same way as by rectangle."""
        key = ("size", width, height)
        remembered = self._addr.get(key)
        if remembered is not None:
            win = self._read(remembered)
            if win and (win.width, win.height) == (width, height) and win.buttons:
                return win
        win = find_window_sized(self.proc, width, height,
                                first_region=self._region)
        if win is not None:
            self._addr[key] = win.addr
            self._region = win.addr & ~0xFFFFF
        return win

    def at(self, left: int, top: int, width: int, height: int) -> Optional[Window]:
        key = (left, top, width, height)

        remembered = self._addr.get(key)
        if remembered is not None:
            win = self._read(remembered)
            if win and (win.left, win.top, win.width, win.height) == key and win.buttons:
                return win

        win = find_window_at(self.proc, *key, first_region=self._region)
        if win is not None:
            self._addr[key] = win.addr
            self._region = win.addr & ~0xFFFFF
        return win

    def forget(self) -> None:
        self._addr.clear()
        self._region = None


def find_window_sized(proc, width: int, height: int,
                      first_region: Optional[int] = None) -> Optional[Window]:
    """The window of exactly this size, wherever it is, richest match winning.

    For panels whose position is not known in advance. Computing it from the
    game's client area does NOT work: Windows reports the client as 1536x864
    while the engine draws and places its windows in 1024x768 coordinates, so a
    panel worked out that way lands hundreds of pixels from the real thing --
    which is how the page buttons went unclickable while the same screen read
    perfectly.

    Searched on the packed width and height, which sit next to each other in the
    struct, so this is one more byte search rather than a walk.
    """
    size = struct.pack("<2i", width, height)
    best: Optional[Window] = None
    regions = list(proc.regions(writable_only=True))
    if first_region is not None:
        regions.sort(key=lambda r: not (r.base <= first_region < r.base + r.size))
    for index, region in enumerate(regions):
        data = proc.read_chunked(region.base, region.size)
        if len(data) >= W_SIZE:
            at = data.find(size)
            while at >= 0:
                start = at - W_WIDTH      # width sits at +0x18 in the struct
                if start >= 0 and start + W_SIZE <= len(data):
                    win = _window_from(proc, data, region.base, start)
                    if win is not None and (best is None
                                            or len(win.buttons) > len(best.buttons)):
                        best = win
                at = data.find(size, at + 1)
        if index == 0 and first_region is not None and best is not None and best.buttons:
            return best
    return best


def _window_from(proc, data: bytes, region_base: int, off: int
                 ) -> Optional[Window]:
    """Build a Window from a candidate struct already in `data`."""
    wid, flags, l, t, r, b, w, h = struct.unpack_from("<8i", data, off)
    if not _plausible(wid, l, t, r, b, w, h):
        return None
    head = struct.unpack_from("<I", data, off + W_BUTTONS)[0]
    buttons = _read_buttons(proc, head) if head else []
    return Window(id=wid, flags=flags, left=l, top=t, width=w, height=h,
                  addr=region_base + off, buttons=buttons)
