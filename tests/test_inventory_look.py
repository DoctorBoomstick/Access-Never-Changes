"""Looking at a carried item.

The one entry on the item menu that needs no pointer: the description is a
string the engine is already holding, so it arrives complete and the only way
to get it wrong is in the parsing.
"""

from __future__ import annotations

import unittest

from fallout2_access.game import inventory


class LookLineTest(unittest.TestCase):
    def test_the_name_comes_before_the_description(self):
        """The list cursor can move between opening the menu and choosing from
        it, so the answer has to say which item it answered for."""
        said = inventory.look_line(
            "INVEN:look|Stimpak|A healing chem. When injected, it provides "
            "immediate healing of interior wounds.|")
        self.assertTrue(said.startswith("Stimpak."), said)
        self.assertIn("immediate healing", said)

    def test_an_item_with_no_description_says_so(self):
        """Silence reads as the key not working -- the failure this codebase
        keeps having to fix everywhere else."""
        self.assertEqual(inventory.look_line("INVEN:look|Rock||"),
                         "Rock. No description.")

    def test_a_description_spanning_lines_survives(self):
        """Some prototype descriptions carry newlines. Dropping everything
        after the first would truncate mid-sentence and sound complete."""
        said = inventory.look_line(
            "INVEN:look|Flare|A flare.\nBurns brightly.|")
        self.assertIn("Burns brightly", said)

    def test_a_line_that_is_not_a_look_is_declined(self):
        self.assertIsNone(inventory.look_line("INVEN:menu open|Stimpak|3|"))


if __name__ == "__main__":
    unittest.main()
