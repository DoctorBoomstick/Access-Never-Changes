"""Reading the save and load screens.

Everything here guards the same thing: this is the one screen in the game where
a wrong sentence destroys something. Saying "empty" about a row that holds a
game is how an evening gets overwritten, so the engine's own answer decides
whether a row is occupied and the savegame folder only supplies the words.
"""

import struct
import unittest

from fallout2_access.game.saves import Slot
from fallout2_access.game.slotscreen import (
    OCCUPIED,
    OPEN,
    SELECTION,
    SLOTS_PER_PAGE,
    SlotScreen,
    describe,
)


class FakeProc:
    """A process with just the handful of addresses this reads.

    Keyed by address, so it takes a dict rather than keywords -- integers are
    not valid keyword names.
    """

    def __init__(self, values=None):
        self.values = dict(values or {})

    def read_i32(self, addr):
        return self.values.get(addr)


def proc(open_=1, selection=0, occupied=()):
    values = {OPEN: open_, SELECTION: selection}
    for i in range(SLOTS_PER_PAGE):
        values[OCCUPIED + 4 * i] = 1 if i < len(occupied) and occupied[i] else 0
    return FakeProc(values)


class TestShowing(unittest.TestCase):
    def test_open_when_the_flag_is_set(self):
        self.assertTrue(SlotScreen(proc(open_=1)).showing)

    def test_closed_at_the_main_menu(self):
        self.assertFalse(SlotScreen(proc(open_=0)).showing)

    def test_an_unreadable_flag_is_not_open(self):
        self.assertFalse(SlotScreen(FakeProc()).showing)


class TestSelection(unittest.TestCase):
    def test_the_highlighted_row_is_read(self):
        self.assertEqual(SlotScreen(proc(selection=4)).selection(), 4)

    def test_both_ends_of_the_range_are_valid(self):
        self.assertEqual(SlotScreen(proc(selection=0)).selection(), 0)
        self.assertEqual(SlotScreen(proc(selection=9)).selection(), 9)

    def test_a_value_off_the_end_is_refused(self):
        """This is the number that decides which game gets overwritten, so a
        reading outside the ten rows is not repaired into a guess."""
        self.assertIsNone(SlotScreen(proc(selection=10)).selection())
        self.assertIsNone(SlotScreen(proc(selection=-1)).selection())

    def test_an_unreadable_selection_is_none(self):
        self.assertIsNone(SlotScreen(FakeProc()).selection())


class TestOccupancy(unittest.TestCase):
    def test_the_engines_own_answer_is_read_per_row(self):
        s = SlotScreen(proc(occupied=(1, 1, 1, 1, 1, 0, 0, 0, 0, 0)))
        self.assertEqual(s.occupied(),
                         [True] * 5 + [False] * 5)

    def test_an_empty_page_reads_as_all_empty(self):
        self.assertEqual(SlotScreen(proc()).occupied(), [False] * 10)


class TestSlotNumbers(unittest.TestCase):
    """Rows are 0-based on screen; slots are 1-based on disk. Mixing the two
    silently targets the wrong saved game."""

    def test_the_first_page_starts_at_one(self):
        s = SlotScreen(proc())
        self.assertEqual(s.slot_number(0, 0), 1)
        self.assertEqual(s.slot_number(0, 9), 10)

    def test_the_second_page_continues(self):
        s = SlotScreen(proc())
        self.assertEqual(s.slot_number(1, 0), 11)
        self.assertEqual(s.slot_number(1, 4), 15)


class TestDescribe(unittest.TestCase):
    def setUp(self):
        self.saved = Slot(number=15, written=0, size=1, character="Narg",
                          description="QUICK: 20/08/2026 - 01:42:25")

    def test_an_occupied_row_reads_out_the_saves_own_words(self):
        self.assertEqual(describe(15, True, self.saved),
                         "Slot 15, QUICK: 20/08/2026 - 01:42:25.")

    def test_an_empty_row_says_empty(self):
        self.assertEqual(describe(3, False, None), "Slot 3, empty.")

    def test_an_occupied_row_with_no_file_is_still_occupied(self):
        """The engine says the row holds a game, so it will be overwritten --
        saying "empty" here is the most expensive wrong sentence available."""
        self.assertEqual(describe(7, True, None), "Slot 7, a saved game.")

    def test_a_file_present_but_the_row_empty_is_not_described(self):
        """The screen is what the player is about to act on, so the engine wins
        over the folder when they disagree."""
        self.assertEqual(describe(15, False, self.saved), "Slot 15, empty.")


if __name__ == "__main__":
    unittest.main()
