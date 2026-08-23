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


class _RecordingWorld:
    """Just enough WorldWatcher for the dispatcher to talk to."""

    def __init__(self, talking=True):
        self.calls = []
        self._talking = talking

    def talking(self):
        return self._talking

    def dlg_step(self, ann, delta):
        self.calls.append(("dlg_step", delta))

    def dlg_say(self, ann):
        self.calls.append(("dlg_say",))


def _drive(what, talking=True):
    """Run one hotkey through the real dispatcher, and report what it did."""
    app = App.__new__(App)
    app.world = _RecordingWorld(talking)
    app.ann = None
    app.screen = "world"
    App._do_action(app, what)
    return app.world.calls


class TestHotkeyWiring(unittest.TestCase):
    def test_app_has_the_entry_point_the_listener_calls(self):
        self.assertTrue(callable(getattr(App, "action", None)))

    def test_every_bound_key_reaches_something_real(self):
        """Each hotkey is a click, names a Watcher method, or is dispatched.

        The third case is checked by *running* it rather than by looking up a
        name, because a name that exists is not the same claim as a key that
        does something -- and this test exists because of a key that did
        nothing, silently, for several rounds.
        """
        from fallout2_access.app import Watcher

        for vk, what in f2access.HOTKEYS.items():
            with self.subTest(vk=vk, what=what):
                if what in ("click", "rclick"):
                    self.assertTrue(callable(getattr(App, "click", None)))
                elif callable(getattr(Watcher, what, None)):
                    continue
                else:
                    self.assertTrue(
                        _drive(what),
                        "{!r} is bound to vk {} but reaches nothing: no "
                        "Watcher implements it and _do_action ignores it"
                        .format(what, vk),
                    )

    def test_the_reply_keys_belong_to_the_map_when_not_talking(self):
        """Numpad 8, 2 and 5 are the hex cursor's everywhere but a conversation.

        gl_dialog.ssl only swallows them while one is on screen, so out here
        the in-game script is acting on them and this side must not answer for
        them as well.
        """
        for what in ("dlg_prev", "dlg_next", "dlg_say"):
            with self.subTest(what=what):
                self.assertEqual(_drive(what, talking=False), [])

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


class TestLazyImportsResolve(unittest.TestCase):
    """Imports written inside a method still have to be right.

    `_skill_names` imported with two dots, as though it lived in a game
    submodule rather than in fallout2_access.app itself. Two dots reaches past
    the top of the package, so the first Skilldex line raised ImportError -- and
    because the loop caught only OSError, that ended the mod mid-game.

    Nothing in the suite touched it, because an import inside a function is not
    resolved until the function runs. So run it.
    """

    def test_skill_names_can_be_called(self):
        from fallout2_access.app import WorldWatcher
        from fallout2_access.game.worldlog import WorldLog

        w = WorldWatcher(WorldLog("nowhere.log"))

        class _Proc:
            directory = ""

            def read_chunked(self, addr, size):
                return None

            def read(self, addr, size):
                return None

            def read_i32(self, addr):
                return None

            def read_u32(self, addr):
                return None

        w.proc = _Proc()
        self.assertEqual(w._skill_names(), {},
                         "no names to be had, but it must not raise")


class TestTheLoopSurvivesABrokenTick(unittest.TestCase):
    """One bad log line must not end the session.

    The mod went completely dead mid-game because a handler raised something
    that was not OSError. Everything else it does was still working; the loop
    simply stopped running.
    """

    def test_a_non_oserror_is_caught_and_reported(self):
        import io
        import contextlib
        from fallout2_access.app import App, Announcer

        class _Speaker:
            def __init__(self):
                self.said = []

            def speak(self, text, interrupt=False):
                self.said.append(text)

        app = App.__new__(App)
        speaker = _Speaker()
        app.ann = Announcer(speaker)
        app._last_fault = None
        app.require_focus = False
        app.proc = object()
        calls = []

        def boom():
            calls.append(1)
            if len(calls) > 2:
                raise SystemExit           # stop the loop from the inside
            raise ImportError("the exact shape of the Skilldex fault")

        app.tick = boom
        app._connected = lambda: True
        app._active = lambda: True

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                app.run()

        self.assertGreater(len(calls), 2, "the loop stopped at the first fault")
        self.assertIn("tick failed", buf.getvalue())
        self.assertEqual(len(speaker.said), 1,
                         "a repeating fault must be spoken once, not per tick")


