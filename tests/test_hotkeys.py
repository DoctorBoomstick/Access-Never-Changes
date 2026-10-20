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
from fallout2_access import controls
from fallout2_access.app import App, QuantityWatcher
from fallout2_access.game import screens


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


def _subclasses(cls):
    """Every subclass of `cls`, however deep."""
    found = []
    for sub in cls.__subclasses__():
        found.append(sub)
        found.extend(_subclasses(sub))
    return found


class _RecordingBarter:
    """Stands in for the barter module, so pressing OFFER is observable.

    The real one aims a pointer at a button on a live game. What this test
    needs to know is only that the key reaches it at all -- which is the thing
    that went missing once and cost a debugging session, and which no amount of
    reading the dispatcher proves.
    """

    def __init__(self, calls):
        self.calls = calls

    def offering(self, _proc):
        return True

    def offer(self, _proc, _hwnd, log_path=None):
        self.calls.append(("offer",))
        return True, ""


class _RecordingCounter(QuantityWatcher):
    """A QuantityWatcher, keys and all, that records instead of typing."""

    def __init__(self, calls):
        self.calls = calls

    def step(self, _ann, delta):
        self.calls.append(("count", delta * self.big))

    def fewest(self, _ann):
        self.calls.append(("fewest",))

    def take_all(self, _ann):
        self.calls.append(("take all",))

    def cancel(self, _ann):
        self.calls.append(("cancel",))

    def digit(self, _ann, d):
        self.calls.append(("digit", d))

    def repeat(self, _ann):
        self.calls.append(("repeat",))


class _Silent:
    """An Announcer that says nothing anybody has to listen to."""

    def answer(self, _text):
        pass

    def say(self, _text, **_kw):
        pass


def _drive(what, talking=True, screen="world"):
    """Run one hotkey through the real dispatcher, and report what it did."""
    from fallout2_access import app as app_module

    app = App.__new__(App)
    app.world = _RecordingWorld(talking)
    app.ann = _Silent()
    app.screen = screen
    app.watchers = {"quantity": _RecordingCounter(app.world.calls)}
    # Enough of an attached game for the guarded branches to run.
    app.proc = object()
    app.hwnd = 1
    real = app_module.barter
    app_module.barter = _RecordingBarter(app.world.calls)
    try:
        App._do_action(app, what)
    finally:
        app_module.barter = real
    return app.world.calls


