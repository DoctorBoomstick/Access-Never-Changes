"""Replay recorded fights through the combat watcher and check what gets said.

These are the throwaway checks written while combat was being built, kept. Every
line here was captured from a real fight, engine noise and all, which is what
makes them worth running: two of the bugs they now guard against were invisible
in clean synthetic data.
"""

import unittest

from fallout2_access.game.combat import CombatWatcher


def say(lines):
    w = CombatWatcher()
    out = []
    for line in lines:
        out.extend(w.handle(line))
    return w, out


class TestCombatNarration(unittest.TestCase):
    def test_a_whole_fight(self):
        _w, out = say([
            "COMBAT:turn 1|you|",
            "COMBAT:ap 8|8|",
            "COMBAT:ap 5|8|",
            "COMBAT:miss 1|you|Giant Ant|72|3|",
            "COMBAT:turn 0|you|",
            "COMBAT:turn 1|Giant Ant|",
            "COMBAT:dmg Giant Ant|you|7|256|",
            "COMBAT:turn 0|Giant Ant|",
            "COMBAT:turn 1|you|",
            "COMBAT:ap 8|8|",
            "COMBAT:dmg you|Giant Ant|22|640|",
            "COMBAT:death Giant Ant|",
            "COMBAT:turn -2||",
        ])
        self.assertEqual(out, [
            "Your turn.",
            "8 of 8 action points.",
            "5.",
            "You miss Giant Ant.",
            "Giant Ant's turn.",
            "Giant Ant hits you for 7.",
            "Your turn.",
            "8 of 8 action points.",
            "You hit Giant Ant for 22, critical.",
            "Giant Ant dies.",
            "Combat over.",
        ])

    def test_turn_start_restores_the_full_ap_figure(self):
        """Mid-turn only the remainder matters; at turn start, the total does."""
        _w, out = say([
            "COMBAT:turn 1|you|", "COMBAT:ap 9|9|", "COMBAT:ap 6|9|",
            "COMBAT:turn 0|you|",
            "COMBAT:turn 1|you|", "COMBAT:ap 9|9|",
        ])
        self.assertEqual(out[1], "9 of 9 action points.")
        self.assertEqual(out[2], "6.")
        self.assertEqual(out[-1], "9 of 9 action points.")

    def test_engine_noise_cannot_leak_into_speech(self):
        """The engine appends its own debug output to our lines with no newline.

        Without the trailing separator this said the whole of "Giant Ant is
        using Rat packet with a 0% chance to taunt" as part of the critter's
        name. Recorded verbatim from debug.log.
        """
        _w, out = say([
            "COMBAT:turn 1|Giant Ant|Giant Ant is using Rat packet with a 0% chance to taunt",
            "COMBAT:dmg Giant Ant|you|3|0|sequencing attack...",
        ])
        self.assertEqual(out, ["Giant Ant's turn.", "Giant Ant hits you for 3."])

    def test_death_is_not_announced_twice(self):
        """DAM_DEAD is set on the killing blow, and ONDEATH follows it."""
        _w, out = say([
            "COMBAT:dmg you|Giant Ant|22|640|",
            "COMBAT:death Giant Ant|",
        ])
        self.assertNotIn("killed", out[0])
        self.assertEqual(out[1], "Giant Ant dies.")

    def test_no_action_points_left_is_called_out(self):
        _w, out = say(["COMBAT:turn 1|you|", "COMBAT:ap 4|9|", "COMBAT:ap 0|9|"])
        self.assertEqual(out[-1], "No action points left.")

    def test_target_hover_is_recorded_but_silent(self):
        w, out = say(["COMBAT:target 0|1|Giant Ant|"])
        self.assertEqual(out, [])
        self.assertEqual(w.target_name, "Giant Ant")
        self.assertTrue(w.target_valid)

    def test_summary_reports_turn_and_points(self):
        w, _ = say(["COMBAT:turn 1|you|", "COMBAT:ap 7|9|"])
        self.assertEqual(w.summary(), "Your turn. 7 of 9 action points.")

    def test_summary_outside_combat(self):
        self.assertEqual(CombatWatcher().summary(), "Not in combat.")

    def test_verbs_agree_with_the_subject(self):
        _w, out = say([
            "COMBAT:dmg you|Giant Ant|5|0|",
            "COMBAT:dmg Giant Ant|you|5|0|",
        ])
        self.assertEqual(out[0], "You hit Giant Ant for 5.")
        self.assertEqual(out[1], "Giant Ant hits you for 5.")

    def test_malformed_lines_are_ignored_not_crashed_on(self):
        w = CombatWatcher()
        for junk in ("COMBAT:dmg", "COMBAT:ap x|y|", "COMBAT:turn |", "COMBAT:",
                     "COMBAT:wat 1|2|3|"):
            self.assertEqual(w.handle(junk), [])


if __name__ == "__main__":
    unittest.main()
