"""The character screen of a character who already exists.

Every number in these fixtures came off a real sheet, described aloud by a
sighted reader while the mod read the same character out of memory. That pairing
is what exposed the bug: the mod's readings and the screen's disagreed, and the
screen was right.

    Perception          base table 8      screen 6    (a drug penalty)
    Small Guns          computed 37       screen 47   (tags and spent points)
    Damage Resistance   base table 0      screen 8%   (armour)

None of those are readable from the stat table, and all three are what
get_critter_stat and has_skill return.
"""

import unittest

from fallout2_access.game import charsheet

# The sheet as the engine reports it for that character.
LINES = (
    "CHAR:stats 5|6|3|7|5|8|4|",
    "CHAR:derived 8|9|158|1|8|15|6|12|1|4|",
    "CHAR:cond 7|26|10|8|0|",
    "CHAR:skills 47|6|6|64|36|22|37|31|49|24|24|22|15|17|78|43|28|16|",
    "CHAR:pc 1|765|0|",
)


def sheet(lines=LINES):
    s = charsheet.Sheet()
    for line in lines:
        s.handle(line)
    return s


class TestReading(unittest.TestCase):
    def test_the_whole_sheet_parses(self):
        s = sheet()
        self.assertTrue(s.ready)
        self.assertEqual(s.special, [5, 6, 3, 7, 5, 8, 4])
        self.assertEqual(len(s.skills), 18)
        self.assertEqual((s.hp, s.max_hp), (7, 26))
        self.assertEqual((s.level, s.experience), (1, 765))

    def test_the_values_the_base_table_gets_wrong(self):
        """The three that made this necessary."""
        s = sheet()
        self.assertEqual(s.special[1], 6, "Perception, after the drug penalty")
        self.assertEqual(s.skills[0], 47, "Small Guns, after tags and points")
        self.assertEqual(s.derived[4], 8, "Damage Resistance, from armour")

    def test_a_partial_sheet_is_not_ready(self):
        """Five lines arrive across a frame or two. Half a sheet must not be
        read out as though it were the whole one."""
        self.assertFalse(sheet(LINES[:2]).ready)

    def test_a_line_that_is_not_ours(self):
        s = charsheet.Sheet()
        self.assertFalse(s.handle("WORLD:hex 1 dist 0 : you|"))


class TestConditions(unittest.TestCase):
    """The condition box lists a fixed column of labels and lights the ones
    that apply, so only the set ones may be spoken. Reading the column out
    would tell a player they are blind and missing both legs when they are
    fine."""

    def cond(self, state=0, poison=0, rads=0):
        s = sheet()
        s.state, s.poison, s.rads = state, poison, rads
        return charsheet.conditions(s)

    def test_a_healthy_character_has_nothing_wrong(self):
        self.assertEqual(self.cond(), [])

    def test_poison_and_radiation_are_stats_not_flags(self):
        self.assertEqual(self.cond(poison=10, rads=8), ["poisoned", "radiated"])

    def test_crippling_comes_from_the_state_bitmask(self):
        self.assertEqual(self.cond(state=0x04 | 0x20),
                         ["crippled left leg", "crippled right arm"])

    def test_blinded(self):
        self.assertIn("blinded", self.cond(state=0x40))


class TestSheetClearedWithTheScreen(unittest.TestCase):
    """A sheet that outlived its screen would be read out over the NEXT
    character -- and the creation editor is exactly where the reader has to
    fall back on the editor's own working copy."""

    def test_leaving_the_character_screen_drops_it(self):
        import os
        import tempfile
        from fallout2_access.game.worldlog import WorldLog

        path = os.path.join(tempfile.mkdtemp(), "debug.log")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("WORLD:gamemode 512\n")
            for line in LINES:
                fh.write(line + "\n")
        log = WorldLog(path)
        log.poll()
        self.assertTrue(log.sheet.ready)

        with open(path, "a", encoding="utf-8") as fh:
            fh.write("WORLD:gamemode 0\n")
        log.poll()
        self.assertFalse(log.sheet.ready, "the sheet outlived its screen")


if __name__ == "__main__":
    unittest.main()


