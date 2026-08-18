#!/usr/bin/env python3
"""Explore the premade-character selection screen.

Three things at once:

1. Confirm the screen discriminator candidates actually track the screen.
2. Verify the suspected tagged-skill and trait arrays. They sit immediately
   before the skill.msg and trait.msg globals and read -1 in a fresh editor.
   If they really are what they look like, then cycling premades must produce
   *valid, differing* skill indices (0-17) and trait indices (0-15) per
   character -- a check that no coincidence passes.
3. Find the premade index and the name/bio text the screen displays.

Navigation only on this screen: Left/Right cycle premades and change nothing.

    python tools/huntpremade.py
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

from fallout2_access.memory import FALLOUT_EXE_NAMES, Process, ProcessNotFound, ValueScan  # noqa: E402
from fallout2_access.msg import read_message_list  # noqa: E402
from fallout2_access.input import (  # noqa: E402
    FocusLost,
    find_game_window,
    focus_window,
    guarded_tap,
)

SEL = 0x005709EC
SPECIAL = 0x0051C394
TAGS = 0x00668070
TRAITS = 0x0066BE40
SCREEN_FLAGS = [0x00518490, 0x00597138]
MSG_SKILL = 0x00668080
MSG_TRAIT = 0x0066BE38
OUT_PATH = os.path.join(_ROOT, "fallout2_access", "offsets", "premade.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", type=float, default=0.5)
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

    skill_names = (read_message_list(proc, MSG_SKILL) or None)
    skill_by = skill_names.by_num() if skill_names else {}
    trait_names = (read_message_list(proc, MSG_TRAIT) or None)
    trait_by = trait_names.by_num() if trait_names else {}

    def ints(addr: int, n: int) -> List[int]:
        raw = proc.read(addr, n * 4)
        if not raw or len(raw) < n * 4:
            return []
        return [int.from_bytes(raw[i * 4:i * 4 + 4], "little", signed=True) for i in range(n)]

    def flags() -> Dict[str, int]:
        return {hex(a): proc.read_i32(a) for a in SCREEN_FLAGS}

    print("in editor  flags: {}".format(flags()))
    print("  tags   {}".format(ints(TAGS, 4)))
    print("  traits {}".format(ints(TRAITS, 3)))

    # Escape out to the selection screen.
    guarded_tap(hwnd, "escape", settle=args.settle + 0.3)
    print("\non selection screen  flags: {}".format(flags()))

    # Find the premade index: Left/Right must move it by exactly one.
    print("\n--- locating the premade index ---")
    scan = ValueScan(proc, None, "i32")
    scan.baseline()
    for i in range(3):
        guarded_tap(hwnd, "right", settle=args.settle)
        n = scan.delta(1)
        print("  right {}: {} candidate(s)".format(i + 1, n))
        if n and n <= 3:
            break
    premade_idx = None
    cands = scan.addresses()
    for addr in cands:
        guarded_tap(hwnd, "left", settle=args.settle)
        after = proc.read_i32(addr)
        guarded_tap(hwnd, "right", settle=args.settle)
        back = proc.read_i32(addr)
        if back == after + 1:
            premade_idx = addr
            break
    print("  premade index: {}".format(hex(premade_idx) if premade_idx else "not found"))

    # Walk every premade and read its data.
    print("\n--- premade characters ---")
    results = []
    seen_idx = set()
    for step in range(6):
        idx = proc.read_i32(premade_idx) if premade_idx else step
        if idx in seen_idx:
            break
        seen_idx.add(idx)
        s = ints(SPECIAL, 7)
        tags = [t for t in ints(TAGS, 4) if t >= 0]
        traits = [t for t in ints(TRAITS, 3) if t >= 0]
        entry = {
            "index": idx,
            "special": s,
            "tags": tags,
            "tag_names": [skill_by.get(100 + t, "?") for t in tags],
            "traits": traits,
            "trait_names": [trait_by.get(100 + t, "?") for t in traits],
        }
        results.append(entry)
        print("  premade {}".format(idx))
        print("    SPECIAL {}".format(s))
        print("    tags    {} -> {}".format(tags, entry["tag_names"]))
        print("    traits  {} -> {}".format(traits, entry["trait_names"]))
        guarded_tap(hwnd, "right", settle=args.settle)

    # Sanity: are these really skill/trait indices?
    ok = all(
        all(0 <= t <= 17 for t in e["tags"]) and all(0 <= t <= 15 for t in e["traits"])
        for e in results
    )
    distinct = len({tuple(e["tags"]) for e in results}) > 1
    print("\n  all indices in valid range: {}".format("YES" if ok else "NO"))
    print("  tags differ between premades: {}".format("YES" if distinct else "NO"))

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump({"premade_index_addr": premade_idx, "premades": results}, fh, indent=2)
        fh.write("\n")
    print("\nwrote {}".format(os.path.relpath(OUT_PATH, _ROOT)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FocusLost as exc:
        print("\nFOCUS LOST: {}".format(exc))
        sys.exit(3)
