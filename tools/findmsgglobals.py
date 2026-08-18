#!/usr/bin/env python3
"""Resolve the static globals that point at each loaded message list.

The message-list arrays live on the heap, so their addresses change every run
and cannot ship. Fallout 2 reaches them through statically allocated globals:

    struct MessageList { int count; MessageListItem* entries; };

So for each array we find the u32 inside fallout2.exe's data that equals the
array's base. That address is the `entries` field; the MessageList global
begins 4 bytes earlier, where `count` should match the entry count -- which is
exactly the check that tells us we have the right global rather than a stray
cached pointer.

    python tools/findmsgglobals.py
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fallout2_access.memory import FALLOUT_EXE_NAMES, Process, ProcessNotFound  # noqa: E402
from fallout2_access.msg import find_message_lists  # noqa: E402

OUT_PATH = os.path.join(_ROOT, "fallout2_access", "offsets", "msg_globals.json")

# Strings we expect in each list, used to name it without hardcoding addresses.
FINGERPRINTS = {
    "skill_msg": ("Outdoorsman", "Gambling", "Lockpick"),
    "stat_msg": ("Perception", "Endurance", "Luck"),
    "editor_msg": ("Crippled Left Leg", "Radiation Res.", "Eye Damage"),
}


def identify(texts):
    for name, needles in FINGERPRINTS.items():
        hits = sum(1 for n in needles if any(n.lower() == t.lower() for t in texts))
        if hits >= 2:
            return name
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=8)
    args = ap.parse_args()

    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except ProcessNotFound as exc:
        print("not attached: {}".format(exc))
        return 2

    mod = proc.main_module()
    t0 = time.time()
    lists = find_message_lists(proc, min_entries=args.min)
    print("{} message lists in {:.1f}s".format(len(lists), time.time() - t0))

    # Only the executable's own writable data can hold a shippable global.
    data_regions = proc.module_regions(mod)
    blobs = [(r.base, proc.read_chunked(r.base, r.size)) for r in data_regions]

    named = {}
    for lst in lists:
        texts = [e.text for e in lst.entries]
        name = identify(texts)
        if not name or name in named:
            continue

        needle = struct.pack("<I", lst.base)
        matches = []
        for base, data in blobs:
            start = 0
            while True:
                i = data.find(needle, start)
                if i < 0:
                    break
                if i % 4 == 0:
                    addr = base + i
                    count = proc.read_i32(addr - 4)
                    matches.append((addr, count))
                start = i + 1

        print("\n{}  array 0x{:08X}  {} entries".format(name, lst.base, lst.count))
        if not matches:
            print("  no static reference found (list may be reached indirectly)")
            continue
        for addr, count in matches:
            good = count == lst.count
            print(
                "  entries field 0x{:08X}  MessageList 0x{:08X}  count={} {}".format(
                    addr, addr - 4, count, "MATCH" if good else "(count mismatch)"
                )
            )
            if good:
                named[name] = {
                    "message_list": addr - 4,
                    "entries_field": addr,
                    "rva": (addr - 4) - mod.base,
                    "count": count,
                }

    print("\n\nSHIPPABLE GLOBALS")
    if not named:
        print("  none resolved")
    for name in sorted(named):
        info = named[name]
        print(
            "  {:<12} MessageList 0x{:08X}  rva 0x{:X}  {} entries".format(
                name, info["message_list"], info["rva"], info["count"]
            )
        )

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump({"module_base": mod.base, "globals": named}, fh, indent=2)
        fh.write("\n")
    print("\nwrote {}".format(os.path.relpath(OUT_PATH, _ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
