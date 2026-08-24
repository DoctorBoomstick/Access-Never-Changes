#!/usr/bin/env python3
"""Find the character editor's window handle again, in a patched executable.

The Restoration Project Unofficial rewrote fallout2.exe in place -- same
1,189,888 bytes, different SHA256 -- and EDITOR_WINDOW (0x006ADDA8) stopped
meaning anything. Measured on the live game with tools/checkoffsets.py: it read
-1 on the main menu, -1 on character selection, and -1 *in the editor itself*,
where it is the whole basis for detecting that screen. So CHARGEN was never
returned, no watcher ever started, and character creation was silent.

Nothing else was wrong. In a loaded game the screen comes from the script's
game mode rather than from any address here, which is why the mod behaves
perfectly once you are actually playing and only the pre-game screens are mute.

**The test is the flip, not the value.** A handle that is >= 0 in the editor
proves nothing on its own: a Fallout map is carpeted with words that happen to
be positive, and this codebase has already been fooled twice by a number that
rose convincingly and meant nothing -- the save screen's page and the
explosive's timer both produced one. What cannot be coincidence is a value that
goes negative when the editor closes and positive when it opens, again, in the
other direction. So this alternates and keeps only what flips every time.

    python tools/hunteditorwin.py

Follow the prompts: out of the editor, into the editor, out again, in again.
Two full cycles is usually enough to leave a handful of candidates; three
leaves one or two. Confirm the survivor with tools/checkoffsets.py before
putting it in screens.py.
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fallout2_access.memory.process import (                  # noqa: E402
    FALLOUT_EXE_NAMES, Process, ProcessNotFound,
)

# Enough cycles that a coincidence would have to survive four sign changes in
# the order we asked for them.
CYCLES = 2
LIST_WHEN = 25


def snapshot(proc: Process) -> dict:
    """Every 4-byte aligned int in the module's writable data, by address."""
    out = {}
    for region in proc.module_regions():
        blob = proc.read_chunked(region.base, region.size)
        if not blob:
            continue
        count = len(blob) // 4
        if not count:
            continue
        vals = struct.unpack_from("<{}i".format(count), blob, 0)
        base = region.base
        for i, v in enumerate(vals):
            out[base + i * 4] = v
    return out


def prompt(text: str) -> None:
    try:
        input("  {} -- then press Enter: ".format(text))
    except EOFError:
        raise SystemExit("\nstdin closed; run this from a real terminal")


def main() -> int:
    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except (ProcessNotFound, OSError):
        print("Fallout 2 is not running. Start it, then run this again.")
        return 1

    mod = proc.main_module()
    print("attached to pid {}, module 0x{:08X}-0x{:08X}".format(
        proc.pid, mod.base, mod.end))
    print("\nHunting a value that is NEGATIVE outside the character editor and")
    print("ZERO OR ABOVE inside it, and that flips back every time.\n")

    prompt("Get OUT of the editor (main menu is fine)")
    shot = snapshot(proc)
    cands = {a for a, v in shot.items() if v < 0}
    print("    {:,} addresses are negative here".format(len(cands)))

    for cycle in range(1, CYCLES + 1):
        prompt("Go INTO the character editor (cycle {}/{})".format(cycle, CYCLES))
        shot = snapshot(proc)
        cands = {a for a in cands if shot.get(a, -1) >= 0}
        print("    {:,} of those went to zero or above".format(len(cands)))
        if not cands:
            print("\nNothing survived. The handle may not be a signed int, or "
                  "may live outside the main module. Widen the scan before "
                  "trusting this result.")
            return 2

        prompt("Come back OUT of the editor (cycle {}/{})".format(cycle, CYCLES))
        shot = snapshot(proc)
        cands = {a for a in cands if shot.get(a, 0) < 0}
        print("    {:,} went negative again".format(len(cands)))
        if not cands:
            print("\nNothing survived the return trip. Everything that looked "
                  "right was rising for some other reason -- which is the "
                  "result this tool exists to produce rather than hide.")
            return 2

    print("\n{:,} candidate(s) survived {} full cycles.".format(
        len(cands), CYCLES))
    if len(cands) <= LIST_WHEN:
        old = 0x006ADDA8
        for addr in sorted(cands):
            mark = "   <-- the old EDITOR_WINDOW" if addr == old else ""
            print("    0x{:08X}  (module +0x{:X}){}".format(
                addr, addr - mod.base, mark))
        print("\nPut a survivor in screens.py as EDITOR_WINDOW, then confirm "
              "with tools/checkoffsets.py: it must read -1 on the menu, -1 on "
              "selection, and >= 0 in the editor.")
    else:
        print("Still too many. Run again and do more cycles, or narrow by "
              "opening and closing the editor from a different screen.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
