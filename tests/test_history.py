"""The message log: what the game said, kept to be read again."""

import unittest

from fallout2_access.game import history
from fallout2_access.game.history import History


class Browsing(unittest.TestCase):
    def setUp(self):
        self.h = History()
        for line in ("You see: a locker.", "It's locked.", "Torr: Bugs dead."):
            self.h.add(line)

    def test_older_starts_from_the_newest(self):
        self.assertEqual(self.h.older(), "Torr: Bugs dead.")
        self.assertEqual(self.h.older(), "It's locked.")

    def test_the_oldest_says_so_and_is_said_again(self):
        for _ in range(3):
            self.h.older()
        self.assertEqual(self.h.older(), "Oldest. You see: a locker.")

    def test_newer_walks_back_and_off_the_end(self):
        self.h.older()
        self.h.older()
        self.assertEqual(self.h.newer(), "Torr: Bugs dead.")
        self.assertEqual(self.h.newer(), "Newest. Torr: Bugs dead.")
        # Off the end, the next older press starts again from the newest.
        self.assertEqual(self.h.older(), "Torr: Bugs dead.")

    def test_something_new_does_not_move_you(self):
        self.h.older()
        self.h.older()
        self.h.add("You hit the rat for 4 hit points.")
        self.assertEqual(self.h.older(), "You see: a locker.")

    def test_empty(self):
        h = History()
        self.assertEqual(h.older(), "Nothing has been said yet.")
        self.assertEqual(h.newer(), "Nothing has been said yet.")

    def test_blank_lines_are_not_kept(self):
        h = History()
        h.add("   ")
        h.add("")
        self.assertEqual(h.lines, [])


class Capacity(unittest.TestCase):
    def test_the_oldest_go_first(self):
        h = History(capacity=3)
        for n in range(5):
            h.add(str(n))
        self.assertEqual(h.lines, ["2", "3", "4"])

    def test_a_reader_among_the_dropped_stays_at_the_oldest(self):
        h = History(capacity=3)
        for n in range(3):
            h.add(str(n))
        for _ in range(3):
            h.older()           # on "0"
        h.add("3")
        h.add("4")
        self.assertEqual(h.newer(), "3")


class TheKeys(unittest.TestCase):
    def test_shift_comma_and_period(self):
        import f2access
        self.assertEqual(f2access.hotkey_for(188, True), "log_prev")
        self.assertEqual(f2access.hotkey_for(190, True), "log_next")
        # Unshifted they are the game's: they turn you.
        self.assertIsNone(f2access.hotkey_for(188, False))

    def test_shift_and_a_digit_is_not_a_digit(self):
        """Shift and 1 is the light level. The "how many" window must not take
        it for a 1."""
        import f2access
        self.assertEqual(f2access.hotkey_for(49, False), "digit1")
        self.assertIsNone(f2access.hotkey_for(49, True))

    def test_they_reach_the_log_on_any_screen(self):
        from fallout2_access.app import App

        class _Said:
            last = ""

            def answer(self, text):
                self.last = text

        app = App.__new__(App)
        app.ann = _Said()
        app.history = History()
        app.history.add("It's locked.")
        app.screen = None
        app._do_action("log_prev")
        self.assertEqual(app.ann.last, "It's locked.")


if __name__ == "__main__":
    unittest.main()
