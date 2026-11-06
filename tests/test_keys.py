"""keys.ini: one file moves a key in both halves of the mod, or not at all."""

import os
import re
import shutil
import tempfile
import unittest

import f2access
from fallout2_access import controls, keys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class Names(unittest.TestCase):
    def test_the_ways_a_key_is_written(self):
        for text, name, shift, ctrl in (
                ("Numpad 7", "Numpad 7", False, False),
                ("numpad7", "Numpad 7", False, False),
                ("Right bracket", "Right bracket", False, False),
                ("]", "Right bracket", False, False),
                ("Control+Slash", "Slash", False, True),
                ("ctrl + /", "Slash", False, True),
                ("Shift+1", "1", True, False),
                ("Numpad +", "Numpad plus", False, False),
                ("Shift+Numpad +", "Numpad plus", True, False),
                ("k", "K", False, False)):
            combo = keys.parse(text)
            self.assertIsNotNone(combo, text)
            self.assertEqual((combo.key.name, combo.shift, combo.ctrl),
                             (name, shift, ctrl), text)

    def test_not_keys(self):
        for text in ("", "Numpad 11", "Alt+K", "Shift+Control+K", "Shift+", "Banana"):
            self.assertIsNone(keys.parse(text), text)

    def test_what_f1_calls_them(self):
        self.assertEqual(keys.parse("Control+Slash").said(), "Control and slash")
        self.assertEqual(keys.parse("Shift+1").said(), "Shift and 1")
        self.assertEqual(keys.parse("Shift+Numpad 7").said(), "Shift and Numpad 7")
        self.assertEqual(keys.parse("Left bracket").said(), "Left bracket")

    def test_every_default_reads_back_as_itself(self):
        for a in keys.ACTIONS:
            combo = keys.parse(a.default)
            self.assertIsNotNone(combo, a.name)
            self.assertEqual(keys.parse(combo.written()), combo, a.name)


class Mistakes(unittest.TestCase):
    def resolve(self, **wanted):
        problems = []
        return keys.resolve(wanted, problems), problems

    def test_a_good_line_moves_its_key(self):
        km, problems = self.resolve(cursor_northwest="Y")
        self.assertEqual(km["cursor_northwest"].key.name, "Y")
        self.assertEqual(problems, [])

    def test_an_unknown_key_keeps_the_default_and_says_so(self):
        km, problems = self.resolve(status="Semicolonn")
        self.assertEqual(km["status"], keys.DEFAULTS["status"])
        self.assertEqual(len(problems), 1)
        self.assertIn("status", problems[0])

    def test_the_grammar_and_the_mods_own_keys_cannot_be_taken(self):
        for key in ("Up", "Enter", "Escape", "Apostrophe", "Backslash",
                    "Numpad 0", "5", "Tab", "Shift+Tab"):
            km, problems = self.resolve(use_hand=key)
            self.assertEqual(km["use_hand"], keys.DEFAULTS["use_hand"], key)
            self.assertTrue(problems, key)

    def test_a_shifted_digit_is_free(self):
        km, problems = self.resolve(use_hand="Shift+2")
        self.assertEqual(km["use_hand"].written(), "Shift+2")
        self.assertEqual(problems, [])

    def test_two_on_one_key_both_go_back(self):
        km, problems = self.resolve(use_hand="K", status="K")
        self.assertEqual(km["use_hand"], keys.DEFAULTS["use_hand"])
        self.assertEqual(km["status"], keys.DEFAULTS["status"])
        self.assertTrue(problems)

    def test_taking_a_default_key_sends_the_newcomer_back(self):
        km, problems = self.resolve(use_hand="Semicolon")
        self.assertEqual(km["use_hand"], keys.DEFAULTS["use_hand"])
        self.assertEqual(km["status"], keys.DEFAULTS["status"])
        self.assertTrue(problems)

    def test_a_swap_is_allowed(self):
        km, problems = self.resolve(status="U", use_hand="Semicolon")
        self.assertEqual(km["status"].key.name, "U")
        self.assertEqual(km["use_hand"].key.name, "Semicolon")
        self.assertEqual(problems, [])

    def test_the_defaults_never_clash(self):
        combos = [keys.DEFAULTS[a.name] for a in keys.ACTIONS]
        self.assertEqual(len(combos), len(set(combos)))


