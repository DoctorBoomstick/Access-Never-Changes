#!/usr/bin/env python3
"""Summarise the art identifiers collected while playing.

Fallout's floors and much of its walls are tile art rather than objects, so
nothing the mod can ask will ever name them -- and the invisible blocker that
does sit on such a hex is filtered out on purpose. The art id is the only handle
on what a hex actually looks like.

This gathers those ids out of debug.log so a table mapping art id to a human
name can be written. That table has to be a data file rather than words buried
in the script: the names are ours rather than the game's, and anything of ours
that describes the world has to be translatable, which is the rule this project
has followed everywhere else.

    python tools/artnames.py [path to debug.log]
"""

from __future__ import annotations

import collections
import os
import re
import sys

_ART = re.compile(
    r"WORLD:art tile=(\d+) ground=(-?\d+) roof=(-?\d+) blocked=(-?\d+)\|"
)
_OBJ = re.compile(
    r"WORLD:artobj fid=(-?\d+) ty=(\d+) vis=(-?\d+) nm=([^|]*)\|"
)

DEFAULT_LOG = (
    r"C:\Program Files (x86)\Steam\steamapps\common\Fallout 2\debug.log"
)

TYPES = {0: "item", 1: "critter", 2: "scenery", 3: "wall", 4: "tile",
         5: "misc", 6: "spatial"}


def art_index(fid: int) -> int:
    """The frame index within its art list -- the part worth keying on."""
    return fid & 0xFFF


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG
    if not os.path.exists(path):
        print("no log at {}".format(path))
        return 1

    ground = collections.Counter()
    roof = collections.Counter()
    blocked_ground = collections.Counter()
    objects = collections.defaultdict(collections.Counter)

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _ART.search(line)
            if m:
                g, r, b = int(m.group(2)), int(m.group(3)), int(m.group(4))
                ground[g] += 1
                roof[r] += 1
                if b:
                    blocked_ground[g] += 1
                continue
            m = _OBJ.search(line)
            if m:
                fid, ty, _vis, nm = m.groups()
                objects[(int(fid) & 0xFFFFFFFF, int(ty))][nm.strip()] += 1

    print("=== ground tiles ===")
    print("{:>12} {:>7} {:>8} {:>9}".format("fid", "index", "seen", "blocked"))
    for fid, n in ground.most_common(30):
        print("{:>12} {:>7} {:>8} {:>9}".format(
            fid, art_index(fid), n, blocked_ground.get(fid, 0)))

    print("\n=== roof tiles ===")
    for fid, n in roof.most_common(10):
        print("{:>12} {:>7} {:>8}".format(fid, art_index(fid), n))

    print("\n=== objects, by art id ===")
    print("{:>12} {:>7} {:<9} {:>7}  names the game gives".format(
        "fid", "index", "type", "seen"))
    for (fid, ty), names in sorted(objects.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(names.values())
        print("{:>12} {:>7} {:<9} {:>7}  {}".format(
            fid, art_index(fid), TYPES.get(ty, ty), total,
            ", ".join(sorted(names)) or "(unnamed)"))

    print("\n{} ground tile ids, {} roof, {} object arts".format(
        len(ground), len(roof), len(objects)))
    print("\nGround and roof ids are the ones worth naming by hand: the objects\n"
          "mostly carry a name from the game already.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
