"""Engine symbol table.

`found.json` holds addresses confirmed by hand through tools/f2mem.py, each
with the RVA from the module base so it survives a different image base.

Confirmed entries graduate into a signature-resolved table: an AoB pattern
that locates the instruction referencing the global, plus the offset of the
address operand within the match. That is what ships -- absolute addresses are
a development convenience, not a distribution format.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
FOUND_PATH = os.path.join(_HERE, "found.json")


def load_found():
    """Hand-confirmed addresses from the harness. Empty dict if none yet."""
    try:
        with open(FOUND_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}
