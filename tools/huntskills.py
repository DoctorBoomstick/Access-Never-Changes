#!/usr/bin/env python3
"""Locate the skill value array and the tag/trait counters.

Skills can't be raised with the arrow keys during character creation -- you
only get to tag three -- so the differential trick used for SPECIAL doesn't
apply. Instead we scan for the known starting skill percentages as a byte
sequence. Eighteen specific values in a specific order is an extremely strong
fingerprint; nothing else in the address space looks like it.

If the full sequence misses (a mod may alter starting skills), progressively
shorter prefixes are tried and reported, so a partial match is visible rather
than silently returning nothing.

Read-only: sends no input at all.

    python tools/huntskills.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
from typing import Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fallout2_access.memory import FALLOUT_EXE_NAMES, Process, ProcessNotFound  # noqa: E402
from fallout2_access.msg import read_message_list  # noqa: E402

MSG_SKILL = 0x00668080
OUT_PATH = os.path.join(_ROOT, "fallout2_access", "offsets", "skills.json")

# Fallout 2 starting skill percentages for an all-5 SPECIAL character, in the
# order the editor lists them. Read off the live screen.
START_SKILLS = [25, 10, 10, 50, 40, 20, 20, 15, 20, 20, 15, 20, 20, 15, 25, 20, 25, 20]


def find_sequence(proc: Process, values: List[int], regions) -> List[int]:
    needle = b"".join(struct.pack("<i", v) for v in values)
    hits: List[int] = []
    for region in regions:
        data = proc.read_chunked(region.base, region.size)
        start = 0
        while True:
            i = data.find(needle, start)
            if i < 0:
                break
            hits.append(region.base + i)
            start = i + 1
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="search all writable memory")
    args = ap.parse_args()

    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except ProcessNotFound as exc:
        print("not attached: {}".format(exc))
        return 2

    regions = (
        [r for r in proc.regions(writable_only=True)]
        if args.all
        else proc.module_regions()
    )
    print("searching {:,} bytes".format(sum(r.size for r in regions)))

    skills = read_message_list(proc, MSG_SKILL)
    names = []
    if skills:
        by_num = skills.by_num()
        names = [by_num.get(100 + i, "?") for i in range(18)]
        print("skill names: {}".format(", ".join(names)))

    hits: List[int] = []
    used = len(START_SKILLS)
    for length in range(len(START_SKILLS), 4, -1):
        hits = find_sequence(proc, START_SKILLS[:length], regions)
        if hits:
            used = length
            break

    if not hits:
        print("\nno match, even for a 5-value prefix. starting skills may differ.")
        return 1

    print("\nmatched the first {} values at {} location(s)".format(used, len(hits)))
    results: Dict[str, object] = {}
    for addr in hits:
        print("\n  skill array 0x{:08X}".format(addr))
        raw = proc.read(addr, 18 * 4)
        values = [
            int.from_bytes(raw[i * 4:i * 4 + 4], "little", signed=True) for i in range(18)
        ]
        for i, value in enumerate(values):
            label = names[i] if i < len(names) else "skill {}".format(i)
            print("    {:<16} {}%".format(label, value))
        results.setdefault("skill_arrays", []).append(
            {"addr": addr, "values": values}
        )

        # What sits around it: tag slots read -1, counters read small.
        print("    -- neighbourhood --")
        span = 12
        start = addr - span * 4
        nraw = proc.read(start, (span * 2 + 18) * 4)
        if nraw:
            line = []
            for i in range(0, len(nraw) - 3, 4):
                v = int.from_bytes(nraw[i:i + 4], "little", signed=True)
                cur = start + i
                mark = "*" if addr <= cur < addr + 18 * 4 else " "
                line.append("{}{:>6}".format(mark, v))
                if len(line) == 8:
                    print("      0x{:08X} {}".format(start + i - 28, "".join(line)))
                    line = []
            if line:
                print("      0x{:08X} {}".format(start + len(nraw) - len(line) * 4, "".join(line)))

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
        fh.write("\n")
    print("\nwrote {}".format(os.path.relpath(OUT_PATH, _ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
