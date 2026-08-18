"""The keyboard is the mod's only entry point. Check it is actually connected.

`App.action` went missing during a refactor and nothing noticed. The listener
called a method that no longer existed, the AttributeError was swallowed by the
handler's "never let a hotkey kill the listener" guard, and the message went to
a console a blind player cannot read. Every key press did nothing at all,
without a sound, for several rounds of debugging.

Silence is this project's worst failure mode, and an exception caught for
robustness is a very effective way to produce it.
"""

import unittest

import f2access
from fallout2_access.app import App


class TestHotkeyWiring(unittest.TestCase):
    def test_app_has_the_entry_point_the_listener_calls(self):
        self.assertTrue(callable(getattr(App, "action", None)))

    def test_every_bound_key_reaches_something_real(self):
        """Each hotkey either is a click, or names a Watcher method."""
        from fallout2_access.app import Watcher

        for vk, what in f2access.HOTKEYS.items():
            with self.subTest(vk=vk, what=what):
                if what in ("click", "rclick"):
                    self.assertTrue(callable(getattr(App, "click", None)))
                else:
                    self.assertTrue(
                        callable(getattr(Watcher, what, None)),
                        "{!r} is bound to vk {} but no Watcher implements it"
                        .format(what, vk),
                    )

    def test_the_two_mouse_buttons_are_bound(self):
        self.assertEqual(f2access.HOTKEYS.get(107), "click")    # numpad +
        self.assertEqual(f2access.HOTKEYS.get(109), "rclick")   # numpad -

    def test_action_queues_rather_than_acting(self):
        """It runs on pynput's thread; doing the work there would interleave
        keystrokes with the main loop's own."""
        app = App.__new__(App)
        app._pending = []
        App.action(app, "click")
        self.assertEqual(len(app._pending), 1)
        self.assertEqual(app._pending[0][0], "click")

    def test_stale_actions_are_dropped(self):
        """A click that fires when focus comes back lands in a context the
        player moved on from."""
        import time

        app = App.__new__(App)
        app._pending = [("click", time.time() - 5.0)]
        done = []
        app._do_action = lambda what: done.append(what)
        App._run_pending(app)
        self.assertEqual(done, [])
        self.assertEqual(app._pending, [])


if __name__ == "__main__":
    unittest.main()
