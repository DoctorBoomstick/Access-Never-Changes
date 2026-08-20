"""Which screen row holds the item the script calls `index`.

This is arithmetic that was wrong in the live game for weeks, and it hid well:
the move was checked afterwards by counting both lists, the counts were always
right, and a wrong row looks exactly like a right one to a count. Only naming
the item that moved caught it.
"""

import unittest

from fallout2_access.game.itemmove import VISIBLE_ROWS, drawn_row


class TestDrawnRow(unittest.TestCase):
    def test_the_list_is_drawn_backwards(self):
        """The measurement, both ways round, with two items.

        Dragging index 0 moved the Spear -- the script's index 1 -- and dragging
        index 1 moved the Healing Powder, the script's index 0.
        """
        self.assertEqual(drawn_row(0, 2), 1)
        self.assertEqual(drawn_row(1, 2), 0)

    def test_the_scripts_first_item_is_the_engines_last_row(self):
        self.assertEqual(drawn_row(0, 5), 4)
        self.assertEqual(drawn_row(4, 5), 0)

    def test_a_single_item_is_the_only_row(self):
        self.assertEqual(drawn_row(0, 1), 0)

    def test_it_is_its_own_inverse(self):
        """Reversal applied twice is the identity, which is what makes the same
        function correct for reading a row back as for choosing one."""
        for total in range(1, 12):
            for index in range(total):
                self.assertEqual(drawn_row(drawn_row(index, total), total),
                                 index)

    def test_a_stale_total_cannot_produce_a_negative_row(self):
        """A negative row would be added to the base event code and address a
        button belonging to some other control entirely -- a click somewhere
        nobody chose, which is the one outcome worse than refusing."""
        self.assertEqual(drawn_row(5, 2), 0)
        self.assertEqual(drawn_row(3, 0), 0)

    def test_long_lists_push_the_early_items_off_screen(self):
        """With the list drawn backwards it is the script's FIRST items that
        fall outside the six visible rows, not its last."""
        total = 9
        off = [i for i in range(total) if drawn_row(i, total) >= VISIBLE_ROWS]
        self.assertEqual(off, [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
