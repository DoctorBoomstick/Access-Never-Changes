"""Speak the inventory, loot and barter windows.

`gl_inven.ssl` reads the lists out of the engine and writes "INVEN:" lines;
this turns them into speech. It holds no idea of what is in a container -- every
line reports what the engine said at the moment the key was pressed, which is
the same rule the rest of the mod follows and the reason the speech cannot drift
away from the game.

Three lists, because the window has three and they mean different things:

    yours       what you are carrying
    theirs      the container, the corpse, or the person you are trading with
    worn        armour and the two hands

The worn list is a fixed three slots rather than a list of what happens to be
there, because an empty hand is a fact worth hearing. "Item 2, empty" is the
answer to "can I pick something up", and a list that simply omitted it would
leave that question unanswerable.

As everywhere else here, item names and weights are the game's own. The words
that describe *navigation* -- which list, which slot, how far through -- are
ours, because the game has no phrase for them: it simply shows you.
"""

from __future__ import annotations

import re
from typing import List, Optional

from . import screens

SIDE_MINE = 0
SIDE_THEIRS = 1
SIDE_WORN = 2

SIDE_NAMES = {
    SIDE_MINE: "yours",
    SIDE_THEIRS: "theirs",
    SIDE_WORN: "worn",
}

# What an empty list is called out loud. An empty carried list is now somewhere
# the player can deliberately stand -- it is where an unequipped item has to go
# -- so it needs a sentence that makes sense as a destination rather than the
# "No yours here" that the side names produced.
EMPTY_SIDE = {
    SIDE_MINE: "Carrying nothing.",
    SIDE_THEIRS: "Nothing there.",
    SIDE_WORN: "Wearing nothing.",
}

# The three fixed slots down the middle of the window. These are the game's own
# labels, printed on the window itself, which is why they are capitalised the
# way they are on screen.
WORN_SLOTS = ["Armor", "Item 1", "Item 2"]

_OPEN = re.compile(r"INVEN:open (\d+)\|([^|]*)\|(\d+)\|(\d+)\|")
# Where the window is, straight from sfall. This is what lets the mod find the
# same window in memory and read its buttons: a rectangle the engine states is
# a rectangle we do not have to guess, so the struct we match is confirmed
# rather than assumed.
_RECT = re.compile(r"INVEN:rect (\d+)\|(\d+)\|(\d+)\|(\d+)\|(\d+)\|(\d+)x(\d+)\|")
_ENTRY = re.compile(
    r"INVEN:entry (\d+)\|(\d+)\|(\d+)\|([^|]*)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|"
)
_NONE = re.compile(r"INVEN:none (\d+)\|")
_SUMMARY = re.compile(
    r"INVEN:summary (\d+)\|(-?\d+)\|(-?\d+)\|(\d+)\|(\d+)\|(-?\d+)\|"
)

HELP = ("Numpad 8 and 2 step the list, 4 and 6 change list, "
        "5 re-reads, 0 gives the totals.")


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _items(n: int) -> str:
    return "{} {}".format(n, _plural(n, "item", "items"))


