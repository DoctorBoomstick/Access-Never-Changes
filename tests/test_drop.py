"""Drop it, from the item menu.

It had never once worked. It dragged the item onto the character figure, and
the engine only reads a release there as taking something out of a bag opened
inside the inventory (0x00471443); at the top level the item went straight
back. gl_inven.ssl now makes the engine's own Drop calls, and these are the
sentences that come back.
"""

import os
import re
import unittest

from fallout2_access.game import inventory
from fallout2_access.game.inventory import InventoryWatcher, drop_line

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestWhatIsSaid(unittest.TestCase):
    def test_one(self):
        self.assertEqual(drop_line("INVEN:dropped|Xander Root|1|"),
                         "Dropped Xander Root.")

    def test_some_of_a_stack(self):
        self.assertEqual(drop_line("INVEN:dropped|Bottle Caps|40|"),
                         "Dropped 40 Bottle Caps.")

    def test_cancelling_the_how_many_window(self):
        self.assertEqual(drop_line("INVEN:dropnot cancel|"), "Cancelled.")

    def test_from_a_container_or_a_trade(self):
        self.assertIn("own inventory", drop_line("INVEN:dropnot here|"))

    def test_without_the_engine_calls_allowed(self):
        self.assertIn("AllowUnsafeScripting", drop_line("INVEN:dropnot unsafe|"))

    def test_a_failure_is_said_plainly(self):
        self.assertEqual(drop_line("INVEN:dropnot failed|"), "That did not drop.")

    def test_the_count_is_asked(self):
        said = drop_line("INVEN:dropask|Bottle Caps|1|291|")
        self.assertTrue(said.startswith("Drop how many Bottle Caps? 1 of 291."))
        self.assertIn("Enter drops", said)

    def test_the_count_as_it_changes(self):
        self.assertEqual(drop_line("INVEN:dropcount|40|291|"), "40 of 291.")
        self.assertEqual(drop_line("INVEN:dropcount|291|291|"), "All 291.")

    def test_the_watcher_says_it(self):
        self.assertEqual(InventoryWatcher().handle("INVEN:dropped|Rock|1|"),
                         ["Dropped Rock."])


class TestTheScript(unittest.TestCase):
    """The menu entry runs the engine's drop, and drops no longer go to Python."""

    def setUp(self):
        with open(os.path.join(ROOT, "scripts", "gl_inven.ssl"), encoding="latin-1") as fh:
            self.src = fh.read()

    def test_drop_is_the_script_s_own(self):
        self.assertRegex(self.src, r"which == IMENU_DROP\) then begin\s+call drop_item;")

    def test_it_calls_the_engine_s_drop(self):
        body = self.src[self.src.index("procedure drop_item begin"):]
        self.assertIn("call_offset_v2(F_OBJ_DROP", body)
        self.assertIn("call inven_redraw", body)

    def test_the_engine_s_how_many_window_is_never_run_from_the_hook(self):
        """Run from inside the keypress hook it re-entered the hook for every
        key typed into it, ignored the count and crashed the game in sfall's
        read_int."""
        self.assertNotIn("F_QUANTITY_ASK", self.src)
        self.assertNotRegex(self.src, r"call_offset_\w+\(\s*0x0047688C")

    def test_the_count_prompt_owns_the_keyboard_first(self):
        hook = self.src[self.src.index("procedure on_key begin"):]
        self.assertLess(hook.index("if (g_dropask) then begin"),
                        hook.index("if (g_imenu) then begin"))

    def test_use_it_is_gone(self):
        self.assertNotIn('return "use it"', self.src)
        self.assertRegex(self.src, r"#define IMENU_COUNT\s+\(2\)")


if __name__ == "__main__":
    unittest.main()