class TheFile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_the_shipped_file_is_the_defaults(self):
        """config/keys.ini is made from keys.py; edit that and regenerate."""
        with open(os.path.join(ROOT, "config", "keys.ini"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().replace("\r\n", "\n"), keys.file_text(),
                             "regenerate config/keys.ini from keys.file_text()")

    def test_reading_the_shipped_file_changes_nothing(self):
        problems = []
        km = keys.load(os.path.join(ROOT, "config", "keys.ini"), problems)
        self.assertEqual(problems, [])
        self.assertEqual(km, keys.DEFAULTS)

    def test_no_file_is_the_defaults(self):
        self.assertEqual(keys.load(os.path.join(self.dir, "none.ini")), keys.DEFAULTS)

    def test_a_line_for_nothing_is_reported(self):
        path = os.path.join(self.dir, "keys.ini")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[map]\nfly = K\nstatus = L\n")
        problems = []
        km = keys.load(path, problems)
        self.assertEqual(km["status"].key.name, "L")
        self.assertEqual(len(problems), 1)

    def test_the_scripts_file(self):
        km = keys.resolve({"scan_kind_next": "Control+K"})
        where = keys.write_script_keys(km, self.dir)
        self.assertEqual(where, os.path.join(self.dir, keys.SCRIPT_KEYS_DIR,
                                             keys.SCRIPT_KEYS_NAME))
        with open(where, encoding="ascii") as fh:
            text = fh.read()
        self.assertIn("scan_kind_next={}\n".format(0x25 + keys.SCRIPT_CTRL), text)
        self.assertIn("cursor_northwest=71\n", text)
        # sfall's limit on the file name get_ini_setting is handed.
        self.assertLessEqual(len(keys.SCRIPT_KEYS), 63)


class TheScriptsAgree(unittest.TestCase):
    """keys.h's fallbacks are the defaults, and it reads every key the file writes."""

    def test_fallbacks_match_the_defaults(self):
        src = read(os.path.join("scripts", "keys.h"))
        dik = read_dik()
        found = dict(re.findall(r'key_setting\("(\w+)",\s*([^)]+)\)', src))
        written = {a.name for a in keys.ACTIONS if a.script}
        self.assertEqual(set(found), written)
        for name, expr in found.items():
            value = 0
            for part in expr.split("+"):
                part = part.strip()
                value += {"KEY_SHIFT": keys.SCRIPT_SHIFT,
                          "KEY_CTRL": keys.SCRIPT_CTRL}.get(part, dik.get(part, -1))
            self.assertEqual(value, keys.DEFAULTS[name].script_code(), name)

    def test_the_path_is_the_same_on_both_sides(self):
        src = read(os.path.join("scripts", "keys.h"))
        self.assertIn('"{}|keys|"'.format(keys.SCRIPT_KEYS), src)


def read_dik():
    """Scancodes by their sfall names, from the table keys.py keeps."""
    names = {"NUMPAD{}".format(n): "Numpad {}".format(n) for n in range(10)}
    names.update({"LBRACKET": "Left bracket", "RBRACKET": "Right bracket",
                  "SLASH": "Slash", "SEMICOLON": "Semicolon", "U": "U",
                  "1": "1", "DECIMAL": "Numpad dot", "F1": "F1",
                  "COMMA": "Comma", "PERIOD": "Period"})
    return {"DIK_" + k: keys.KEYS[v.lower()].dik for k, v in names.items()}


class TheListener(unittest.TestCase):
    def setUp(self):
        self.tables = (dict(f2access.HOTKEYS), dict(f2access.SHIFTED_HOTKEYS),
                       dict(f2access.CTRL_HOTKEYS))

    def test_the_defaults_change_nothing(self):
        plain, shifted, ctrl = (dict(t) for t in self.tables)
        keys.apply(keys.DEFAULTS, plain, shifted, ctrl)
        self.assertEqual((plain, shifted, ctrl), self.tables)

    def test_every_default_is_where_the_listener_has_it(self):
        plain, shifted, _ = self.tables
        for a in keys.ACTIONS:
            if not a.python:
                continue
            combo = keys.DEFAULTS[a.name]
            table = shifted if combo.shift else plain
            self.assertEqual(table.get(combo.key.vk), a.python[0], a.name)

    def test_a_moved_key_leaves_its_old_place(self):
        plain, shifted, ctrl = (dict(t) for t in self.tables)
        km = keys.resolve({"cursor_home": "K", "left_click": "Control+J"})
        keys.apply(km, plain, shifted, ctrl)
        self.assertEqual(plain.get(ord("K")), "num5")
        self.assertNotIn(101, plain)   # numpad 5
        self.assertNotIn(12, plain)    # and Clear, its Num Lock twin
        self.assertEqual(ctrl.get(ord("J")), "click")
        self.assertNotIn(107, plain)

    def test_control_falls_back_to_the_plain_key(self):
        # Control and Up is still Up: the "how many" window counts in tens.
        self.assertEqual(f2access.hotkey_for(38, False, True), "dlg_prev")


class F1(unittest.TestCase):
    def tearDown(self):
        controls.use_keymap(keys.DEFAULTS)

    def test_unmoved_keys_are_said_as_always(self):
        b = controls.COMMON[0]
        self.assertEqual(controls.key_text(b), "Numpad slash")

    def test_a_moved_key_is_said_where_it_went(self):
        controls.use_keymap(keys.resolve({"say_again": "Control+R"}))
        self.assertEqual(controls.key_text(controls.COMMON[0]), "Control and R")

    def test_a_pair(self):
        controls.use_keymap(keys.resolve({"log_older": "Shift+Page up",
                                          "log_newer": "Shift+Page down"}))
        self.assertEqual(controls.key_text(controls.COMMON[2]),
                         "Shift and page up and Shift and page down")

    def test_every_bound_name_is_a_key_action(self):
        from fallout2_access import app
        bindings = list(controls.COMMON)
        for cls in vars(app).values():
            if isinstance(cls, type):
                for attr in ("KEYS", "TALK_KEYS", "ITEM_KEYS"):
                    bindings += list(getattr(cls, attr, ()) or ())
        names = {n for b in bindings for n in b.binds}
        self.assertTrue(names)
        self.assertEqual(names - set(keys.BY_NAME), set())


if __name__ == "__main__":
    unittest.main()
