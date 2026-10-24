#!/usr/bin/env python3
"""One release's notes, out of CHANGELOG.md.

    python tools/changelog.py               this version's section, to stdout
    python tools/changelog.py 1.0.0         another version's
    python tools/changelog.py --out FILE    written to FILE instead

The release workflow hands the result to the draft release, so what a player
reads on GitHub is what CHANGELOG.md says rather than a list of commit titles.
It fails when the version has no heading, or a heading with nothing under it:
a release whose notes were never written should stop the build, not go out
blank.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
sys.path.insert(0, ROOT)


def section(text: str, version: str) -> Optional[str]:
    """The body under `## <version> ...`, up to the next release's heading."""
    head = re.compile(r"^## +{}(?=[\s(\"]|$).*$".format(re.escape(version)),
                      re.MULTILINE)
    found = head.search(text)
    if not found:
        return None
    rest = text[found.end():]
    following = re.search(r"^## ", rest, re.MULTILINE)
    return (rest[:following.start()] if following else rest).strip()


def main() -> int:
    from fallout2_access.version import VERSION

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?", default=VERSION)
    ap.add_argument("--out", default="", help="write the notes here")
    args = ap.parse_args()

    with open(CHANGELOG, encoding="utf-8") as fh:
        notes = section(fh.read(), args.version)
    if notes is None:
        print("CHANGELOG.md has no heading for {}".format(args.version),
              file=sys.stderr)
        return 1
    if not notes:
        print("CHANGELOG.md says nothing under {}".format(args.version),
              file=sys.stderr)
        return 1
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(notes + "\n")
    else:
        sys.stdout.buffer.write((notes + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
