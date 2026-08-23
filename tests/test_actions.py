"""Reading the engine's action list out of memory.

The list is never empty between menus -- it holds whatever was last built -- so
the failure mode here is a confident answer about the wrong object. Everything
below is about not doing that.
"""

import struct
import unittest

from . import fakes

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


class TestHighlight(unittest.TestCase):
    """Which icon the engine has lit, which is what a release will perform."""

    def test_it_is_read_as_a_word_not_a_dword(self):
        """The top half of that dword belongs to something else.

        Measured live: with icon 0 lit, the dword reads 16580608, and it
        increments convincingly as the pointer moves -- 16580609, 16580610.
        A reader that took the dword would walk a menu of five icons looking
        for index 1 and never find it, having been handed a number that looks
        like it is working.
        """
        mem = fakes.FakeMemory()
        mem.poke(actions.MENU_INDEX, struct.pack("<i", 0x00FD0002))
        self.assertEqual(actions.highlighted(mem), 2)

    def test_unreadable_is_none_rather_than_zero(self):
        # Zero is a real icon. "I cannot tell" must not read as "the first one".
        self.assertIsNone(actions.highlighted(fakes.FakeMemory()))


class TestMenuHandoff(unittest.TestCase):
    """The line the script sends when it cannot carry an action out itself.

    A hand-off that fails to parse does nothing at all, and says nothing about
    it -- the failure this project keeps having to design against. `App.action`
    went missing once and cost several rounds of debugging for exactly this
    reason, so the parse gets a test rather than a hope.
    """

    def _run(self, line):
        from fallout2_access.app import App
        from fallout2_access.game import actions as actions_module

        got = {}

        class _World:
            pending_menu_action = line

        app = App.__new__(App)
        app.world = _World()
        app.proc = object()
        app.hwnd = 1
        app.aimer = object()
        app.ann = type("A", (), {"answer": lambda self, text: got.setdefault(
            "said", []).append(text) or None})()
        got["said"] = []

        real = actions_module.perform
        actions_module.perform = lambda *a, **k: (
            got.setdefault("call", (a, k)) or (True, ""))
        try:
            App._run_menu_action(app)
        finally:
            actions_module.perform = real
        return got

    def test_it_reaches_the_engine_with_the_right_action(self):
        got = self._run("WORLD:menudo 3|Klint|")
        self.assertIn("call", got)
        self.assertEqual(got["call"][0][3], actions.LOOK)
        self.assertEqual(got["call"][1].get("wanted"), "Klint")

    def test_it_names_what_it_is_about_to_do(self):
        # Driving the menu takes seconds, and silence for seconds after a
        # keypress reads as the key never having arrived.
        got = self._run("WORLD:menudo 5|Klint|")
        self.assertTrue(got["said"])
        self.assertIn("Klint", got["said"][0])

    def test_a_line_it_cannot_parse_does_not_reach_the_engine(self):
        # Better to do nothing than to drive the pointer for an action nobody
        # asked for.
        for line in ("WORLD:menudo|", "WORLD:menudo x|Klint|", "WORLD:menudo"):
            with self.subTest(line=line):
                self.assertNotIn("call", self._run(line))


class TestStepToward(unittest.TestCase):
    def test_it_goes_down_to_reach_a_later_icon(self):
        # Down increases the index -- measured, not assumed. Backwards here
        # walks the highlight to the far end and performs whatever sits there.
        self.assertEqual(actions.step_toward(0, 3), 1)

    def test_it_goes_up_to_reach_an_earlier_one(self):
        self.assertEqual(actions.step_toward(4, 1), -1)

    def test_arriving_means_stop(self):
        self.assertEqual(actions.step_toward(2, 2), 0)


if __name__ == "__main__":
    unittest.main()
