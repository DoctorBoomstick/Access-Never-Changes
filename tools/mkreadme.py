#!/usr/bin/env python3
"""Make README.md from docs/manual.html.

    python tools/mkreadme.py           write README.md
    python tools/mkreadme.py --check   say whether it is up to date

docs/manual.html is the manual, and the one to edit. GitHub will not show an HTML
file as a page, but it does show HTML written inside README.md -- so the
manual's body is copied in, and the repository's front page is the whole
manual, readable before anyone downloads anything. tests/test_manual.py fails
when the two disagree.

GitHub keeps the headings, paragraphs, lists, tables and links and drops what
it does not allow, the styling and the <nav> wrapper among them; the contents
list inside the wrapper survives as an ordinary list.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL = os.path.join(ROOT, "docs", "manual.html")
README = os.path.join(ROOT, "README.md")

HEADER = ("<!-- Made from docs/manual.html by tools/mkreadme.py. "
          "Edit docs/manual.html, then run the tool. -->\n\n")


def render() -> str:
    with open(MANUAL, encoding="utf-8") as fh:
        page = fh.read()
    m = re.search(r"<main>\s*(.*?)\s*</main>", page, re.S)
    if not m:
        raise SystemExit("docs/manual.html has no <main> element")
    body = m.group(1)
    # A blank line inside an element would hand the rest of it back to the
    # Markdown parser, and an indented line would become a code block.
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
    return HEADER + "\n\n".join(blocks) + "\n"


def main(argv) -> int:
    text = render()
    try:
        with open(README, encoding="utf-8") as fh:
            current = fh.read()
    except OSError:
        current = ""
    if "--check" in argv:
        if current != text:
            print("README.md is out of date: run tools/mkreadme.py")
            return 1
        print("README.md is up to date")
        return 0
    with open(README, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote README.md from docs/manual.html")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
