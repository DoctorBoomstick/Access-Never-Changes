"""Reading the engine's action menu out of memory.

The list is never empty between menus -- it holds whatever was last built -- so
the failure mode here is a confident answer about the wrong object. Everything
below is about not doing that.
"""

import struct
import unittest

import fakes

from fallout2_access.game import actions


def memory(codes, tail=()):
    """A fake holding an action list, plus whatever follows it in memory."""
    mem = fakes.FakeMemory()
    words = list(codes) + [0] + list(tail)
    blob = b"".join(struct.pack("<i", w) for w in words)
    blob = blob.ljust(4 * actions.MAX_ACTIONS, b"\x00")
    mem.poke(actions.ACTION_LIST, blob)
    return mem


class TestReadList(unittest.TestCase):
    def test_a_container_offers_use(self):
        """Measured on a Pot: use, look, use an item on it, use a skill."""
        self.assertEqual(actions.read_list(memory([6, 3, 2, 8])), [6, 3, 2, 8])

    def test_plain_scenery_loses_use(self):
        """Measured on a Stone Bench. This difference is what identifies 6 as
        Use -- a bench is the same list minus exactly that entry."""
        self.assertEqual(actions.read_list(memory([3, 2, 8])), [3, 2, 8])

    def test_the_list_stops_at_the_terminator(self):
        """The array is not cleared, only overwritten, so whatever the previous
        object needed is still sitting past the end of a shorter list."""
        self.assertEqual(actions.read_list(memory([3, 2, 8], tail=[6, 3])),
                         [3, 2, 8])

    def test_nothing_at_all_is_an_empty_list(self):
        self.assertEqual(actions.read_list(memory([])), [])

    def test_unreadable_memory_is_an_empty_list(self):
        self.assertEqual(actions.read_list(fakes.FakeMemory()), [])

    def test_a_wild_value_stops_the_walk(self):
        """Menu codes are small. A large one means the array is not what we
        think, and stopping beats announcing "action 1734437990"."""
        self.assertEqual(actions.read_list(memory([3, 1734437990, 8])), [3])

    def test_it_never_runs_past_its_bound(self):
        self.assertLessEqual(
            len(actions.read_list(memory([3] * 40))), actions.MAX_ACTIONS)


class TestDescribe(unittest.TestCase):
    def test_the_backpack_is_named_for_what_it_does(self):
        """"Inventory" is what the engine calls it; what it MEANS is using one
        of your items on the thing -- which is the whole point of asking."""
        self.assertIn("use an item on it", actions.describe([2]))

    def test_a_full_container_menu_reads_as_a_sentence(self):
        self.assertEqual(
            actions.describe([6, 3, 2, 8]),
            "You can use it, look at it, use an item on it, use a skill on it.")

    def test_nothing_available_says_so(self):
        self.assertEqual(actions.describe([]), "Nothing you can do to it.")

    def test_an_unknown_code_is_a_number_not_a_guess(self):
        """The names come from the engine's ordering and only USE was pinned
        down by measurement, so a code outside the table is reported as itself.
        Naming it wrongly would describe an action that cannot be checked."""
        text = actions.describe([3, 42])
        self.assertIn("action 42", text)
        self.assertIn("look at it", text)


if __name__ == "__main__":
    unittest.main()
