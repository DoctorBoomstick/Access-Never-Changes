#!/usr/bin/env python3
"""Find the interface bar's display window in memory.

The strip along the bottom of the screen is where Fallout tells the player
everything in words -- "You see: a door", "It's locked", who hit whom for how
much. Nothing in sfall reads it back, so it has to be located in the game's
memory and read directly.

The trick that makes this easy: we can *write* to it. `gl_world.ssl` binds the
backslash key to `display_msg("ANCPROBE7F3C9D51")`, so we put a string we chose
into the buffer and then go looking for exactly that. No differential narrowing,
no shortlist of candidates to eliminate -- one scan and the address is known.

    python tools/findmsgwindow.py

The game must be running, in a loaded game, with the mod's scripts installed.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fallout2_access.input.send import (  # noqa: E402
    find_game_window,
    guarded_tap,
    require_focus,
)
from fallout2_access.memory.process import (  # noqa: E402
    FALLOUT_EXE_NAMES,
    Process,
)

MARKER = b"ANCPROBE7F3C9D51"


def scan_for(proc: Process, needle: bytes):
    """Every address in the process holding `needle`."""
    hits = []
    for region in proc.regions():
        if region.size > 64 * 1024 * 1024:
            continue  # a single allocation that large is not a text buffer
        data = proc.read_chunked(region.base, region.size)
        if not data:
            continue
        start = 0
        while True:
            found = data.find(needle, start)
            if found < 0:
                break
            hits.append((region.base + found, region))
            start = found + 1
    return hits


def context(proc: Process, addr: int, before: int = 64, after: int = 192) -> bytes:
    return proc.read_chunked(addr - before, before + after) or b""


def printable(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def main() -> int:
    proc = Process.attach(FALLOUT_EXE_NAMES)
    hwnd = find_game_window(proc.pid)
    print("attached to pid {} ({})".format(proc.pid, proc.directory))
    if not hwnd:
        print("no game window")
        return 1

    require_focus(hwnd)
    time.sleep(0.3)

    print("pressing backslash to print the marker ...")
    guarded_tap(hwnd, "backslash", settle=0.6)

    print("scanning ...")
    t0 = time.time()
    hits = scan_for(proc, MARKER)
    print("{} hit(s) in {:.1f}s\n".format(len(hits), time.time() - t0))

    if not hits:
        print("The marker is not in memory. Either the script did not run (a\n"
              "game restart is needed after any .ssl change) or backslash did\n"
              "not reach the game. Check debug.log for a WORLD:marker line.")
        return 1

    for addr, region in hits:
        print("=" * 70)
        print("0x{:08X}   (region 0x{:08X} + 0x{:X}, {} bytes)".format(
            addr, region.base, addr - region.base, region.size))
        data = context(proc, addr)
        for row in range(0, len(data), 32):
            chunk = data[row:row + 32]
            print("  0x{:08X}  {}".format(addr - 64 + row, printable(chunk)))
        print()

    print("Press backslash again by hand and re-run to see which of these is a\n"
          "live buffer rather than a one-off copy: the address that keeps\n"
          "changing as the game talks is the display window.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
