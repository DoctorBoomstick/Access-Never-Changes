"""Every screen's keys keep the one grammar in fallout2_access/controls.py.

This is the sanity check the controls were missing. Before it, each screen
picked its keys on the day it was built, and nothing noticed that the Pip-Boy
chose with numpad plus while every list on the map chose with Enter.
"""

import unittest

import f2access
from fallout2_access import controls
from fallout2_access.app import App, Watcher


def _all_watchers():
    found, todo = [], [Watcher]
    while todo:
        cls = todo.pop()
        for sub in cls.__subclasses__():
            found.append(sub)
            todo.append(sub)
    return found


def _tables(cls):
    """Every key table a watcher has: its own, and any it switches to."""
    out = [("", getattr(cls, "KEYS", ()))]
    for name in dir(cls):
        if name.endswith("_KEYS") and name != "KEYS":
            out.append((name, getattr(cls, name)))
    return out


class EveryScreenKeepsTheGrammar(unittest.TestCase):
    def test_no_screen_breaks_it(self):
        problems = []
        for cls in _all_watchers():
            screen = getattr(cls, "key", "?")
            for name, table in _tables(cls):
                problems += controls.violations(
                    "{}{}".format(screen, "." + name if name else ""),
                    table, cls)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_every_key_the_listener_hears_has_a_meaning(self):
        """A key in the listener with no entry in ROLES is a key nobody
        decided the meaning of."""
        others = {"barter_offer"}
        for vk, what in f2access.HOTKEYS.items():
            with self.subTest(vk=vk, what=what):
                self.assertTrue(what in controls.ROLES or what in others,
                                "{!r} is bound but has no role".format(what))

    def test_the_mouse_buttons_are_only_the_maps(self):
        for cls in _all_watchers():
            for _name, table in _tables(cls):
                for b in table:
                    if b.role == "mouse":
                        self.assertEqual(getattr(cls, "key", None), "world")

    def test_the_grammar_check_catches_a_bad_screen(self):
        """And the check is not vacuous."""
        bad = (controls.Binding("Numpad plus", "choose", "choose", ("click",),
                                "choose"),)
        self.assertTrue(controls.violations("pipboy", bad))
        twice = (controls.Binding("Up", "a", "previous", ("dlg_prev",)),
                 controls.Binding("Up", "b", "previous", ("dlg_prev",)))
        self.assertTrue(controls.violations("x", twice))


class F1(unittest.TestCase):
    def test_every_screen_answers_it(self):
        for cls in _all_watchers():
            if not getattr(cls, "TITLE", ""):
                continue
            with self.subTest(screen=cls.__name__):
                said = controls.help_text(cls.KEYS, cls.TITLE)
                self.assertTrue(said.startswith(cls.TITLE))
                self.assertIn("Numpad slash", said)

    def test_it_says_each_pair_of_keys_once(self):
        from fallout2_access.app import PipboyWatcher

        said = controls.help_text(PipboyWatcher.KEYS, "Pip-Boy")
        self.assertEqual(said.count("Up and Down"), 1)
        self.assertIn("Enter: choose.", said)
        self.assertIn("Backspace", said)

    def test_it_reaches_the_app(self):
        class _Said:
            last = ""

            def answer(self, text):
                self.last = text

        from fallout2_access.app import PipboyWatcher

        app = App.__new__(App)
        app.ann = _Said()
        app.screen = "pipboy"
        app.watchers = {"pipboy": PipboyWatcher.__new__(PipboyWatcher)}
        App._do_action(app, "help")
        self.assertTrue(app.ann.last.startswith("Pip-Boy keys."))


if __name__ == "__main__":
    unittest.main()
