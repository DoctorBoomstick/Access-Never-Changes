#!/usr/bin/env python3
"""Enumerate every message list loaded in the running game and dump it.

    python tools/dumpmsg.py                 # summary of every list found
    python tools/dumpmsg.py --grep Strength # which list holds a given string
    python tools/dumpmsg.py --list 0x0C0C1400 --full
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fallout2_access.memory import FALLOUT_EXE_NAMES, Process, ProcessNotFound  # noqa: E402
from fallout2_access.msg import find_message_lists  # noqa: E402

OUT_PATH = os.path.join(_ROOT, "fallout2_access", "offsets", "message_lists.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grep", help="only show lists containing this substring")
    ap.add_argument("--list", help="dump one list by base address (hex)")
    ap.add_argument("--full", action="store_true", help="print every entry")
    ap.add_argument("--min", type=int, default=8, help="minimum entries per list")
    ap.add_argument("--save", action="store_true", help="write message_lists.json")
    args = ap.parse_args()

    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except ProcessNotFound as exc:
        print("not attached: {}".format(exc))
        return 2

    t0 = time.time()
    lists = find_message_lists(proc, min_entries=args.min)
    print("found {} message list(s) in {:.1f}s\n".format(len(lists), time.time() - t0))

    wanted = args.grep.lower() if args.grep else None
    only = int(args.list, 16) if args.list else None

    shown = 0
    for lst in lists:
        if only is not None and lst.base != only:
            continue
        texts = [e.text for e in lst.entries]
        if wanted and not any(wanted in t.lower() for t in texts):
            continue
        shown += 1
        sample = ", ".join(repr(t[:22]) for t in texts[:5])
        print(
            "0x{:08X}  {:>5} entries  nums {:<12} {}".format(
                lst.base, lst.count, lst.numbers(), sample
            )
        )
        if args.full or only is not None:
            for entry in lst.entries:
                text = entry.text if len(entry.text) <= 90 else entry.text[:87] + "..."
                print("    {:>6}  {}".format(entry.num, text))
        elif wanted:
            for entry in lst.entries:
                if wanted in entry.text.lower():
                    print("    {:>6}  {}".format(entry.num, entry.text[:90]))

    if not shown:
        print("nothing matched")

    if args.save:
        payload = [
            {
                "base": lst.base,
                "count": lst.count,
                "entries": [{"num": e.num, "text": e.text} for e in lst.entries],
            }
            for lst in lists
        ]
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print("\nwrote {}".format(os.path.relpath(OUT_PATH, _ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
