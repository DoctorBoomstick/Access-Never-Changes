#!/usr/bin/env python3
"""Find a global that identifies which screen is showing.

The mod currently mistakes the premade-character selection screen for the
character editor, because the editor's selection index and SPECIAL array both
still look valid there. A real discriminator is needed so each screen only
speaks when it is actually on top.

Method: the two screens toggle cleanly -- Escape cancels the editor back to
selection, C re-enters it. So capture memory in editor, selection, editor,
selection, and keep only addresses that held one stable value in both editor
captures, a different stable value in both selection captures. Requiring
stability across the repeat is what rejects the counters and timers that merely
happen to differ once.

    python tools/huntscreen.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from array import array
from typing import Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fallout2_access.memory import FALLOUT_EXE_NAMES, Process, ProcessNotFound  # noqa: E402
from fallout2_access.input import (  # noqa: E402
    FocusLost,
    find_game_window,
    focus_window,
    guarded_tap,
)

SEL = 0x005709EC
OUT_PATH = os.path.join(_ROOT, "fallout2_access", "offsets", "screens.json")

Capture = List[Tuple[int, array]]


def capture(proc: Process, regions) -> Capture:
    out: Capture = []
    for r in regions:
        data = proc.read_chunked(r.base, r.size)
        usable = len(data) - (len(data) % 4)
        out.append((r.base, array("i", data[:usable])))
    return out


def stable_differences(
    a1: Capture, a2: Capture, b1: Capture, b2: Capture
) -> List[Tuple[int, int, int]]:
    """Addresses that are stably X in state A and stably Y != X in state B."""
    found: List[Tuple[int, int, int]] = []
    for (base, arr_a1), (_, arr_a2), (_, arr_b1), (_, arr_b2) in zip(a1, a2, b1, b2):
        n = min(len(arr_a1), len(arr_a2), len(arr_b1), len(arr_b2))
        for i in range(n):
            va = arr_a1[i]
            if va != arr_a2[i]:
                continue
            vb = arr_b1[i]
            if vb != arr_b2[i] or vb == va:
                continue
            found.append((base + i * 4, va, vb))
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", type=float, default=0.7,
                    help="seconds to wait after a screen change")
    ap.add_argument("--to-a", default="escape", help="key that leaves screen B for screen A")
    ap.add_argument("--to-b", default="c", help="key that leaves screen A for screen B")
    ap.add_argument("--name-a", default="A")
    ap.add_argument("--name-b", default="B")
    ap.add_argument("--start", choices=["a", "b"], default="b",
                    help="which screen we are on right now")
    args = ap.parse_args()

    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except ProcessNotFound as exc:
        print("not attached: {}".format(exc))
        return 2
    hwnd = find_game_window(proc.pid)
    if hwnd is None or not focus_window(hwnd):
        print("could not focus the game window")
        return 2

    regions = proc.module_regions()
    print("watching {:,} bytes of exe globals".format(sum(r.size for r in regions)))
    print("toggling {!r} --{}--> {!r} --{}--> back".format(
        args.name_b, args.to_a, args.name_a, args.to_b))

    def go_a() -> None:
        guarded_tap(hwnd, args.to_a, settle=args.settle)

    def go_b() -> None:
        guarded_tap(hwnd, args.to_b, settle=args.settle)

    if args.start == "a":
        go_b()

    # Now on B. Capture A,B,A,B so each state is sampled twice.
    go_a()
    print("capturing {} #1".format(args.name_a))
    a1 = capture(proc, regions)
    go_b()
    print("capturing {} #1".format(args.name_b))
    b1 = capture(proc, regions)
    go_a()
    print("capturing {} #2".format(args.name_a))
    a2 = capture(proc, regions)
    go_b()
    print("capturing {} #2".format(args.name_b))
    b2 = capture(proc, regions)

    ed1, ed2, sel1, sel2 = a1, a2, b1, b2
    hits = stable_differences(ed1, ed2, sel1, sel2)
    print("\n{} address(es) stably differ between the two screens".format(len(hits)))

    # Prefer small, flag-like values: a screen id is an enum, not a pointer.
    flaglike = [h for h in hits if -8 <= h[1] <= 64 and -8 <= h[2] <= 64]
    print("{} of them look like small enums/flags\n".format(len(flaglike)))

    shown = flaglike if flaglike else hits
    for addr, in_editor, in_select in shown[:40]:
        print("  0x{:08X}  {}={:<8} {}={}".format(
            addr, args.name_a, in_editor, args.name_b, in_select))
    if len(shown) > 40:
        print("  ... {} more".format(len(shown) - 40))

    payload = {
        "candidates": [
            {"addr": a, "editor": e, "selection": s} for a, e, s in shown[:200]
        ]
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    print("\nwrote {}".format(os.path.relpath(OUT_PATH, _ROOT)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FocusLost as exc:
        print("\nFOCUS LOST: {}".format(exc))
        sys.exit(3)
