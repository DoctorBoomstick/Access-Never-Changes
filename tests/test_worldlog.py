"""Parsing the in-game script's output.

debug.log is the only channel the engine gives a script for getting text out, so
everything the mod knows about the live world arrives as lines in this file --
and the engine writes its own debug output into the same file, sometimes without
a newline. These tests use real captured lines, noise included.
"""

import os
import tempfile
import unittest

from fallout2_access.game import worldlog
from fallout2_access.game.worldlog import WorldLog


class LogFixture:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "debug.log")
        open(self.path, "w").close()
        self.log = WorldLog(self.path)

    def write(self, *lines):
        with open(self.path, "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        return self.log.poll()

    def truncate(self):
        open(self.path, "w").close()


class TestWorldLog(unittest.TestCase):
    def setUp(self):
        self.f = LogFixture()

    def test_hex_reading(self):
        self.f.write("WORLD:hex 17488 dist 0 : you|")
        self.assertEqual(self.f.log.last_hex.tile, 17488)
        self.assertEqual(self.f.log.last_hex.contents, "you")
        self.assertEqual(self.f.log.last_hex.announce(), "you")

    def test_distance_is_pluralised(self):
        self.f.write("WORLD:hex 17687 dist 1 : empty|")
        self.assertEqual(self.f.log.last_hex.announce(), "empty, 1 hex")
        self.f.write("WORLD:hex 17686 dist 2 : Tree|")
        self.assertEqual(self.f.log.last_hex.announce(), "Tree, 2 hexes")

    def test_engine_noise_after_the_terminator_is_discarded(self):
        """Captured verbatim: the engine appended its own line to ours."""
        self.f.write("WORLD:hex 25911 dist 1 : Giant Ant|sequencing attack...")
        self.assertEqual(self.f.log.last_hex.contents, "Giant Ant")

    def test_cursorok_reports_the_mode_too(self):
        """Only parsing `cursormode` left the mode unknown exactly when nothing
        had changed -- which is the common case, and the one the click path
        needs an answer for."""
        self.f.write("WORLD:cursorok 2|")
        self.assertEqual(self.f.log.cursor_mode, 2)
        self.f.write("WORLD:cursormode 0|")
        self.assertEqual(self.f.log.cursor_mode, 0)

    def test_game_mode_and_session_liveness(self):
        self.assertFalse(self.f.log.session_live)
        self.f.write("WORLD:ready")
        self.assertTrue(self.f.log.session_live)
        self.f.write("WORLD:gamemode 64")
        self.assertEqual(self.f.log.game_mode, 64)

    def test_combat_lines_are_passed_through(self):
        out = self.f.write("COMBAT:turn 1|you|")
        self.assertEqual(out, ["COMBAT:turn 1|you|"])

    def test_combat_ready_marks_the_session_live(self):
        self.f.write("COMBAT:ready|")
        self.assertTrue(self.f.log.session_live)

    def test_relaunch_resets_everything(self):
        """The game truncates debug.log on launch, so a shrinking file means a
        new session and every remembered fact belongs to a dead one."""
        self.f.write("WORLD:ready", "WORLD:gamemode 0", "WORLD:hex 1 dist 0 : you|")
        self.assertTrue(self.f.log.session_live)
        self.f.truncate()
        self.f.write("WORLD:hex 2 dist 0 : you|")
        self.assertEqual(self.f.log.last_hex.tile, 2)

    def test_missing_file_is_survivable(self):
        log = WorldLog(os.path.join(self.f.dir, "nope.log"))
        self.assertEqual(log.poll(), [])

    def _pumped(self, *lines):
        """Feed lines and let a WorldWatcher consume them.

        Written straight to the file rather than through the fixture, because
        the fixture polls as it writes and would eat the line first.
        """
        from fallout2_access.app import WorldWatcher

        w = WorldWatcher(self.f.log)
        with open(self.f.path, "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        w.pump()
        return w

    def test_arrive_distance_drops_the_terminator(self):
        """Heard as "Moved 2| hexes." -- the line gained a trailing separator
        to keep engine noise out, and the parse took the bar with the number."""
        w = self._pumped("WORLD:arrive 17686 dist 2|")
        self.assertEqual([t for t, _u in w._queue], ["Moved 2 hexes."])

    def test_prepare_lines_are_not_spoken(self):
        """Heard as "prepare 6|". It is the click setting its own cursor."""
        w = self._pumped("WORLD:prepare 6|Door, locked|")
        self.assertEqual(w._queue, [])

    def test_unrelated_lines_are_ignored(self):
        out = self.f.write("Gsound: playing ambient map sfx: animal1")
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()


class TestStatusLine(unittest.TestCase):
    """Health, action points and armour class -- the three numbers a sighted
    player reads off the interface bar without pressing anything."""

    def test_order_is_health_then_action_points_then_armour(self):
        said = worldlog.status_line("WORLD:status 48|48|8|10|8|1|")
        self.assertLess(said.index("Health"), said.index("action"))
        self.assertLess(said.index("action"), said.index("Armor"))

    def test_in_combat_action_points_are_a_remainder(self):
        said = worldlog.status_line("WORLD:status 31|48|3|10|8|1|")
        self.assertIn("3 of 10 action points", said)

    def test_out_of_combat_action_points_are_a_capacity(self):
        """The engine keeps a running count outside a fight, but it is not a
        number anyone is spending -- reporting it as a remainder would be true
        of nothing."""
        said = worldlog.status_line("WORLD:status 31|48|3|10|8|0|")
        self.assertIn("10 action points", said)
        self.assertNotIn("3 of", said)

    def test_damage_shows_in_the_health_figure(self):
        self.assertIn("Health 31 of 48",
                      worldlog.status_line("WORLD:status 31|48|0|10|8|0|"))

    def test_an_unparsable_line_is_not_spoken(self):
        self.assertIsNone(worldlog.status_line("WORLD:status garbage"))
        self.assertIsNone(worldlog.status_line("WORLD:hex 17488 dist 0 : you|"))


class TestUseItemLine(unittest.TestCase):
    """Using the item in your hand on the thing the look cursor is on.

    The one action the engine's menu offered that nothing else could reach:
    walking, attacking, using an object and using a skill are all cursor modes,
    and "use an ITEM on that" is not.
    """

    def say(self, line):
        return worldlog.use_item_line(line)

    def test_the_attempt_names_both_halves(self):
        self.assertEqual(
            self.say("WORLD:useitem try Plastic Explosives|Impenetrable Door|"),
            "Using Plastic Explosives on Impenetrable Door.")

    def test_empty_hands_say_what_to_do_about_it(self):
        """A refusal that does not say how to proceed is a dead end to someone
        who cannot see the hand slots."""
        text = self.say("WORLD:useitem empty|")
        self.assertIn("empty", text)
        self.assertIn("Ready an item", text)

    def test_nothing_to_use_it_on(self):
        self.assertEqual(self.say("WORLD:useitem notarget 14322|"),
                         "Nothing there to use it on.")

    def test_finishing_says_nothing_and_that_is_deliberate(self):
        """The engine runs the object's own handler and reports the outcome in
        its own words through the display window, which the mod already reads.
        A verdict invented here would talk over the one voice that knows."""
        self.assertIsNone(
            self.say("WORLD:useitem done Plastic Explosives|Impenetrable Door|"))

    def test_an_unknown_outcome_is_silent_rather_than_raw(self):
        self.assertIsNone(self.say("WORLD:useitem wat|"))

    def test_a_line_that_is_not_ours_is_ignored(self):
        self.assertIsNone(self.say("WORLD:hex 14322 dist 1 : Door|"))


class TestUseObjLine(unittest.TestCase):
    """"Use it" -- the hand icon.

    Nothing could reach this before: the mod only ever selects the movement or
    targeting cursor, so a click on a door walked into it rather than opening
    it, and opening one needs the command cursor the mod never picks.
    """

    def test_the_attempt_names_the_target(self):
        self.assertEqual(
            worldlog.use_obj_line("WORLD:useobj try Impenetrable Door|"),
            "Using Impenetrable Door.")

    def test_nothing_there(self):
        self.assertEqual(worldlog.use_obj_line("WORLD:useobj notarget 14322|"),
                         "Nothing there to use.")

    def test_finishing_leaves_the_verdict_to_the_game(self):
        self.assertIsNone(
            worldlog.use_obj_line("WORLD:useobj done Impenetrable Door|"))
