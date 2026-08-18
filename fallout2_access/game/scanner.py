"""Speak the scanner's output.

`gl_world.ssl` does the work -- asking the engine for everything of a kind that
is currently on screen, filtering it, and sorting nearest first. This turns its
"SCAN:" lines into speech.

The categories and direction names are the mod's own words, not the game's.
That is the line this project draws: anything describing the *world* (a
critter's name, an item, a damage figure) comes from the game so translations
and content mods keep working, while the scaffolding that describes how to
*navigate* -- "critters", "north east", "3 of 7" -- has no in-game equivalent
and is ours to write.
"""

from __future__ import annotations

import re
from typing import List, Optional

_ENTRY = re.compile(
    r"SCAN:entry (\d+)\|(\d+)\|(\d+)\|([^|]*)\|(\d+)\|(-?\d+)\|(\d+)\|"
)
_NONE = re.compile(r"SCAN:none (\d+)\|")
_JUMP = re.compile(r"SCAN:jump (\d+)\|")

CATEGORIES = ["critters", "items", "scenery"]

# tile_num_in_direction's 0-5, measured against the live engine rather than
# taken from a table: from tile 17488 the offsets were NE -1, E +199, SE +200,
# SW +201, W +1, NW -200.
DIRECTIONS = ["north east", "east", "south east", "south west", "west", "north west"]


def category_name(index: int) -> str:
    if 0 <= index < len(CATEGORIES):
        return CATEGORIES[index]
    return "category {}".format(index)


def direction_name(rotation: int) -> str:
    if 0 <= rotation < len(DIRECTIONS):
        return DIRECTIONS[rotation]
    return ""


class Scanner:
    """Holds only what was last heard, so it can be repeated on request."""

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
            return ["No {} in sight.".format(category_name(int(m.group(1))))]
        if _JUMP.match(line):
            # The hex readout that follows says what is there, which is the
            # same thing this would say and better sourced.
            return []
        return []

    def _entry(self, m) -> List[str]:
        category = int(m.group(1))
        index = int(m.group(2))
        total = int(m.group(3))
        name = m.group(4).strip()
        distance = int(m.group(5))
        rotation = int(m.group(6))
        announce_category = m.group(7) == "1"

        where = direction_name(rotation)
        parts = [name]
        if distance:
            parts.append(
                "{} {}".format(where, distance).strip()
                + (" hex" if distance == 1 else " hexes")
            )
        else:
            parts.append("here")
        # Position in the list last: you need it to know whether to keep
        # pressing, but it is the least interesting part of the answer.
        parts.append("{} of {}".format(index + 1, total))

        text = ", ".join(parts) + "."
        if announce_category:
            text = "{}. {}".format(category_name(category).capitalize(), text)
        self.last = text
        return [text]

    def repeat(self) -> Optional[str]:
        return self.last
