#!/usr/bin/env python3
"""Are the screen-detection offsets still true of this executable?

Written after the Restoration Project Unofficial patched fallout2.exe in place:
same 1,189,888 bytes, different SHA256. Every address the mod holds is absolute
into that binary, so a patch that moves nothing and changes something is the
worst case -- the reads all succeed, and some of them are now about a different
variable.

The three below decide which screen the mod thinks it is on before a game is
loaded, and a wrong answer there is silent by construction: no screen detected
means no watcher, and no watcher means nothing is announced. That is exactly
what "the main menu sometimes reads and the editor is mute" looks like from the
inside.

    python tools/checkoffsets.py

Leave it running and walk the game from the main menu into character creation.
Each line is one reading; the verdict is what the mod would do with it.

What good looks like:

    main menu           menu=1  editor=0  window=-1   -> MAIN_MENU
    character selection menu=0  editor=1  window=-1   -> SELECT
    character editor    menu=0  editor=0  window>=0   -> CHARGEN

Anything else -- a window handle that is never negative, a menu flag that never
reaches 1, two flags that both read 1 -- is an address that no longer means what
its name says, and the fix is to find it again in the new binary rather than to
argue with the reading.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fallout2_access.game import screens                      # noqa: E402
from fallout2_access.memory.process import (                  # noqa: E402
    FALLOUT_EXE_NAMES, Process, ProcessNotFound,
)

WATCH = [
    ("menu", screens.MENU_FLAG, "1 on the main menu"),
    ("editor", screens.EDITOR_FLAG, "1 on character selection"),
    ("window", screens.EDITOR_WINDOW, ">= 0 only in the editor"),
]


def main() -> int:
    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except (ProcessNotFound, OSError):
        print("Fallout 2 is not running. Start it, then run this again.")
        return 1

    print("attached to pid {} in {}".format(proc.pid, proc.directory or "?"))
    for name, addr, why in WATCH:
        print("  {:7} 0x{:08X}  {}".format(name, addr, why))
    print("\nWalk from the main menu into character creation. Ctrl+C to stop.\n")

    last = None
    while True:
        vals = [proc.read_i32(addr) for _, addr, _ in WATCH]
        # detect() is asked with in_game=False: before a game loads there is no
        # script and so no game mode, which is the path that is misbehaving.
        verdict = screens.detect(proc, in_game=False, mode=None)
        row = (tuple(vals), verdict)
        if row != last:
            last = row
            print("menu={:<6} editor={:<6} window={:<12} -> {}".format(
                *[("?" if v is None else v) for v in vals], verdict))
        time.sleep(0.2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
