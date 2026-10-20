"""The mod's words and their translations.

The rule under all of it: a translation can change what is said, and nothing a
translation does -- a missing line, a misspelt blank, a file that will not open
-- can make the mod say nothing.
"""

import os
import re
import string
import sys
import tempfile
import unittest

from fallout2_access import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG = os.path.join(ROOT, "lang")
sys.path.insert(0, os.path.join(ROOT, "tools"))

import mklang  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def blanks(text):
    return sorted({name for _lit, name, _spec, _conv in string.Formatter().parse(text)
                   if name})


class TestTranslating(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        write(os.path.join(self.root, "german.ini"),
              "[chargen]\npoints_left = Noch {points} Punkte\n"
              "race = Rasse {oops}\nempty =\n")
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(i18n.init, "english", os.path.join(self.root, "none"))

    def test_without_a_file_the_code_speaks_english(self):
        i18n.init("english", os.path.join(self.root, "none"))
        self.assertEqual(i18n.tr("chargen.points_left", "{points} points left",
                                 points=3), "3 points left")

    def test_the_chosen_language(self):
        self.assertEqual(i18n.init("german", self.root), "german")
        self.assertEqual(i18n.tr("chargen.points_left", "{points} points left",
                                 points=3), "Noch 3 Punkte")

    def test_a_line_left_out_is_english(self):
        i18n.init("german", self.root)
        self.assertEqual(i18n.tr("chargen.other", "Other"), "Other")

    def test_a_line_left_empty_is_english(self):
        i18n.init("german", self.root)
        self.assertEqual(i18n.tr("chargen.empty", "Empty"), "Empty")

    def test_a_misspelt_blank_is_english(self):
        i18n.init("german", self.root)
        self.assertEqual(i18n.tr("chargen.race", "Race {name}", name="x"), "Race x")

    def test_a_missing_language_is_english_and_noted(self):
        notes = []
        self.assertEqual(i18n.init("klingon", self.root, notes), "english")
        self.assertEqual(len(notes), 1)

    def test_auto_follows_the_game(self):
        game = os.path.join(self.root, "game")
        write(os.path.join(game, "fallout2.cfg"), "[system]\nlanguage=french\n")
        self.assertEqual(i18n.choose("auto", game), "french")
        self.assertEqual(i18n.choose("Polish", game), "polish")
        self.assertEqual(i18n.choose("auto", None), "english")


class TestScriptWords(unittest.TestCase):
    """The scripts write English; it is translated on the way out."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        write(os.path.join(self._tmp.name, "german.ini"),
              "[test]\ndoor = eine Tür\n")
        i18n.script_words({"test.door": "a door", "test.lit": "lit"})
        i18n.init("german", self._tmp.name)
        self.addCleanup(i18n.init, "english", os.path.join(ROOT, "nowhere"))

    def test_a_known_phrase_is_translated(self):
        self.assertEqual(i18n.say_script("a door"), "eine Tür")

    def test_a_known_phrase_without_a_translation_stays_english(self):
        self.assertEqual(i18n.say_script("lit"), "lit")

    def test_anything_else_passes_through(self):
        self.assertEqual(i18n.say_script("Sulik"), "Sulik")

    def test_field_by_field(self):
        self.assertEqual(i18n.say_script_fields("Sulik, a door"), "Sulik, eine Tür")


class TestScriptPhrasesOnTheWayOut(unittest.TestCase):
    """The scripts' English is parsed as English and spoken translated."""

    def setUp(self):
        from fallout2_access.game import worldlog

        self.worldlog = worldlog
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        write(os.path.join(self._tmp.name, "german.ini"),
              "[hex]\nlocked = verschlossen\nempty = leer\nfacing = blickt {direction}\n"
              "[dir]\nne = Nordost\n"
              "[act]\ntalk = mit ihm reden\n"
              "[words]\nof = {index} von {total}\nhexes = {count} Felder\n")
        i18n.init("german", self._tmp.name)
        self.addCleanup(i18n.init, "english", os.path.join(ROOT, "nowhere"))

    def test_a_hex_is_parsed_in_english_and_spoken_translated(self):
        hex_ = self.worldlog.HexReading(1, 3, "Door, locked, Klint, facing north east")
        self.assertEqual(hex_.names(), ["Door", "Klint"])
        self.assertEqual(hex_.announce(),
                         "Door, verschlossen, Klint, blickt Nordost, 3 Felder")

    def test_an_empty_hex(self):
        self.assertEqual(self.worldlog.HexReading(1, 0, "").announce(), "leer")

    def test_a_menu_label(self):
        said = self.worldlog.menu_line("WORLD:menu open Sulik|3|talk to it|")
        self.assertEqual(said, "Sulik. 3 actions. Mit ihm reden, 1 von 3.")


class TestTheEnglishFile(unittest.TestCase):
    """lang/english.ini is the code's English, exactly."""

    def test_every_tr_has_a_literal_key_and_one_english(self):
        _found, problems = mklang.collect()
        self.assertEqual(problems, [])

    def test_the_file_is_up_to_date(self):
        found, _problems = mklang.collect()
        with open(mklang.OUT, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), mklang.render(found),
                             "run tools/mklang.py")

    def test_the_file_reads_back_as_the_code(self):
        found, _problems = mklang.collect()
        problems = []
        loaded = i18n.load_file(mklang.OUT, problems)
        self.assertEqual(problems, [])
        self.assertEqual(loaded, found)


class TestShippedTranslations(unittest.TestCase):
    """Every lang/*.ini keeps the blanks its English has."""

    def test_blanks_match(self):
        found, _problems = mklang.collect()
        for name in os.listdir(LANG):
            if not name.endswith(".ini") or name == "english.ini":
                continue
            problems = []
            loaded = i18n.load_file(os.path.join(LANG, name), problems)
            self.assertEqual(problems, [], name)
            for key, text in loaded.items():
                if key in found:
                    self.assertEqual(blanks(text), blanks(found[key]),
                                     "{} {}".format(name, key))


if __name__ == "__main__":
    unittest.main()