class TestTypingAnAmount(unittest.TestCase):
    """Sixty caps used to be sixty presses of up."""

    def test_digits_go_to_the_how_many_window(self):
        self.assertEqual(_drive("digit6", screen=screens.QUANTITY),
                         [("digit", 6)])

    def test_digits_are_left_to_the_game_everywhere_else(self):
        """Reply numbers in a conversation, skills on the map."""
        self.assertEqual(_drive("digit6", screen="world"), [])

    def test_control_steps_by_ten(self):
        from fallout2_access import app as app_module

        app = App.__new__(App)
        app.world = _RecordingWorld(True)
        app.ann = _Silent()
        app.screen = screens.QUANTITY
        app.watchers = {"quantity": _RecordingCounter(app.world.calls)}
        app.proc, app.hwnd, app.ctrl_held = object(), 1, True
        App._do_action(app, "dlg_prev")
        self.assertEqual(app.world.calls, [("count", 10)])


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

        # Every watcher, not just the base class. The base names the five
        # actions every screen answers to; a screen with keys of its own puts
        # them on its own subclass, which is where the world map's cursor and
        # scanner live. Looking only at the base was right until one did.
        watchers = [Watcher] + _subclasses(Watcher)

        for vk, what in f2access.HOTKEYS.items():
            with self.subTest(vk=vk, what=what):
                if what in ("click", "rclick"):
                    self.assertTrue(callable(getattr(App, "click", None)))
                elif what.startswith("digit"):
                    # The number row means something in one window only.
                    self.assertTrue(_drive(what, screen=screens.QUANTITY))
                elif any(callable(getattr(w, what, None)) for w in watchers):
                    continue
                elif any(controls.find(w, what) for w in watchers):
                    # Bound in some screen's table, which tests/test_controls
                    # checks against the method it names.
                    continue
                elif what == "help":
                    self.assertTrue(callable(getattr(App, "help", None)))
                else:
                    self.assertTrue(
                        _drive(what),
                        "{!r} is bound to vk {} but reaches nothing: no "
                        "Watcher implements it and _do_action ignores it"
                        .format(what, vk),
                    )

    def test_the_move_items_window_gets_the_keys_before_the_conversation(self):
        """The bug that made bartering impossible.

        The barter screen is a conversation's child, so a stack dragged onto a
        table puts the "How many?" window up with DIALOG still set. Up and down
        arrive under the dialogue names -- that is what they are everywhere
        else -- and the dialogue branch answered for them first: either walking
        a reply list nobody could see or, when the mod judged the conversation
        not to be the thing on screen, returning without a sound. The mod
        announced the window, named the keys, and then swallowed every one of
        them.

        Checked with `talking` BOTH ways, because only one of the two failed
        loudly and the quiet one is the one that shipped.
        """
        for talking in (True, False):
            for what, expected in (("dlg_prev", ("count", 1)),
                                   ("dlg_next", ("count", -1)),
                                   ("num8", ("count", 1)),
                                   ("num2", ("count", -1)),
                                   ("end", ("take all",)),
                                   ("home", ("fewest",)),
                                   ("click", None),
                                   ("rclick", None),
                                   ("dlg_say", ("repeat",))):
                with self.subTest(what=what, talking=talking):
                    self.assertEqual(
                        _drive(what, talking=talking, screen="quantity"),
                        [expected] if expected else [])

    def test_nothing_else_reaches_past_that_window(self):
        """It is a modal loop of the engine's own with the barter behind it.

        `o` is the OFFER button, and offering a trade through a half-answered
        question about how many stimpaks to put on the table is not a thing to
        leave possible.
        """
        for what in ("barter_offer", "wm_town", "wm_scan_next"):
            with self.subTest(what=what):
                self.assertEqual(_drive(what, screen="quantity"), [])

    def test_the_reply_keys_belong_to_the_map_when_not_talking(self):
        """Numpad 8, 2 and 5 are the hex cursor's everywhere but a conversation.

        gl_dialog.ssl only swallows them while one is on screen, so out here
        the in-game script is acting on them and this side must not answer for
        them as well.
        """
        for what in ("dlg_prev", "dlg_next", "dlg_say"):
            with self.subTest(what=what):
                self.assertEqual(_drive(what, talking=False), [])

    def test_a_special_key_still_yields_its_virtual_key(self):
        """The bug that made the reply keys dead for everyone.

        pynput hands the listener two shapes. An ordinary key arrives as a
        `KeyCode`, which has a `vk`. Anything pynput recognises as special --
        every arrow, and the whole numpad once Num Lock is off -- arrives as a
        `Key` enum member, which does not: its virtual key is one level down in
        `Key.up.value.vk`. The listener read `key.vk`, got None, and dropped
        the press before any dialogue code ran.

        Driven with the real pynput objects rather than fakes. A fake with a
        `vk` attribute would pass this test and prove nothing, and a stand-in
        for the thing that was misunderstood is no test at all.
        """
        try:
            from pynput import keyboard
        except ImportError:
            self.skipTest("pynput not installed")

        self.assertIsNone(getattr(keyboard.Key.up, "vk", None),
                          "if this ever gains a vk, the bug is gone and so is "
                          "the reason for key_vk -- but check before deleting")
        self.assertEqual(f2access.key_vk(keyboard.Key.up), 38)
        self.assertEqual(f2access.key_vk(keyboard.Key.down), 40)
        self.assertEqual(f2access.key_vk(keyboard.KeyCode.from_vk(104)), 104)

    def test_every_bound_key_can_be_resolved_from_pynput(self):
        """Each binding, from the key pynput would actually deliver.

        This is the end-to-end version: for every vk in the table, build the
        object pynput builds for it and check the listener would find the
        binding again.
        """
        try:
            from pynput import keyboard
        except ImportError:
            self.skipTest("pynput not installed")

        # Every Key enum member, by the virtual key it carries.
        special = {}
        for name in dir(keyboard.Key):
            member = getattr(keyboard.Key, name)
            vk = getattr(getattr(member, "value", None), "vk", None)
            if vk is not None:
                special.setdefault(vk, member)

        for vk, what in f2access.HOTKEYS.items():
            with self.subTest(vk=vk, what=what):
                key = special.get(vk) or keyboard.KeyCode.from_vk(vk)
                self.assertEqual(f2access.HOTKEYS.get(f2access.key_vk(key)),
                                 what)

    def test_an_unknown_key_is_still_ignored_quietly(self):
        self.assertIsNone(f2access.key_vk(object()))

    def test_the_reply_keys_survive_num_lock(self):
        """Each reply key is bound to both virtual keys its numpad key sends.

        The three reply keys are the mod's only hotkeys read as Windows virtual
        keys rather than as DirectInput scancodes inside the game, and a
        virtual key is what Num Lock changes: with the lock off, numpad 8, 2
        and 5 arrive as Up, Down and Clear. All three did nothing, and nothing
        else in the mod failed with them, because every other numpad binding is
        an operator key that reports the same virtual key either way.

        The pairs, not just the presence of six bindings: a twin bound to the
        wrong action is the same silent failure wearing a passing test.

        The two halves of each pair now carry different names -- the world map
        needs to tell numpad 8 from Up, because there the arrow keys are the
        engine's own -- so what is checked is that both still arrive at the same
        action once `_do_action` has mapped them.
        """
        from fallout2_access.app import App as _App

        for locked, unlocked, what in ((104, 38, "dlg_prev"),
                                       (98, 40, "dlg_next"),
                                       (101, 12, "dlg_say")):
            with self.subTest(what=what):
                on = f2access.HOTKEYS.get(locked)
                off = f2access.HOTKEYS.get(unlocked)
                self.assertIsNotNone(on, "numpad key {} unbound".format(locked))
                self.assertIsNotNone(off, "its Num Lock twin {} unbound".format(unlocked))
                self.assertEqual(_App._NUMPAD_AS_ARROWS.get(on, on), what)
                self.assertEqual(_App._NUMPAD_AS_ARROWS.get(off, off), what)

    def test_numpad_five_still_reaches_the_hex_cursor_on_a_map(self):
        """Num Lock off sends Clear, and Clear must still mean numpad 5.

        Both halves of that pair now arrive as "num5", so this checks the pair
        is intact at the table rather than assuming the rename kept it.
        """
        self.assertEqual(f2access.HOTKEYS.get(101), f2access.HOTKEYS.get(12))

    def test_the_numpad_and_the_arrows_part_company_on_the_world_map(self):
        """There the arrow keys scroll the engine's own view.

        If numpad 8 and Up still shared one action name, pressing Up would
        scroll the map *and* walk this mod's cursor, and the player would hear
        about only one of the two. So the physical keys must be distinguishable
        in the table, and `_do_action` must send the numpad ones somewhere else
        on that screen alone.
        """
        from fallout2_access.app import App as _App, screens

        self.assertNotEqual(f2access.HOTKEYS.get(104), f2access.HOTKEYS.get(38))
        self.assertNotEqual(f2access.HOTKEYS.get(98), f2access.HOTKEYS.get(40))
        for numpad in ("num8", "num2", "num5"):
            with self.subTest(numpad=numpad):
                self.assertIn(numpad, _App._NUMPAD_ON_WORLDMAP)
                self.assertNotEqual(_App._NUMPAD_ON_WORLDMAP[numpad],
                                    _App._NUMPAD_AS_ARROWS[numpad])
        # And the arrows themselves are never rewritten, on any screen.
        self.assertNotIn("dlg_prev", _App._NUMPAD_ON_WORLDMAP)
        self.assertEqual(screens.WORLDMAP, "worldmap")

    def test_the_world_maps_keys_are_silent_everywhere_else(self):
        """Four of them are keys a player types.

        `[`, `]`, `/` and `T` belong to the world map's cursor and scanner. At a
        name field they are letters and punctuation, and the generic dispatch
        would have answered "No screen recognised" out loud on an unrecognised
        screen. Off the world map they must reach nothing and say nothing.
        """
        import f2access as f2

        world_map_keys = [what for what in f2.HOTKEYS.values()
                          if what.startswith("wm_")]
        self.assertTrue(world_map_keys, "no world map keys bound at all")
        for what in world_map_keys:
            for screen in ("chargen", "world", "unknown", "slots"):
                with self.subTest(what=what, screen=screen):
                    app = App.__new__(App)
                    app.world = _RecordingWorld(False)
                    app.screen = screen
                    app.watchers = {}
                    spoken = []

                    class _Ann:
                        def answer(self, text):
                            spoken.append(text)

                    app.ann = _Ann()
                    App._do_action(app, what)
                    self.assertEqual(spoken, [])

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
                       "call calibrate"):
            self.assertIn("if (pressed) then " + action, src,
                          "{} still runs on the release".format(action))

    def test_the_semicolon_pair_is_held_back_on_the_release(self):
        """Semicolon and shift-semicolon share one guard.

        They are the two readouts that have to answer with a panel open -- your
        health and what is in your hand are both things a sighted player reads
        off the bar without looking away -- so they are handled before the mode
        test rather than in the dispatch below, which does its own release
        check. That means the guard here is theirs alone, and a shift branch
        added outside it would report twice per press.
        """
        src = self.script()
        anchor = "if (key == DIK_SEMICOLON) then begin"
        self.assertIn(anchor, src)
        body = src[src.index(anchor):]
        body = body[:body.index("set_sfall_return")]
        self.assertIn("call report_status", body)
        self.assertIn("call report_weapon", body)
        for call in ("call report_status", "call report_weapon"):
            self.assertLess(body.index("if (pressed) then"), body.index(call),
                            "{} is reachable on the release".format(call))


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


class TestOwnKeys(unittest.TestCase):
    """The mod must not hear the keys it types itself."""

    class _Data:
        def __init__(self, flags):
            self.flags = flags

    def test_a_key_the_player_pressed_is_heard(self):
        self.assertTrue(f2access.from_player(0x100, self._Data(0)))

    def test_a_key_the_mod_sent_is_not(self):
        """Every digit typed into the "how many" window came back as another
        press, and the echoes buried the player's own."""
        self.assertFalse(f2access.from_player(
            0x100, self._Data(f2access.LLKHF_INJECTED)))
