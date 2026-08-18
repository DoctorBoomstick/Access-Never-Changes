"""Screen and game-mode logic.

`is_map_mode` gets a test of its own because the same mistake was made twice in
one day, in two different files, and cost most of an evening both times.
"""

import unittest

from fallout2_access.game import screens


class TestMapMode(unittest.TestCase):
    def test_plain_map_view(self):
        self.assertTrue(screens.is_map_mode(0))

    def test_combat_counts_as_the_map(self):
        """The bug. Combat is its own mode, not a flag on top of mode 0.

        Testing `mode == 0` disabled aiming for every fight, so attacks clicked
        wherever the pointer had last been left -- and separately switched off
        the script's own telemetry, which is what made it hard to see.
        """
        self.assertTrue(screens.is_map_mode(screens.MODE_COMBAT))
        self.assertTrue(screens.is_map_mode(0x40))

    def test_panels_are_not_the_map(self):
        for mode in (screens.MODE_DIALOG, screens.MODE_INVENTORY,
                     screens.MODE_PIPBOY, screens.MODE_BARTER,
                     screens.MODE_SKILLDEX, screens.MODE_CHARSCREEN,
                     screens.MODE_WORLDMAP):
            self.assertFalse(screens.is_map_mode(mode), hex(mode))

    def test_unknown_mode_is_not_the_map(self):
        """Unknown means unknown. Aiming a click on a guess is how you attack
        something you never chose."""
        self.assertFalse(screens.is_map_mode(None))


class TestCursorNames(unittest.TestCase):
    def test_known_cursors_are_named(self):
        self.assertIn("walks", screens.cursor_name(screens.CURSOR_MOVEMENT))
        self.assertIn("interacts", screens.cursor_name(screens.CURSOR_COMMAND))
        self.assertIn("attacks", screens.cursor_name(screens.CURSOR_TARGETING))

    def test_unknown_cursors_claim_nothing(self):
        """These were once announced as Skilldex skills on the strength of
        sfall's docs. Live logs showed the value tracking the direction the view
        had just scrolled. An unknown mode now reports a number and the one fact
        that is definitely true about it."""
        for mode in (5, 7, 8, 9, 10):
            text = screens.cursor_name(mode)
            self.assertIn(str(mode), text)
            self.assertNotIn("Skilldex", text)
            self.assertIn("numpad 0", text)

    def test_unknown_is_none_not_a_guess(self):
        self.assertIsNone(screens.cursor_name(None))


class TestModeNames(unittest.TestCase):
    def test_zero_is_exploring(self):
        self.assertEqual(screens.mode_name(0), "exploring")

    def test_combined_modes(self):
        self.assertIn("combat", screens.mode_name(screens.MODE_COMBAT))

    def test_unknown_mode_is_not_invented(self):
        self.assertEqual(screens.mode_name(None), "unknown")


if __name__ == "__main__":
    unittest.main()