class InventoryWatcher:
    """Turns INVEN: log lines into things to say."""

    def __init__(self) -> None:
        self.open = False
        self.container: Optional[str] = None
        self.last: Optional[str] = None
        # Where the window sits, and what is selected in it. Held so that the
        # part of the mod that moves an item knows which row to point at
        # without having to ask the game again -- the script already said.
        self.rect: Optional[tuple] = None       # (x, y, width, height)
        self.side: Optional[int] = None
        self.index: int = 0
        self.total: int = 0
        self.selected: Optional[str] = None     # the item's own name
        # (weight carried, items carried, items on the other side), from the
        # totals line. The only reading a move reliably changes.
        self.counts: Optional[tuple] = None

    def reset(self) -> None:
        self.open = False
        self.container = None
        self.last = None
        self.rect = None
        self.side = None
        self.index = 0
        self.total = 0
        self.selected = None
        self.counts = None

    def handle(self, line: str) -> List[str]:
        """One INVEN: line in, zero or more things to say out."""
        m = _RECT.match(line)
        if m:
            self.rect = (int(m.group(1)), int(m.group(2)),
                         int(m.group(3)), int(m.group(4)))
            return []
        m = _OPEN.match(line)
        if m:
            return self._open(m)
        m = _ENTRY.match(line)
        if m:
            return self._entry(m)
        m = _NONE.match(line)
        if m:
            side = int(m.group(1))
            self.side, self.index, self.total = side, 0, 0
            self.selected = None
            self.last = EMPTY_SIDE.get(side, "Nothing here.")
            return [self.last]
        m = _SUMMARY.match(line)
        if m:
            return self._summary(m)
        if line.startswith("INVEN:close"):
            was, self.open = self.open, False
            self.container = None
            self.last = None
            return ["Closed."] if was else []
        return []

    # -- handlers -------------------------------------------------------

    def _open(self, m) -> List[str]:
        mode = int(m.group(1))
        name = m.group(2).strip()
        theirs = int(m.group(3))
        mine = int(m.group(4))
        self.open = True
        self.container = name or None

        # Name the window from the game mode rather than from whether a
        # container happened to be found: a corpse with nothing on it and a
        # window that failed to identify what it was looking at should not
        # sound the same.
        what = screens.mode_name(mode)
        if name:
            head = "{}: {}. {}.".format(what.capitalize(), name, _items(theirs))
        else:
            head = "{}.".format(what.capitalize())
        return ["{} You are carrying {}. {}".format(head, _items(mine), HELP)]

    def _entry(self, m) -> List[str]:
        side = int(m.group(1))
        index = int(m.group(2))
        total = int(m.group(3))
        name = m.group(4).strip()
        count = int(m.group(5))
        weight = int(m.group(6))
        slot = int(m.group(7))

        self.side, self.index, self.total = side, index, total
        self.selected = name or None

        if slot >= 0:
            # A worn slot. The slot's name comes first because it is what the
            # player is navigating by -- they are asking what is in their right
            # hand, not hunting for an item.
            label = WORN_SLOTS[slot] if slot < len(WORN_SLOTS) else "Slot {}".format(slot + 1)
            text = "{}, {}.".format(label, name or "empty")
            self.last = text
            return [text]

        if not name:
            # An entry the engine offered but would not name. This used to
            # return nothing, which is the one answer a blind player cannot act
            # on: pressing a key and hearing silence is indistinguishable from
            # the key never arriving, and that is exactly how it was reported.
            # Say the position, which is true, and say the name is missing,
            # which is also true and is a bug report rather than a guess.
            text = "Unnamed item. {} of {}.".format(index + 1, total)
            self.last = text
            return [text]

        parts = [name]
        # Only say "3" when there is more than one. A quantity of one on every
        # single item is noise on every single item.
        if count > 1:
            parts.append(str(count))
        if weight > 0:
            parts.append("{} {}".format(weight, _plural(weight, "pound", "pounds")))
        text = "{}. {} of {}.".format(", ".join(parts), index + 1, total)
        self.last = text
        return [text]

    def _summary(self, m) -> List[str]:
        carried = int(m.group(2))
        capacity = int(m.group(3))
        mine = int(m.group(4))
        theirs = int(m.group(5))
        ap_cost = int(m.group(6))

        # The counts a move actually changes. An item leaving the carried list
        # for an equipment slot changes this and nothing about the slot side's
        # own reading, which is why checking the selected side called every
        # successful equip a failure.
        self.counts = (carried, mine, theirs)

        parts = ["Carrying {}, {} of {} pounds.".format(
            _items(mine), carried, capacity)]
        if theirs:
            parts.append("{} there.".format(_items(theirs)))
        # The AP cost of an inventory action only exists during a fight, and it
        # is the number that decides whether swapping a weapon is affordable.
        if ap_cost > 0:
            parts.append("{} action {} to use an item.".format(
                ap_cost, _plural(ap_cost, "point", "points")))
        return [" ".join(parts)]

    def repeat(self) -> Optional[str]:
        return self.last