class TestSkilldex(unittest.TestCase):
    """The Skilldex panel: eight skills behind eight number keys.

    It was unreachable in the way that is easiest to miss -- opening it
    announced "skilldex" and stopped, so the player knew a panel existed and
    nothing about what was on it.
    """

    NAMES = {100 + i: n for i, n in enumerate([
        "Small Guns", "Big Guns", "Energy Weapons", "Unarmed", "Melee Weapons",
        "Throwing", "First Aid", "Doctor", "Sneak", "Lockpick", "Steal",
        "Traps", "Science", "Repair", "Speech", "Barter", "Gambling",
        "Outdoorsman"])}

    # The sneak state rides on the same line as the list. Sent separately it
    # was a second announcement, and both are marked as answers to a keypress,
    # so it cut the list off mid-word -- the panel read out as nothing but
    # "Not sneaking." and the eight skills it exists to report were never heard.
    LINE = "SKILLDEX:list 0|8,49|9,24|10,24|11,22|6,37|7,31|12,15|13,17|"

    def test_the_key_number_is_the_panel_position_not_the_skill_index(self):
        """Sneak is skill 8 and is pressed with 1. Numbering the list by skill
        index would tell the player to press 9 for Lockpick, which arms
        nothing."""
        said = charsheet.skilldex_line(self.LINE, self.NAMES)
        self.assertIn("1 Sneak, 49 percent.", said)
        self.assertIn("2 Lockpick, 24 percent.", said)
        self.assertIn("8 Repair, 17 percent.", said)

    def test_the_percentages_come_with_the_names(self):
        """"Lockpick, 24 percent" is the number you are deciding on when you
        choose whether to try the door at all."""
        self.assertIn("24 percent", charsheet.skilldex_line(self.LINE, self.NAMES))

    def test_unnamed_skills_do_not_break_the_list(self):
        said = charsheet.skilldex_line(self.LINE, {})
        self.assertIn("skill 8", said)

    def test_the_sneak_state_travels_with_the_list(self):
        """One announcement, not two. Two got the first one cut off."""
        said = charsheet.skilldex_line(self.LINE, self.NAMES)
        self.assertIn("Not sneaking.", said)
        self.assertIn("1 Sneak, 49 percent.", said)
        on = charsheet.skilldex_line(self.LINE.replace("list 0|", "list 1|"),
                                     self.NAMES)
        self.assertIn("Sneaking.", on)
        self.assertIn("8 Repair", on)

    def test_a_line_that_is_not_ours(self):
        self.assertIsNone(charsheet.skilldex_line("WORLD:hex 1 dist 0 : you|",
                                                  self.NAMES))


class TestSneakState(unittest.TestCase):
    """Sneak is the one Skilldex entry with no cursor of its own.

    Arming Lockpick changes the cursor and that change is announced, so you
    know it took. Pressing 1 changes nothing audible, and the engine prints
    nothing either -- measured by toggling it twice with the game's own message
    window under watch, which stayed empty both times.
    """

    def test_on_and_off(self):
        self.assertEqual(charsheet.sneak_line("SKILLDEX:sneak 1|"), "Sneaking.")
        self.assertEqual(charsheet.sneak_line("SKILLDEX:sneak 0|"),
                         "Not sneaking.")

    def test_a_line_that_is_not_ours(self):
        self.assertIsNone(charsheet.sneak_line("SKILLDEX:list 8,49|"))


class TestNextLevel(unittest.TestCase):
    """The third line of the level box.

    Computed rather than read, because there is nothing to read: the module was
    scanned for the sequence 1000, 3000, 6000 -- with and without a leading
    zero -- and Fallout keeps no such table. It works the figure out each time.
    """

    def test_the_live_sheet_s_own_value(self):
        """A screenshot at level 1 prints "Next Level: 1,000"."""
        self.assertEqual(charsheet.next_level_experience(1), 1000)

    def test_the_progression(self):
        """Reaching L costs L*(L-1)/2 thousand, so from L the next wants
        (L+1)*L/2 thousand."""
        self.assertEqual(charsheet.next_level_experience(2), 3000)
        self.assertEqual(charsheet.next_level_experience(3), 6000)
        self.assertEqual(charsheet.next_level_experience(4), 10000)

    def test_no_level_no_answer(self):
        self.assertIsNone(charsheet.next_level_experience(None))
        self.assertIsNone(charsheet.next_level_experience(0))
