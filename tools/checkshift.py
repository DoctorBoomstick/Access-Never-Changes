#!/usr/bin/env python3
"""Did RPU's eight-byte shift move the window list too?

The character editor's window handle came out of the Restoration Project
Unofficial eight bytes lower than it went in, 0x006ADDA8 -> 0x006ADDA0, found by
watching it flip sign across four editor open/closes. An insertion that moves
one global moves its neighbours, and uiwindow.py keeps two in the same
neighbourhood, both ABOVE the one that moved:

    WINDOW_LIST  = 0x006ADE58
    WINDOW_COUNT = 0x006ADF24

pointer.py's addresses are all BELOW it (0x006AC750, 0x006ABD74) and pointing
still works in play, which is the shape you would expect if something were
removed at 0x006ADDA0: everything after slides, everything before does not.

So this reads both the recorded address and the same address minus eight, and
asks which one looks like a window list at all. That is a question the data can
answer for itself:

    the count must be a small positive number -- there are never fifty windows
    open -- and the entries must be pointers into the heap that dereference to
    a struct whose width and height match its own left/top/right/bottom.

A shape that self-consistent is not something a wrong address produces by
accident, and a wrong address here is not harmless: find_window_at prefers the
richest match, so a garbage list means the mod points at a panel that is not
there, which is what "moving items between inventory and hands is fucked" looks
like from the inside.

    python tools/checkshift.py

Run it with the INVENTORY OPEN, so there is a real window list to read.
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fallout2_access.memory.process import (                  # noqa: E402
    FALLOUT_EXE_NAMES, Process, ProcessNotFound,
)

WINDOW_LIST = 0x006ADE58
WINDOW_COUNT = 0x006ADF24
SHIFT = -8

PTR_MIN = 0x00010000
PTR_MAX = 0x7FFF0000


def describe(proc: Process, list_addr: int, count_addr: int) -> None:
    print("  list 0x{:08X}  count 0x{:08X}".format(list_addr, count_addr))
    count = proc.read_i32(count_addr)
    print("    count reads {}".format(count))
    if count is None or not (0 < count <= 51):
        print("    -> not a window count (expected a small positive number)")
        return

    blob = proc.read_chunked(list_addr, 4 * count)
    if not blob or len(blob) < 4 * count:
        print("    -> could not read the array")
        return

    good = 0
    for i in range(count):
        ptr = struct.unpack_from("<I", blob, i * 4)[0]
        if not PTR_MIN <= ptr <= PTR_MAX:
            print("    [{}] 0x{:08X}  not a heap pointer".format(i, ptr))
            continue
        data = proc.read(ptr, 32)
        if not data or len(data) < 32:
            print("    [{}] 0x{:08X}  unreadable".format(i, ptr))
            continue
        wid, flags, l, t, r, b, w, h = struct.unpack_from("<8i", data, 0)
        # The self-check: a real GNW window's width and height agree with its
        # own edges. Noise does not.
        ok = (w == r - l + 1 and h == b - t + 1 and 0 < w <= 4096
              and 0 < h <= 4096)
        print("    [{}] 0x{:08X}  {}x{} at ({},{})-({},{}) {}".format(
            i, ptr, w, h, l, t, r, b, "OK" if ok else "<- inconsistent"))
        if ok:
            good += 1
    print("    -> {} of {} entries are self-consistent windows".format(
        good, count))


def main() -> int:
    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except (ProcessNotFound, OSError):
        print("Fallout 2 is not running. Start it, then run this again.")
        return 1

    print("attached to pid {}\n".format(proc.pid))
    print("AS RECORDED (correct on the retail Steam build):")
    describe(proc, WINDOW_LIST, WINDOW_COUNT)
    print("\nSHIFTED BY {} (the same move the editor handle made):".format(SHIFT))
    describe(proc, WINDOW_LIST + SHIFT, WINDOW_COUNT + SHIFT)
    print("\nWhichever block lists self-consistent windows is the live one.")
    print("If NEITHER does, the list moved by something other than eight and "
          "wants its own hunt rather than an assumption.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
