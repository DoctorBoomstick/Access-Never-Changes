"""Speak the scanner's output.

`gl_world.ssl` does the work -- asking the engine for everything of a kind that
is on screen, rejecting the engine's invisible furniture, and grouping what is
left by name, nearest first. This turns its "SCAN:" lines into speech.

Three levels, because a room can hold a dozen torches and stepping through them
one at a time is unusable:

    category    critters / items / scenery      ctrl [ ]
    type        "Torch", "Rocks", "Giant Ant"   [ ]
    instance    which of the six torches        shift [ ]

How much gets said depends on which level moved. Stepping between instances of
the same torch should not re-announce that they are torches, and changing
category should not make you press again to find out what is in it.

The category and direction words are the mod's own, not the game's. That is the
line this project draws: anything describing the *world* comes from the game, so
translations and content mods keep working, while the scaffolding that describes
how to *navigate* has no in-game equivalent and is ours to write.
"""

from __future__ import annotations

import re
from typing import List, Optional
from ..i18n import tr
from .. import words

_ENTRY = re.compile(
    r"SCAN:entry (\d+)\|(\d+)\|(\d+)\|([^|]*)\|(\d+)\|(\d+)\|(\d+)\|(-?\d+)\|(\d+)\|"
)
_NONE = re.compile(r"SCAN:none (\d+)\|")
_JUMP = re.compile(r"SCAN:jump (\d+)\|")

# The fourth is the way off the map. It reads the engine's MISC list, which
# holds the exit grids and nothing else a player has business with -- see
# SCAN_EXITS in gl_world.ssl for why they are worth a category rather than a
# line in "scenery". "Exits" is the mod's word, like the other three.
def categories() -> List[str]:
    return [tr("scan.critters", "critters"), tr("scan.items", "items"),
            tr("scan.scenery", "scenery"), tr("scan.exits", "exits")]

# What changed, which decides how much needs saying.
LEVEL_INSTANCE = 0
LEVEL_TYPE = 1
LEVEL_CATEGORY = 2

def category_name(index: int) -> str:
    names = categories()
    if 0 <= index < len(names):
        return names[index]
    return tr("scan.category", "category {number}", number=index)


def direction_name(rotation: int) -> str:
    """tile_num_in_direction's 0-5, measured against the live engine rather
    than taken from a table: from tile 17488 the offsets were NE -1, E +199,
    SE +200, SW +201, W +1, NW -200."""
    return words.direction(rotation)


def _where(distance: int, rotation: int) -> str:
    if distance == 0:
        return tr("scan.here", "here")
    bearing = direction_name(rotation)
    if not bearing:
        return words.hexes(distance)
    return tr("scan.where", "{direction} {distance}", direction=bearing,
              distance=words.hexes(distance))


class Scanner:
    """Holds only the last thing said, so it can be repeated on request."""

    def __init__(self) -> None:
        self.last: Optional[str] = None

    def reset(self) -> None:
        self.last = None

    def handle(self, line: str) -> List[str]:
        m = _ENTRY.match(line)
        if m:
            return self._entry(m)
        m = _NONE.match(line)
        if m:
            self.last = None
            return [tr("scan.none", "No {category} in sight.",
                       category=category_name(int(m.group(1))))]
        if _JUMP.match(line):
            # The hex readout that follows says what is there, in the game's own
            # words. Saying it twice helps nobody.
            return []
        return []

    def _entry(self, m) -> List[str]:
        category = int(m.group(1))
        type_index = int(m.group(2))
        type_total = int(m.group(3))
        name = m.group(4).strip()
        instance = int(m.group(5))
        instance_total = int(m.group(6))
        distance = int(m.group(7))
        rotation = int(m.group(8))
        level = int(m.group(9))

        where = _where(distance, rotation)

        if level == LEVEL_INSTANCE:
            # Already know what it is; the question is which one and where.
            text = "{}, {}.".format(where, words.of(instance + 1, instance_total))
            text = "{}, {}".format(name, text) if instance_total == 1 else text

        else:
            # A new type: say what it is, how many there are, and where the
            # nearest one is. The count is the useful part -- it tells you
            # whether shift-bracket is worth pressing at all.
            if instance_total > 1:
                text = tr("scan.type_many", "{name}, {count}, nearest {where}.",
                          name=name, count=instance_total, where=where)
            else:
                text = "{}, {}.".format(name, where)
            text += " {}.".format(words.of(type_index + 1, type_total))
            if level == LEVEL_CATEGORY:
                text = "{}. {}".format(category_name(category).capitalize(), text)

        self.last = text
        return [text]

    def repeat(self) -> Optional[str]:
        return self.last
