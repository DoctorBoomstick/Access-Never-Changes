"""Which window the mod sends its input to.

This is the failure that presented as "moving an item takes fifteen business
years". Run full screen, DirectX gives the game a second visible titled window
of its own -- `D3DProxyWindow`, covering the screen -- and parks the game's real
window off at -25600. `find_game_window` returned whichever `EnumWindows`
yielded first, which is Z-order, which is whichever happened to be on top.

Half the time that was the proxy. Keystrokes sent there reached nothing, aims
ground through their whole step count against a pointer that could not move, and
not one call errored. There is no way to tell that apart from the mod being slow
except by looking at the window class, which is what this now does.
"""

import unittest

from fallout2_access.input import send


class _FakeWindows:
    """Stands in for EnumWindows, so the two-window case can be expressed.

    A fake is right here: the case that matters is one this machine only enters
    when the game is full screen, and a test that needed that could never run
    in CI or on a machine with no game on it.
    """

    def __init__(self, windows):
        # windows: list of (hwnd, class, rect)
        self.windows = list(windows)

    def install(self, monkey):
        monkey(send, "game_windows", lambda pid: [w[0] for w in self.windows])
        monkey(send, "window_class",
               lambda h: next(w[1] for w in self.windows if w[0] == h))
        monkey(send, "window_rect",
               lambda h: next(w[2] for w in self.windows if w[0] == h))


GAME = (1837476, send.GAME_WINDOW_CLASS, (0, 0, 1024, 768))
PARKED_GAME = (1837476, send.GAME_WINDOW_CLASS, (-25600, -25600, -25441, -25573))
PROXY = (3870464, send.PROXY_WINDOW_CLASS, (0, 0, 1536, 864))


class _Patcher:
    def __init__(self):
        self.saved = []

    def __call__(self, obj, name, value):
        self.saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, value in reversed(self.saved):
            setattr(obj, name, value)


class WindowChoice(unittest.TestCase):
    def setUp(self):
        self.patch = _Patcher()
        self.addCleanup(self.patch.undo)

    def test_the_game_wins_whichever_order_they_come_in(self):
        """Z-order is exactly what must stop deciding this."""
        for order in ([PROXY, GAME], [GAME, PROXY]):
            with self.subTest(order=[w[1] for w in order]):
                _FakeWindows(order).install(self.patch)
                self.assertEqual(send.find_game_window(1), GAME[0])

    def test_the_proxy_is_never_chosen_even_when_it_is_all_there_is(self):
        """Having no window is a failure the mod reports. Having the proxy is a
        failure it cannot detect, which is strictly worse."""
        _FakeWindows([PROXY]).install(self.patch)
        self.assertIsNone(send.find_game_window(1))

    def test_an_unfamiliar_window_is_still_accepted(self):
        """Other builds and wrappers exist; this must not be a whitelist of
        one. Anything that is not the proxy beats nothing."""
        other = (999, "SomeOtherClass", (0, 0, 800, 600))
        _FakeWindows([PROXY, other]).install(self.patch)
        self.assertEqual(send.find_game_window(1), other[0])


class FullScreenComplaint(unittest.TestCase):
    def setUp(self):
        self.patch = _Patcher()
        self.addCleanup(self.patch.undo)

    def test_windowed_says_nothing(self):
        _FakeWindows([GAME]).install(self.patch)
        self.assertIsNone(send.fullscreen_complaint(GAME[0], 1))

    def test_a_parked_window_is_reported(self):
        """The real window sits at -25600 behind the proxy, and every aim is
        computed against it."""
        _FakeWindows([PROXY, PARKED_GAME]).install(self.patch)
        said = send.fullscreen_complaint(PARKED_GAME[0], 1)
        self.assertIsNotNone(said)
        self.assertIn("full screen", said)
        self.assertIn("Mode to 5", said)

    def test_the_proxy_existing_at_all_is_reported(self):
        """Even if the game's own window has not been parked yet."""
        _FakeWindows([PROXY, GAME]).install(self.patch)
        self.assertIsNotNone(send.fullscreen_complaint(GAME[0], 1))

    def test_no_window_at_all_is_reported(self):
        _FakeWindows([]).install(self.patch)
        said = send.fullscreen_complaint(None, 1)
        self.assertIsNotNone(said)
        self.assertIn("Mode to 5", said)

    def test_it_says_what_still_works(self):
        """Reading and speech are unaffected, and a player hearing "full
        screen" needs to know the mod has not simply died."""
        _FakeWindows([PROXY, PARKED_GAME]).install(self.patch)
        said = send.fullscreen_complaint(PARKED_GAME[0], 1)
        self.assertIn("still work", said)


if __name__ == "__main__":
    unittest.main()
