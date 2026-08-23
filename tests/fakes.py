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


def _button(addr: int, press: int, nxt: int) -> bytes:
    blob = bytearray(b"\x00" * uiwindow.B_SIZE)
    struct.pack_into("<6i", blob, uiwindow.B_ID, 1, 0, 0, 0, 10, 10)
    struct.pack_into("<i", blob, uiwindow.B_PRESS, press)
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
