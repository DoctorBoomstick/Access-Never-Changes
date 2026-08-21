"""Setting the explosive countdown.

The value here is CAUSED, never read -- the search for a readable one found the
executable's globals empty and then a heap word that turned out to be a tally of
clicks, rising on both buttons. So these tests are about the arithmetic staying
honest and about refusing when it cannot be.
"""

import unittest

from fallout2_access.game import timerwin
from fallout2_access.game.timerwin import Timer, say_time, seconds


class FakeFinder:
    def __init__(self, win=None):
        self.win = win

    def sized(self, w, h):
        return self.win


class FakeButton:
    def __init__(self, press):
        self.press = press

    def centre(self, _win):
        return (0, 0)


class FakeWindow:
    def __init__(self, codes):
        self.codes = codes

    def by_press(self, code):
        return FakeButton(code) if code in self.codes else None


class Driven(Timer):
    """A Timer whose clicks are recorded instead of sent."""

    def __init__(self, win=None, works=True):
        Timer.__init__(self, None, None, FakeFinder(win))
        self.sent = []
        self.works = works

    def _click(self, code, times=1):
        if not self.works:
            return False
        self.sent.append((code, times))
        return True


PANEL = FakeWindow({timerwin.STEP_UP, timerwin.STEP_DOWN})


class TestWords(unittest.TestCase):
    def test_seconds_below_a_minute(self):
        self.assertEqual(say_time(1), "10 seconds")
        self.assertEqual(say_time(5), "50 seconds")

    def test_a_whole_minute_drops_the_seconds(self):
        self.assertEqual(say_time(6), "1 minute")
        self.assertEqual(say_time(12), "2 minutes")

    def test_minutes_and_seconds_together(self):
        """"One hundred and twenty seconds" is a number you have to convert
        while a charge is live."""
        self.assertEqual(say_time(9), "1 minute 30 seconds")
        self.assertEqual(say_time(18), "3 minutes")

    def test_the_range_matches_the_game(self):
        self.assertEqual(seconds(timerwin.MIN_STEPS), 10)
        self.assertEqual(seconds(timerwin.MAX_STEPS), 180)


class TestRewind(unittest.TestCase):
    def test_it_presses_down_more_than_the_range_is_long(self):
        """That is what makes the minimum certain from any starting value."""
        t = Driven(PANEL)
        self.assertTrue(t.rewind())
        self.assertEqual(t.sent, [(timerwin.STEP_DOWN, timerwin.REWIND_PRESSES)])
        self.assertGreater(timerwin.REWIND_PRESSES, timerwin.MAX_STEPS)

    def test_it_lands_on_the_minimum(self):
        t = Driven(PANEL)
        t.rewind()
        self.assertEqual(t.steps, timerwin.MIN_STEPS)

    def test_a_failed_rewind_leaves_the_value_unknown(self):
        """Not zero, not the minimum: unknown. A countdown nobody verified is
        the one number here that must never be announced confidently."""
        t = Driven(PANEL, works=False)
        self.assertFalse(t.rewind())
        self.assertIsNone(t.steps)


class TestStep(unittest.TestCase):
    def setUp(self):
        self.t = Driven(PANEL)
        self.t.rewind()
        self.t.sent = []

    def test_stepping_up_sends_that_many_presses(self):
        self.assertEqual(self.t.step(3), 4)
        self.assertEqual(self.t.sent, [(timerwin.STEP_UP, 3)])

    def test_stepping_back_down(self):
        self.t.step(5)
        self.t.sent = []
        self.assertEqual(self.t.step(-2), 4)
        self.assertEqual(self.t.sent, [(timerwin.STEP_DOWN, 2)])

    def test_it_clamps_to_the_games_range(self):
        self.assertEqual(self.t.step(100), timerwin.MAX_STEPS)
        self.assertEqual(self.t.step(-100), timerwin.MIN_STEPS)

    def test_at_an_end_it_sends_nothing(self):
        """The engine clamps too, so extra presses are harmless -- but sending
        them would make the count and the window disagree if it did not."""
        self.t.step(-5)
        self.t.sent = []
        self.assertEqual(self.t.step(-1), timerwin.MIN_STEPS)
        self.assertEqual(self.t.sent, [])

    def test_an_unknown_value_refuses_to_move(self):
        t = Driven(PANEL)
        self.assertIsNone(t.step(1))
        self.assertEqual(t.sent, [])

    def test_a_failed_click_makes_the_value_unknown_again(self):
        """Half a move is worse than none: the window has changed by some
        amount nobody knows."""
        self.t.works = False
        self.assertIsNone(self.t.step(2))
        self.assertIsNone(self.t.steps)


class TestFind(unittest.TestCase):
    def test_the_panel_is_identified_by_its_step_buttons(self):
        self.assertIsNotNone(timerwin.find(FakeFinder(PANEL)))

    def test_a_window_of_the_same_size_without_them_is_not_it(self):
        """COUNTERWIN also moves a stack of items. Setting a countdown when you
        meant to split a pile is not a mistake worth risking on size alone."""
        self.assertIsNone(timerwin.find(FakeFinder(FakeWindow({500, 501}))))

    def test_no_window_at_all(self):
        self.assertIsNone(timerwin.find(FakeFinder(None)))


if __name__ == "__main__":
    unittest.main()
