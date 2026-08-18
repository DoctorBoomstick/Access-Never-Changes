"""The scanner's narration."""

import unittest

from fallout2_access.game.scanner import Scanner, category_name, direction_name


def say(lines):
    s = Scanner()
    out = []
    for line in lines:
        out.extend(s.handle(line))
    return s, out


class TestScannerNarration(unittest.TestCase):
    def test_entry_reads_name_bearing_distance_and_position(self):
        _s, out = say(["SCAN:entry 0|0|3|Giant Ant|4|0|0|"])
        self.assertEqual(out, ["Giant Ant, north east 4 hexes, 1 of 3."])

    def test_category_is_announced_only_when_it_changed(self):
        _s, out = say([
            "SCAN:entry 0|0|3|Giant Ant|4|0|1|",   # category switch
            "SCAN:entry 0|1|3|Radscorpion|7|2|0|", # stepping within it
        ])
        self.assertTrue(out[0].startswith("Critters. "))
        self.assertFalse(out[1].startswith("Critters"))

    def test_singular_hex(self):
        _s, out = say(["SCAN:entry 1|0|1|Knife|1|4|0|"])
        self.assertIn("west 1 hex,", out[0])

    def test_distance_zero_is_here_not_zero_hexes(self):
        _s, out = say(["SCAN:entry 1|0|1|Knife|0|0|0|"])
        self.assertIn("here", out[0])
        self.assertNotIn("0 hex", out[0])

    def test_empty_category_says_so(self):
        _s, out = say(["SCAN:none 2|"])
        self.assertEqual(out, ["No scenery in sight."])

    def test_names_with_spaces_survive(self):
        _s, out = say(["SCAN:entry 2|0|1|Block Hex Auto Inviso|2|1|0|"])
        self.assertIn("Block Hex Auto Inviso", out[0])

    def test_engine_noise_after_the_terminator_is_discarded(self):
        _s, out = say(["SCAN:entry 0|0|1|Giant Ant|4|0|0|sequencing attack..."])
        self.assertEqual(out, ["Giant Ant, north east 4 hexes, 1 of 1."])

    def test_jump_is_silent(self):
        """The hex readout that follows a jump says what is there, from the
        game's own object names. Saying it twice helps nobody."""
        _s, out = say(["SCAN:jump 17488|"])
        self.assertEqual(out, [])

    def test_survey_lines_are_not_narration(self):
        _s, out = say(["SCAN:obj pid=1 fid=2 flags=3 ty=5 screen=1 vis=1 nm=Rock|"])
        self.assertEqual(out, [])

    def test_repeat_returns_the_last_entry(self):
        s, _ = say(["SCAN:entry 0|0|2|Giant Ant|4|0|0|"])
        self.assertEqual(s.repeat(), "Giant Ant, north east 4 hexes, 1 of 2.")

    def test_repeat_is_cleared_when_a_category_empties(self):
        s, _ = say(["SCAN:entry 0|0|2|Giant Ant|4|0|0|", "SCAN:none 0|"])
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