class TestKeyReleaseIsSwallowedToo(unittest.TestCase):
    """A key the script takes must be taken on the way up as well.

    gl_world.ssl dropped every key-up and acted only on the press, which hides
    half an event: the press is taken away and the release still reaches the
    engine. Numpad 1 is bound to south-west, the engine reads a numpad digit as
    the character '1', and on the map '1' toggles sneak -- so walking the look
    cursor south-west turned stealth on and off, about half the time.

    Checked by reading the script, because the behaviour lives inside the game
    and the only other way to see it is to play. gl_dialog.ssl has swallowed
    both events since it was written and says why in its own comments; this is
    the file that did not.
    """

    def script(self):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "scripts", "gl_world.ssl"),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_the_release_is_no_longer_dropped_on_arrival(self):
        """`if (event != 1) then return;` at the top of on_key is the bug."""
        self.assertNotIn("if (event != 1) then return;", self.script())

    def test_the_dispatch_swallows_a_release_it_owns(self):
        """The dispatch, specifically. The Skilldex digits also test the
        release and deliberately do NOT swallow -- the game still needs them to
        arm the skill -- so anchoring on the first match tests the wrong one."""
        src = self.script()
        anchor = "The key is ours. Swallow the release"
        self.assertIn(anchor, src)
        after = src[src.index(anchor):]
        self.assertIn("set_sfall_return(KEY_SWALLOW)", after[:400])

    def test_the_skilldex_digits_are_still_let_through(self):
        """1 to 8 arm a skill and the engine has to see them. Swallowing those
        would break the Skilldex to fix the numpad."""
        src = self.script()
        head = src[src.index("if (key == DIK_1) then begin g_armedskill"):]
        self.assertNotIn("set_sfall_return", head[:200])

    def test_actions_are_held_back_on_the_release(self):
        """The menu and target list navigate on the press only, or one press
        would step the list twice."""
        src = self.script()
        for action in ("call pick_step(-1)", "call menu_step(-1)",
                       "call calibrate", "call report_status"):
            self.assertIn("if (pressed) then " + action, src,
                          "{} still runs on the release".format(action))


class TestSwallowIsNotZero(unittest.TestCase):
    """Taking a key away from the engine.

    sfall's documentation for HOOK_KEYPRESS could not be plainer:

        int ret0 - overrides the pressed key
                   (a new key DX scancode or 0 for no override)

    So `set_sfall_return(0)` means leave the key alone. Every script here used
    it to mean the opposite, and had done since the first one was written, so
    nothing was ever actually swallowed -- which is one cause behind three
    separate bugs: numpad 1 toggling sneak while stepping the look cursor, the
    numpad picking dialogue replies, and the numpad scrolling the map beneath
    the action menu.
    """

    def scripts(self):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = {}
        for name in ("gl_world", "gl_dialog", "gl_inven"):
            with open(os.path.join(here, "scripts", name + ".ssl"),
                      encoding="utf-8") as fh:
                out[name] = fh.read()
        return out

    def test_no_script_returns_zero_to_mean_swallow(self):
        for name, src in self.scripts().items():
            self.assertNotIn("set_sfall_return(0)", src,
                             "{} still asks the engine for no override".format(name))

    def test_every_script_swallows_with_the_named_constant(self):
        for name, src in self.scripts().items():
            self.assertIn("#define KEY_SWALLOW", src, name)
            self.assertIn("set_sfall_return(KEY_SWALLOW)", src, name)

    def test_the_override_is_a_key_the_game_ignores(self):
        """It has to be a real scancode -- there is no documented block value --
        and one Fallout does nothing with. Scroll Lock is bound to nothing in
        the game and to nothing in ddraw.ini."""
        for name, src in self.scripts().items():
            self.assertIn("#define KEY_SWALLOW  (DIK_SCROLL)", src, name)

    def test_no_script_drops_the_release(self):
        """The documentation adds that the override must be the same scancode
        for press and release, so a handler that returns early on key-up hides
        half an event."""
        for name, src in self.scripts().items():
            self.assertNotIn("if (event != 1) then return;", src, name)
