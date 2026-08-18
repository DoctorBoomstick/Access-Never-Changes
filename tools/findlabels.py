#!/usr/bin/env python3
"""Find the text-pointer globals that feed each character-editor section.

The trait section's name/description pointers were found first; they turned out
to be trait-specific and stale elsewhere. So run the same differential trick
inside every section: snapshot, move the selection one step, keep the u32s that
changed, and report those that dereference to text which *differs* between the
two positions.

Anything found here is a source of real game strings, which is what keeps the
announce layer free of hardcoded English.

Navigation only -- nothing here alters the character.

    python tools/findlabels.py
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
from fallout2_access.input import find_game_window, focus_window, tap  # noqa: E402

SEL_ADDR = 0x005709EC
OUT_PATH = os.path.join(_ROOT, "fallout2_access", "offsets", "label_pointers.json")


def looks_like_text(s: Optional[str]) -> bool:
    if not s or len(s) < 3:
        return False
    if not all(32 <= ord(c) < 127 for c in s):
        return False
    return any(c.isalpha() for c in s)


class Finder:
    def __init__(self, proc: Process, settle: float) -> None:
        self.proc = proc
        self.settle = settle

    def sel(self) -> Optional[int]:
        return self.proc.read_i32(SEL_ADDR)

    def deref(self, value: int, limit: int = 120) -> Optional[str]:
        if not (0x00010000 < value < 0x7FFF0000):
            return None
        s = self.proc.read_cstring(value, limit)
        return s if looks_like_text(s) else None

    def goto_section(self, start: int, max_tabs: int = 8) -> bool:
        for _ in range(max_tabs):
            tap("tab", settle=self.settle)
            if self.sel() == start:
                return True
        return False

    def find_in_section(self, start: int) -> List[Dict[str, object]]:
        if not self.goto_section(start):
            print("  could not reach section {}".format(start))
            return []

        scan = ValueScan(self.proc, None, "u32")
        scan.baseline()
        before_sel = self.sel()
        tap("down", settle=max(self.settle, 0.22))
        after_sel = self.sel()
        scan.changed()

        candidates: List[Tuple[int, str]] = []
        for addr, value in scan.items(0):
            text = self.deref(value)
            if text:
                candidates.append((addr, text))

        # Move once more; a real label pointer changes text again.
        tap("down", settle=max(self.settle, 0.22))
        third_sel = self.sel()

        found: List[Dict[str, object]] = []
        for addr, text_b in candidates:
            ptr = self.proc.read_u32(addr)
            text_c = self.deref(ptr) if ptr else None
            if text_c and text_c != text_b:
                found.append(
                    {
                        "addr": addr,
                        "at_{}".format(after_sel): text_b,
                        "at_{}".format(third_sel): text_c,
                    }
                )
        print(
            "  selection {} -> {} -> {}; {} changed u32s, {} deref to text, "
            "{} track".format(
                before_sel, after_sel, third_sel, scan.count, len(candidates), len(found)
            )
        )
        return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", type=float, default=0.18)
    ap.add_argument(
        "--sections",
        default="0,10,18,28,55",
        help="comma-separated section head indices",
    )
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

    finder = Finder(proc, args.settle)
    results: Dict[str, List[Dict[str, object]]] = {}

    for head in [int(x) for x in args.sections.split(",")]:
        print("\n--- section {} ---".format(head))
        found = finder.find_in_section(head)
        results[str(head)] = found
        for entry in found:
            addr = entry["addr"]
            texts = [v for k, v in entry.items() if k != "addr"]
            shown = " | ".join(
                (t[:52] + "...") if len(t) > 55 else t for t in texts
            )
            print("    0x{:08X}  {}".format(addr, shown))

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("\nwrote {}".format(os.path.relpath(OUT_PATH, _ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
