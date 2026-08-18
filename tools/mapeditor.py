#!/usr/bin/env python3
"""Map the character editor's selection index empirically.

fallout2-ce documents index ranges for `characterEditorSelectedItem`, but those
come from a reimplementation. This walks the real executable's selection with
Up/Down/Tab and records where it actually goes, so the announce layer is built
on measured boundaries rather than borrowed ones.

Navigation only -- nothing here alters the character.

    python tools/mapeditor.py --addr 0x005709EC
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fallout2_access.memory import FALLOUT_EXE_NAMES, Process, ProcessNotFound  # noqa: E402
from fallout2_access.input import find_game_window, focus_window, tap  # noqa: E402


def runs(values: List[int]) -> str:
    """Collapse a sequence into readable runs: 0,1,2,3 -> 0-3."""
    if not values:
        return "(none)"
    out: List[str] = []
    start = prev = values[0]
    for v in values[1:]:
        if v == prev + 1:
            prev = v
            continue
        out.append(str(start) if start == prev else "{}-{}".format(start, prev))
        start = prev = v
    out.append(str(start) if start == prev else "{}-{}".format(start, prev))
    return ", ".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", required=True, help="selection index address (hex)")
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--settle", type=float, default=0.10)
    args = ap.parse_args()

    addr = int(args.addr, 16)

    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except ProcessNotFound as exc:
        print("not attached: {}".format(exc))
        return 2
    hwnd = find_game_window(proc.pid)
    if hwnd is None or not focus_window(hwnd):
        print("could not focus the game window")
        return 2

    def sel() -> Optional[int]:
        return proc.read_i32(addr)

    print("selection address 0x{:08X}, currently {}".format(addr, sel()))

    # Walk to the top of whatever list we are in.
    print("\nwalking UP {} times".format(args.steps))
    seen_up: List[int] = []
    for _ in range(args.steps):
        tap("up", settle=args.settle)
        v = sel()
        if v is not None:
            seen_up.append(v)
        if len(seen_up) >= 4 and len(set(seen_up[-4:])) == 1:
            break  # clamped at the top
    top = sel()
    print("  settled at {} after {} presses".format(top, len(seen_up)))
    print("  visited: {}".format(runs(sorted(set(seen_up)))))

    # Walk down through the whole list.
    print("\nwalking DOWN {} times".format(args.steps))
    seen_down: List[int] = []
    order: List[int] = []
    for _ in range(args.steps):
        tap("down", settle=args.settle)
        v = sel()
        if v is None:
            continue
        order.append(v)
        seen_down.append(v)
        if len(seen_down) >= 4 and len(set(seen_down[-4:])) == 1:
            break  # clamped at the bottom
    bottom = sel()
    print("  settled at {} after {} presses".format(bottom, len(seen_down)))
    print("  visited: {}".format(runs(sorted(set(seen_down)))))
    print("  order:   {}".format(", ".join(str(v) for v in order[:40])))
    if len(order) > 40:
        print("           ... {} more".format(len(order) - 40))

    # Tab between sections.
    print("\npressing TAB 8 times")
    for i in range(8):
        tap("tab", settle=args.settle)
        print("  tab {} -> selection {}".format(i + 1, sel()))

    print("\nSUMMARY")
    print("  top of list    {}".format(top))
    print("  bottom of list {}".format(bottom))
    allseen = sorted(set(seen_up) | set(seen_down))
    print("  full range     {}".format(runs(allseen)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
