"""The save and load screens: which slot is highlighted, and what is in it.

These are the same screen twice, and the pair matter more than they look. A save
you cannot load is a slower way of losing an evening, and until now the mod
could read the savegame folder while the one screen that acts on it said
nothing at all.

**It was never a mouse problem.** The arrow keys already move the highlight --
measured, by watching a value rise on down and fall on up. The screen has been
navigable all along and simply silent, which is the failure this project keeps
meeting: a working thing that makes no sound is indistinguishable from a broken
one.

Three readings, all confirmed against a live game:

`OPEN` is non-zero while either screen is up and zero at the main menu. That
matters because no in-game script runs before a game is loaded, so the usual
"ask the script for the game mode" is unavailable here and the screen has to be
recognised from memory alone.

`SELECTION` is the highlighted row, 0 to 9, clamping at both ends rather than
wrapping. The first candidate for this was wrong in an instructive way: it rose
on *both* arrows, because it counted keypresses rather than tracking a position.
Watching it rise and fall in opposite directions is what separated them.

`OCCUPIED` is ten flags saying whether each visible row holds a game. With five
quick saves in slots 11 to 15 it read all zeros on the first page and
[1,1,1,1,1,0,0,0,0,0] on the second -- the engine stating exactly what the
screen shows.

**The page is caused, not read.** The page number does live in memory, but only
on the heap, which moves every launch and cannot be addressed. It does not need
to be: the page controls are buttons like any other, so clicking "first page"
puts the list at page zero *by construction* and counting from there is exact.
That is the same answer the inventory's scroll position got, for the same
reason -- a state you can set is worth more than one you have to find.
"""

from __future__ import annotations

from typing import List, Optional

# Non-zero while the save or load screen is showing.
OPEN = 0x00614858

# The highlighted row on the visible page: 0..9, clamped at both ends.
SELECTION = 0x005193B8

# Ten flags, one per visible row: does that row hold a saved game?
OCCUPIED = 0x00614280

SLOTS_PER_PAGE = 10


class SlotScreen:
    """Reads the save/load screen. Sends nothing and changes nothing."""

    def __init__(self, proc) -> None:
        self.proc = proc

    @property
    def showing(self) -> bool:
        value = self.proc.read_i32(OPEN)
        return bool(value)

    def selection(self) -> Optional[int]:
        """The highlighted row, or None if it reads implausibly.

        Bounds-checked rather than trusted. This is the number that decides
        which saved game gets overwritten, and a stale or wrong read here is
        the one mistake in this project that destroys something.
        """
        value = self.proc.read_i32(SELECTION)
        if value is None or not (0 <= value < SLOTS_PER_PAGE):
            return None
        return value

    def occupied(self) -> List[bool]:
        """Which of the ten visible rows hold a game, straight from the engine.

        Preferred over deciding from the savegame folder alone: this is what the
        screen is actually displaying, and if the two ever disagree the screen
        is what the player is about to act on.
        """
        out: List[bool] = []
        for i in range(SLOTS_PER_PAGE):
            value = self.proc.read_i32(OCCUPIED + 4 * i)
            out.append(bool(value))
        return out

    def slot_number(self, page: int, index: int) -> int:
        """Which slot on disk a row is. Rows are 0-based, slots are 1-based."""
        return page * SLOTS_PER_PAGE + index + 1


def describe(number: int, taken: bool, saved) -> str:
    """What to say about one row.

    `taken` is the engine's own answer; `saved` is the matching Slot from the
    savegame folder, or None. The engine decides whether the row holds a game,
    because that is what the screen shows and what the player is about to act
    on; the folder only supplies the words.

    The disagreement is worth wording carefully rather than hiding. A row the
    engine calls occupied with no readable file behind it is still a row that
    will be overwritten, and saying "empty" there would be the most expensive
    wrong sentence this mod could produce.
    """
    if not taken:
        return "Slot {}, empty.".format(number)
    if saved is None:
        return "Slot {}, a saved game.".format(number)
    return saved.announce()
