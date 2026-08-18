#!/usr/bin/env python3
"""Walk every section reading all known label pointers at once.

Establishes exactly which pointer serves which section, rather than inferring
it from a single differential scan (which can miss a pointer that happens not
to change on the sampled step).

Navigation only -- nothing here alters the character.

    python tools/probelabels.py
"""

from __future__ import annotations

import argparse
import json
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

SEL_ADDR = 0x005709EC
POINTERS = {
    "p_00F4": 0x005700F4,
    "p_05B8": 0x005705B8,
    "p_05CC": 0x005705CC,
}
SECTIONS = [0, 10, 18, 28, 55]
OUT_PATH = os.path.join(_ROOT, "fallout2_access", "offsets", "editor_labels.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", type=float, default=0.16)
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

    def sel() -> Optional[int]:
        return proc.read_i32(SEL_ADDR)

    def text(ptr_addr: int, limit: int = 70) -> Optional[str]:
        ptr = proc.read_u32(ptr_addr)
        if not ptr or not (0x00010000 < ptr < 0x7FFF0000):
            return None
        s = proc.read_cstring(ptr, limit)
        if s and all(32 <= ord(c) < 127 for c in s) and any(c.isalpha() for c in s):
            return s
        return None

    def goto(head: int, max_tabs: int = 8) -> bool:
        for _ in range(max_tabs):
            tap("tab", settle=args.settle)
            if sel() == head:
                return True
        return False

    out: Dict[str, List[Dict[str, object]]] = {}
    for head in SECTIONS:
        print("\n=== section {} ===".format(head))
        if not goto(head):
            print("  unreachable")
            continue
        rows: List[Dict[str, object]] = []
        seen = set()
        while True:
            time.sleep(0.05)
            idx = sel()
            if idx is None or idx in seen:
                break
            seen.add(idx)
            row: Dict[str, object] = {"index": idx}
            for name, addr in POINTERS.items():
                row[name] = text(addr)
            rows.append(row)
            print(
                "  {:>3}  {:<22} {:<22} {}".format(
                    idx,
                    (row["p_00F4"] or "-")[:22],
                    (row["p_05B8"] or "-")[:22],
                    (row["p_05CC"] or "-")[:30],
                )
            )
            tap("down", settle=args.settle)
        out[str(head)] = rows

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print("\n\nWHICH POINTER SERVES WHICH SECTION")
    for head, rows in out.items():
        for name in POINTERS:
            values = [r[name] for r in rows if r[name]]
            distinct = len(set(values))
            verdict = "TRACKS ({} distinct)".format(distinct) if distinct > 1 else "static/stale"
            print("  section {:>3}  {}  {}".format(head, name, verdict))
    print("\nwrote {}".format(os.path.relpath(OUT_PATH, _ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
