"""The scanner's narration.

Line format, all fields terminated so engine noise cannot leak in:
    SCAN:entry cat|typeIdx|nTypes|name|instIdx|nInsts|dist|rotation|level|
"""

import unittest

from fallout2_access.game.scanner import Scanner, category_name, direction_name


def say(lines):
    s = Scanner()
    out = []
    for line in lines:
        out.extend(s.handle(line))
    return s, out


class TestLevels(unittest.TestCase):
    def test_category_change_says_everything(self):
        _s, out = say(["SCAN:entry 2|0|12|Torch|0|6|4|0|2|"])
        self.assertEqual(out, ["Scenery. Torch, 6, nearest north east 4 hexes. 1 of 12."])

    def test_type_change_drops_the_category(self):
        _s, out = say(["SCAN:entry 2|1|12|Rocks|0|3|2|1|1|"])
        self.assertEqual(out, ["Rocks, 3, nearest east 2 hexes. 2 of 12."])

    def test_instance_change_drops_the_name(self):
        """Stepping between six torches should not say "torch" six times."""
        _s, out = say(["SCAN:entry 2|0|12|Torch|2|6|7|3|0|"])
        self.assertEqual(out, ["south west 7 hexes, 3 of 6."])

    def test_lone_instance_keeps_its_name(self):
        """With only one of a thing, a bare bearing would be meaningless."""
        _s, out = say(["SCAN:entry 0|0|1|Giant Ant|0|1|4|0|0|"])
        self.assertEqual(out, ["Giant Ant, north east 4 hexes, 1 of 1."])

    def test_single_of_a_type_omits_the_count(self):
        _s, out = say(["SCAN:entry 0|0|3|Klint|0|1|2|1|1|"])
        self.assertEqual(out, ["Klint, east 2 hexes. 1 of 3."])


class TestPhrasing(unittest.TestCase):
    def test_singular_hex(self):
        _s, out = say(["SCAN:entry 1|0|1|Knife|0|1|1|4|1|"])
        self.assertIn("west 1 hex.", out[0])

    def test_distance_zero_is_here(self):
        _s, out = say(["SCAN:entry 1|0|1|Knife|0|1|0|0|1|"])
        self.assertIn("here", out[0])
        self.assertNotIn("0 hex", out[0])

    def test_names_with_spaces_survive(self):
        _s, out = say(["SCAN:entry 0|0|1|Lesser Scorpion|0|2|3|2|1|"])
        self.assertIn("Lesser Scorpion", out[0])

    def test_engine_noise_after_the_terminator_is_discarded(self):
        _s, out = say(["SCAN:entry 0|0|1|Giant Ant|0|1|4|0|0|sequencing attack..."])
        self.assertEqual(out, ["Giant Ant, north east 4 hexes, 1 of 1."])

    def test_empty_category_says_so(self):
        _s, out = say(["SCAN:none 1|"])
        self.assertEqual(out, ["No items in sight."])


class TestQuietLines(unittest.TestCase):
    def test_jump_is_silent(self):
        _s, out = say(["SCAN:jump 17488|"])
        self.assertEqual(out, [])

    def test_furniture_survey_is_not_narration(self):
        _s, out = say(["SCAN:obj pid=1 fid=2 flags=3 ty=5 screen=1 vis=1 nm=Rock|"])
        self.assertEqual(out, [])


class TestRepeat(unittest.TestCase):
    def test_repeat_returns_the_last_entry(self):
        s, _ = say(["SCAN:entry 2|0|12|Torch|0|6|4|0|2|"])
        self.assertIn("Torch", s.repeat())

    def test_repeat_cleared_when_a_category_empties(self):
        s, _ = say(["SCAN:entry 2|0|12|Torch|0|6|4|0|2|", "SCAN:none 2|"])
        self.assertIsNone(s.repeat())


class TestNaming(unittest.TestCase):
    def test_six_hex_directions(self):
        self.assertEqual(direction_name(0), "north east")
        self.assertEqual(direction_name(4), "west")
        self.assertEqual(direction_name(5), "north west")

    def test_out_of_range_direction_claims_nothing(self):
        self.assertEqual(direction_name(9), "")

    def test_unknown_category_is_not_invented(self):
        self.assertEqual(category_name(99), "category 99")


if __name__ == "__main__":
    unittest.main()
