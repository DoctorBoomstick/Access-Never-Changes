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

    def test_player_combat_is_combat_plus_pcombat(self):
        """The same bug's second life. `mode in (0, MODE_COMBAT)` looked like a
        fix and was not: during the player's own turn the engine reports 0x840,
        COMBAT and PCOMBAT together, so equality against one value still failed.
        Captured from a live log as `WORLD:gamemode 2112`."""
        self.assertTrue(screens.is_map_mode(0x840))
        self.assertTrue(screens.is_map_mode(2112))
        self.assertTrue(screens.is_map_mode(screens.MODE_PCOMBAT))

    def test_localmap_bit_does_not_hide_the_map(self):
        self.assertTrue(screens.is_map_mode(screens.MODE_LOCALMAP))
        self.assertTrue(screens.is_map_mode(0x842))

    def test_a_panel_over_combat_is_still_a_panel(self):
        """Opening the inventory mid-fight must stop aiming, even though the
        combat bits are still set."""
        self.assertFalse(screens.is_map_mode(0x840 | screens.MODE_INVENTORY))

    def test_unknown_bits_are_treated_as_a_panel(self):
        """Failing this way round is the safe one: decline to aim rather than
        aim into something we have never seen."""
        self.assertFalse(screens.is_map_mode(0x800000))

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

    def test_skill_cursors_are_named(self):
        """Measured by arming each Skilldex key against the live game.

        These were once announced as Skilldex skills on sfall's word alone,
        then "corrected" to scroll cursors when the same values turned up while
        the view scrolled. The probe settled it: the values ARE skills, and
        something else evidently writes direction values into the same variable
        during a scroll.
        """
        self.assertEqual(screens.armed_skill(4), "First Aid")
        self.assertEqual(screens.armed_skill(6), "Lockpick")
        self.assertEqual(screens.armed_skill(10), "Repair")
        self.assertIn("Lockpick", screens.cursor_name(6))

    def test_sneak_has_no_cursor_of_its_own(self):
        """Sneak is a toggle, not something you aim, so the enum skips it --
        which is why the skill numbering has a gap where it would be."""
        self.assertIsNone(screens.armed_skill(screens.CURSOR_MOVEMENT))

    def test_a_mode_outside_the_known_set_claims_nothing(self):
        text = screens.cursor_name(99)
        self.assertIn("99", text)
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
