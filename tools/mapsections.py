#!/usr/bin/env python3
"""Fingerprint each Tab section of the character editor by its item count.

Section sizes identify them unambiguously without needing to see the screen:
SPECIAL is 7, skills 18, optional traits 16. Walking each section's full cycle
and counting therefore tells us what each index range means.

Reads are double-sampled and required to agree, because a single read taken
immediately after a keypress can catch the engine mid-update -- an earlier pass
saw a stray 94 in the middle of an otherwise contiguous run.

Navigation only -- nothing here alters the character.

    python tools/mapsections.py --addr 0x005709EC
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fallout2_access.memory import FALLOUT_EXE_NAMES, Process, ProcessNotFound  # noqa: E402
from fallout2_access.input import find_game_window, focus_window, tap  # noqa: E402


class Reader:
    def __init__(self, proc: Process, addr: int, settle: float) -> None:
        self.proc = proc
        self.addr = addr
        self.settle = settle

    def stable(self, tries: int = 6) -> Optional[int]:
        """Read until two consecutive samples agree."""
        last = self.proc.read_i32(self.addr)
        for _ in range(tries):
            time.sleep(0.04)
            now = self.proc.read_i32(self.addr)
            if now is not None and now == last:
                return now
            last = now
        return last

    def press(self, key: str) -> Optional[int]:
        tap(key, settle=self.settle)
        return self.stable()


def walk_cycle(reader: Reader, max_steps: int = 60) -> List[int]:
    """Press Down until the selection returns to where it started."""
    start = reader.stable()
    if start is None:
        return []
    seq = [start]
    for _ in range(max_steps):
        v = reader.press("down")
        if v is None:
            continue
        if v == start:
            break
        seq.append(v)
    return seq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", required=True)
    ap.add_argument("--settle", type=float, default=0.14)
    ap.add_argument("--sections", type=int, default=5)
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

    reader = Reader(proc, addr, args.settle)
    print("selection at 0x{:08X}, currently {}".format(addr, reader.stable()))

    results: Dict[int, List[int]] = {}
    for i in range(args.sections):
        start = reader.press("tab")
        if start is None:
            continue
        if start in results:
            print("\nsection starting {} already mapped; cycled all sections".format(start))
            break
        print("\n--- Tab {} -> section starting at {} ---".format(i + 1, start))
        seq = walk_cycle(reader)
        results[start] = seq
        contiguous = seq == list(range(min(seq), min(seq) + len(seq))) if seq else False
        print("  {} items: {}".format(len(seq), seq))
        print("  contiguous: {}".format("yes" if contiguous else "NO"))
        # Return to the section head so the next Tab starts clean.

    print("\n\nSECTION MAP")
    guesses = {7: "SPECIAL stats", 18: "skills", 16: "optional traits"}
    for start in sorted(results):
        seq = results[start]
        guess = guesses.get(len(seq), "")
        span = "{}-{}".format(min(seq), max(seq)) if seq else "?"
        print(
            "  start {:>3}  {:>2} items  range {:<8} {}".format(
                start, len(seq), span, guess
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
