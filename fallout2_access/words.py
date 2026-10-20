"""Words more than one part of the mod says, said one way everywhere.

Directions above all: the scanner, the hex readout and a critter's facing all
name the same six, and a translation should only have to name them once.
"""

from __future__ import annotations

from .i18n import tr


def direction(rotation: int) -> str:
    """The engine's 0-5, north east round to north west; "" for anything else."""
    names = (
        tr("dir.ne", "north east"),
        tr("dir.e", "east"),
        tr("dir.se", "south east"),
        tr("dir.sw", "south west"),
        tr("dir.w", "west"),
        tr("dir.nw", "north west"),
    )
    return names[rotation] if 0 <= rotation < len(names) else ""


def compass(dx: int, dy: int) -> str:
    """One of eight directions for a screen offset (y grows south), or ""."""
    if dx == 0 and dy == 0:
        return ""
    ns = "s" if dy > 0 else "n" if dy < 0 else ""
    ew = "e" if dx > 0 else "w" if dx < 0 else ""
    return {
        "n": tr("dir.n", "north"),
        "ne": tr("dir.ne", "north east"),
        "e": tr("dir.e", "east"),
        "se": tr("dir.se", "south east"),
        "s": tr("dir.s", "south"),
        "sw": tr("dir.sw", "south west"),
        "w": tr("dir.w", "west"),
        "nw": tr("dir.nw", "north west"),
    }[ns + ew]


def hexes(count: int) -> str:
    """"1 hex", "4 hexes"."""
    if count == 1:
        return tr("words.one_hex", "1 hex")
    return tr("words.hexes", "{count} hexes", count=count)


def of(index: int, total: int) -> str:
    """"3 of 8" -- `index` counted from 1."""
    return tr("words.of", "{index} of {total}", index=index, total=total)
