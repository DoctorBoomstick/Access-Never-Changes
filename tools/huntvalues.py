#!/usr/bin/env python3
"""Locate the character editor's numeric state: SPECIAL array and spare points.

A naive "went up by 1 when I pressed Right" filter is not enough here, because
several derived stats track Strength linearly and move in lockstep with it.
The disambiguation is cross-stat: raise Strength (index 0), then raise Luck
(index 6), and require the two winning addresses to sit exactly 6 ints apart.
Only the real SPECIAL array satisfies that, and it hands us the whole array.

Everything is restored before exit -- each increase is matched by a decrease,
and the final state is reported so any drift is visible rather than silent.

    python tools/huntvalues.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fallout2_access.memory import FALLOUT_EXE_NAMES, Process, ProcessNotFound, ValueScan  # noqa: E402
from fallout2_access.input import (  # noqa: E402
    FocusLost,
    find_game_window,
    focus_window,
    guarded_tap,
)

SEL = 0x005709EC
OUT_PATH = os.path.join(_ROOT, "fallout2_access", "offsets", "values.json")


class Editor:
    def __init__(self, proc: Process, hwnd: int, settle: float) -> None:
        self.proc = proc
        self.hwnd = hwnd
        self.settle = settle

    def sel(self) -> Optional[int]:
        return self.proc.read_i32(SEL)

    def tap(self, key: str) -> None:
        # Guarded: refuses to type at whatever window stole the foreground.
        guarded_tap(self.hwnd, key, settle=self.settle)

    def responsive(self) -> bool:
        """Confirm the editor is actually accepting navigation.

        Cheap insurance against running a whole scan against a screen that
        isn't the char editor and recording noise as a result.
        """
        before = self.sel()
        self.tap("down")
        moved = self.sel() != before
        self.tap("up")
        return moved

    def goto_section(self, head: int, max_tabs: int = 8) -> bool:
        if self.sel() == head:
            return True
        for _ in range(max_tabs):
            self.tap("tab")
            if self.sel() == head:
                return True
        return False

    def goto_index(self, head: int, target: int, max_steps: int = 30) -> bool:
        """Tab to a section, then Down until the wanted index is selected."""
        if not self.goto_section(head):
            return False
        for _ in range(max_steps):
            if self.sel() == target:
                return True
            self.tap("down")
        return self.sel() == target


def narrow_on_increase(ed: Editor, presses: int = 2) -> Tuple[Dict[int, int], Dict[int, int]]:
    """Press Right and keep addresses that rose by 1 (and those that fell by 1)."""
    up = ValueScan(ed.proc, None, "i32")
    down = ValueScan(ed.proc, None, "i32")
    up.baseline()
    down.baseline()

    for i in range(presses):
        ed.tap("right")
        n_up = up.delta(1)
        n_dn = down.delta(-1)
        print("    press {}: {} rose by 1, {} fell by 1".format(i + 1, n_up, n_dn))

    # Put it back, and require the risers to fall again.
    for i in range(presses):
        ed.tap("left")
        n_up = up.delta(-1)
        n_dn = down.delta(1)
        print("    restore {}: {} tracked down, {} tracked up".format(i + 1, n_up, n_dn))

    return (
        {a: v for a, v in up.items(0)},
        {a: v for a, v in down.items(0)},
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", type=float, default=0.16)
    args = ap.parse_args()

    try:
        return run(args)
    except FocusLost as exc:
        print("\nFOCUS LOST: {}".format(exc))
        return 3


def run(args) -> int:
    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except ProcessNotFound as exc:
        print("not attached: {}".format(exc))
        return 2
    hwnd = find_game_window(proc.pid)
    if hwnd is None or not focus_window(hwnd):
        print("could not focus the game window")
        return 2

    ed = Editor(proc, hwnd, args.settle)

    if not ed.responsive():
        print(
            "the editor is not responding to navigation (selection {} did not "
            "move). Make sure character creation is open and on screen.".format(ed.sel())
        )
        return 1
    print("editor responsive; selection {}".format(ed.sel()))

    print("=== Strength (index 0) ===")
    if not ed.goto_index(0, 0):
        print("could not select index 0; is the editor open?")
        return 1
    str_up, str_down = narrow_on_increase(ed)
    print("  {} candidates track Strength; {} track inversely".format(
        len(str_up), len(str_down)))

    print("\n=== Luck (index 6) ===")
    if not ed.goto_index(0, 6):
        print("could not select index 6")
        return 1
    luck_up, luck_down = narrow_on_increase(ed)
    print("  {} candidates track Luck".format(len(luck_up)))

    # Decisive test: the SPECIAL array puts Luck exactly 6 ints past Strength.
    print("\n=== cross-stat disambiguation (Luck must be Strength + 24 bytes) ===")
    pairs: List[Tuple[int, int]] = []
    for s_addr in str_up:
        for l_addr in luck_up:
            if l_addr - s_addr == 6 * 4:
                pairs.append((s_addr, l_addr))

    if not pairs:
        print("  no pair 24 bytes apart. Strength candidates:")
        for a, v in sorted(str_up.items())[:12]:
            print("    0x{:08X} = {}".format(a, v))
        print("  Luck candidates:")
        for a, v in sorted(luck_up.items())[:12]:
            print("    0x{:08X} = {}".format(a, v))
        return 1

    results: Dict[str, object] = {}
    for s_addr, l_addr in pairs:
        print("  SPECIAL array base 0x{:08X}  (Luck at 0x{:08X})".format(s_addr, l_addr))
        raw = proc.read(s_addr, 7 * 4)
        stats = [int.from_bytes(raw[i * 4:i * 4 + 4], "little", signed=True) for i in range(7)]
        names = ["Strength", "Perception", "Endurance", "Charisma",
                 "Intelligence", "Agility", "Luck"]
        for name, value in zip(names, stats):
            print("    {:<13} {}".format(name, value))
        results["special_array"] = {"addr": s_addr, "values": stats}

    # Spare points: fell by 1 on both Strength and Luck increases.
    common_down = set(str_down) & set(luck_down)
    print("\n=== unspent character points ===")
    print("  {} address(es) fell on both raises".format(len(common_down)))
    for addr in sorted(common_down):
        value = proc.read_i32(addr)
        print("    0x{:08X} = {}".format(addr, value))
    if len(common_down) == 1:
        addr = sorted(common_down)[0]
        results["char_points"] = {"addr": addr, "value": proc.read_i32(addr)}

    print("\nfinal selection index: {}".format(ed.sel()))
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
        fh.write("\n")
    print("wrote {}".format(os.path.relpath(OUT_PATH, _ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
