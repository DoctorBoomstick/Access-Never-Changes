"""The "Pick a Perk" window.

It opens over the character sheet the first time the sheet is opened after a
level that grants a perk -- not at the level-up itself, which is why reaching
level 3 seemed to offer nothing. Every perk a character takes goes through it,
and until this it said nothing at all: a list of names and a card, all drawn.

Measured live with fourteen perks on offer, by logging what moved in the
editor's statics while the list was walked end to end:

    0x0056FCB0   the options, sorted by name: { int perk; char* name } each,
                 ended by an empty name -- Awareness 0, Bonus HtH Damage 2,
                 Cautious Nature 80, ... Thief 105
    0x005707A8   how far the list has scrolled
    0x005707DC   which visible line is lit

The line runs 0 to 3 and then the list scrolls under it, so the perk is the
scroll plus the line. The window is 573 by 230, which nothing else on the
sheet is.

The names are the engine's own pointers into perk.msg and the descriptions are
that file's entry 1101 onwards, so both are whatever language the game is in,
and RPU's perks read like any others. The arrows, Enter and Escape are the
window's own keys and are left to it.
"""

from __future__ import annotations

import struct
from typing import List, NamedTuple, Optional, Tuple

from . import uiwindow
from .. import words

PANEL = (573, 230)
OPTIONS = 0x0056FCB0
OPTION_STRIDE = 8
MAX_OPTIONS = 64
TOP_ADDR = 0x005707A8
LINE_ADDR = 0x005707DC
MSG_PERK = 0x006642D4
# perk.msg: names from 101, descriptions from 1101, by perk number.
DESC_BASE = 1101


class PerkChoice(NamedTuple):
    index: int        # in the whole list, from 0
    total: int
    perk: int         # the engine's perk number
    name: str

    def announce(self) -> str:
        return "{}. {}.".format(self.name, words.of(self.index + 1, self.total))


def showing(proc) -> bool:
    return any((w.width, w.height) == PANEL for w in uiwindow.live_windows(proc))


def options(proc) -> List[Tuple[int, str]]:
    """Every perk on offer, as (perk number, name), in the order listed."""
    blob = proc.read_chunked(OPTIONS, OPTION_STRIDE * MAX_OPTIONS)
    out: List[Tuple[int, str]] = []
    if not blob:
        return out
    for i in range(len(blob) // OPTION_STRIDE):
        perk, ptr = struct.unpack_from("<iI", blob, i * OPTION_STRIDE)
        if not (0x10000 < ptr < 0x7FFF0000):
            break
        name = proc.read_cstring(ptr, 64)
        if not name:
            break
        out.append((perk, name))
    return out


def current(proc) -> Optional[PerkChoice]:
    """The highlighted perk, or None when the window is not up."""
    if not showing(proc):
        return None
    offered = options(proc)
    top = proc.read_i32(TOP_ADDR)
    line = proc.read_i32(LINE_ADDR)
    if not offered or top is None or line is None:
        return None
    index = top + line
    if not 0 <= index < len(offered):
        return None
    perk, name = offered[index]
    return PerkChoice(index, len(offered), perk, name)


def description(proc, perk: int) -> Optional[str]:
    from ..msg.memlist import read_message_list

    lst = read_message_list(proc, MSG_PERK)
    return lst.get(DESC_BASE + perk) if lst else None
