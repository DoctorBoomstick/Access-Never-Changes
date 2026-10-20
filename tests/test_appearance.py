"""sfall's Race and Style rows: which is picked, and what it is called.

The rows always worked from the keyboard -- sfall takes Left and Right on them
itself -- and always said nothing but "Race" and "Style".
"""

import os
import struct
import tempfile
import unittest
import zlib

from fallout2_access.app import CharGenWatcher
from fallout2_access.game import appearance, chargen

from .fakes import FakeMemory

NODES = 0x0C000000
STRINGS = 0x0D000000


def memory_with_paths(paths):
    """The engine's search list, front first, as sfall leaves it."""
    mem = FakeMemory()
    nxt = 0
    for i, path in reversed(list(enumerate(paths))):
        node, text = NODES + i * 0x10, STRINGS + i * 0x100
        mem.poke(text, path.encode("latin-1") + b"\0")
        mem.poke(node, struct.pack("<IIII", text, 0, 0, nxt))
        nxt = node
    mem.poke(appearance.PATHS_HEAD, struct.pack("<I", nxt))
    return mem


def write_dat(path, files):
    """A DAT2 archive, every file compressed."""
    blob, index = bytearray(), bytearray()
    for name, data in files.items():
        packed = zlib.compress(data)
        index += struct.pack("<I", len(name)) + name.encode("latin-1")
        index += struct.pack("<BIII", 1, len(data), len(packed), len(blob))
        blob += packed
    tree = struct.pack("<I", len(files)) + index
    total = len(blob) + len(tree) + 8
    with open(path, "wb") as f:
        f.write(blob + tree + struct.pack("<II", len(tree), total))


def msg(title, desc):
    return "{{100}}{{}}{{{}}}\r\n{{101}}{{}}{{{}}}\r\n".format(title, desc).encode("cp1252")


class TestWhichIsPicked(unittest.TestCase):
    def test_the_front_pack_is_the_choice(self):
        mem = memory_with_paths(["Appearance\\hmR01S00.dat", "master.dat"])
        self.assertEqual(appearance.current(mem), appearance.Choice("m", 1, 0))

    def test_a_style_sits_in_front_of_its_race(self):
        mem = memory_with_paths(["Appearance\\hfR00S02", "Appearance\\hfR00S00",
                                 "master.dat"])
        self.assertEqual(appearance.current(mem), appearance.Choice("f", 0, 2))

    def test_no_pack_is_no_answer(self):
        """The mod switched off: nothing is guessed."""
        mem = memory_with_paths(["data", "master.dat", "critter.dat"])
        self.assertIsNone(appearance.current(mem))

    def test_a_looping_list_ends(self):
        mem = memory_with_paths(["data", "master.dat"])
        mem.poke(NODES + 0x10 + appearance.NODE_NEXT, struct.pack("<I", NODES))
        self.assertIsNone(appearance.current(mem))


class TestSfallsOwnNode(unittest.TestCase):
    """sfall 4.4.9 keeps the hero's pack off the engine's list, in a node of
    its own -- found by the code that prints the pack's name into it."""

    BASE = 0x11000000
    SIZE = 0x2000

    def memory(self, path):
        from fallout2_access.memory.process import Module

        base = self.BASE
        mem = FakeMemory()
        image = bytearray(self.SIZE)
        fmt_at, code_at, var_at = 0x1800, 0x1000, 0x1F00
        image[fmt_at:fmt_at + len(appearance.SFALL_FORMAT)] = appearance.SFALL_FORMAT
        # mov eax, [var]; mov ecx, 46h; push esi; push fmt
        code = (b"\xA1" + struct.pack("<I", base + var_at)
                + b"\xB9\x46\x00\x00\x00\x56"
                + b"\x68" + struct.pack("<I", base + fmt_at))
        image[code_at:code_at + len(code)] = code
        node, buf = 0x0E000000, 0x0E001000
        image[var_at:var_at + 4] = struct.pack("<I", node)
        mem.poke(base, bytes(image))
        mem.poke(node, struct.pack("<I", buf))
        mem.poke(buf, path.encode("latin-1") + b"\0")
        mem.module_at = lambda name, directory: Module("ddraw.dll", base, self.SIZE, "")
        return mem, base + var_at

    def test_the_variable_is_found_from_the_code(self):
        mem, var = self.memory("Appearance\\hMR01S02")
        self.assertEqual(appearance.find_hero_var(mem), var)

    def test_race_and_style_come_from_its_path(self):
        mem, var = self.memory("Appearance\\hMR01S02")
        self.assertEqual(appearance.current(mem, var), appearance.Choice("m", 1, 2))

    def test_the_dat_spelling_too(self):
        mem, var = self.memory("Appearance\\hFR00S03.dat")
        self.assertEqual(appearance.current(mem, var), appearance.Choice("f", 0, 3))


class TestNames(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "appearance"))
        with open(os.path.join(root, "fallout2.cfg"), "w") as f:
            f.write("[system]\nlanguage=german\n")
        write_dat(os.path.join(root, "appearance", "hmr01s00.dat"), {
            "text\\english\\game\\apprace.msg": msg("Race (Black)", "A long line."),
            "text\\german\\game\\apprace.msg": msg("Rasse (Schwarz)", "Eine Linie."),
            "text\\english\\game\\appstyle.msg": msg("Style (Default)", "Plain."),
        })
        loose = os.path.join(root, "appearance", "hmR01S01", "text", "english",
                             "game")
        os.makedirs(loose)
        with open(os.path.join(loose, "appstyle.msg"), "wb") as f:
            f.write(msg("Style (Bald)", "Shiny."))
        self.texts = appearance.Texts(root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_in_the_games_language(self):
        title, desc = self.texts.entry(appearance.Choice("m", 1, 0), "race")
        self.assertEqual((title, desc), ("Rasse (Schwarz)", "Eine Linie."))

    def test_english_when_the_pack_has_no_translation(self):
        title, _ = self.texts.entry(appearance.Choice("m", 1, 0), "style")
        self.assertEqual(title, "Style (Default)")

    def test_a_style_pack_borrows_its_races_name(self):
        choice = appearance.Choice("m", 1, 1)
        self.assertEqual(self.texts.entry(choice, "style")[0], "Style (Bald)")
        self.assertEqual(self.texts.entry(choice, "race")[0], "Rasse (Schwarz)")

    def test_a_missing_pack_is_empty(self):
        self.assertEqual(self.texts.entry(appearance.Choice("f", 4, 0), "race"),
                         (None, None))

    def test_the_title_splits_into_row_and_choice(self):
        self.assertEqual(appearance.split_title("Race (Black)"), ("Race", "Black"))
        self.assertEqual(appearance.split_title("Dreadlocks"), ("Dreadlocks", None))


class _Texts:
    def entry(self, choice, which):
        names = {("race", 0): "Race (Default)", ("race", 1): "Race (Black)",
                 ("style", 0): "Style (Default)", ("style", 1): "Style (Bald)"}
        key = (which, choice.race if which == "race" else choice.style)
        return names.get(key), "about " + which


class _Editor(chargen.CharGen):
    def __init__(self):
        self._msg_cache = {}
        self._rep_heading = None
        self._towns = []
        self.sheet = None
        self._appearance_texts = _Texts()
        self.sel = 1281
        self.choice = appearance.Choice("m", 0, 0)

    def appearance_choice(self): return self.choice
    def selection(self): return self.sel
    def folder(self): return 0
    def card(self): return 0
    def special(self): return [5] * 7
    def char_points(self): return 0
    def tags(self): return []
    def traits(self): return []
    def name(self): return None
    def dialog(self): return None
    def age(self): return 25
    def sex(self): return 0
    def skills(self): return []


class _Said:
    def __init__(self):
        self.said = []

    def answer(self, text):
        self.said.append(text)


class TestRows(unittest.TestCase):
    def setUp(self):
        self.gen = _Editor()

    def test_the_row_says_what_is_picked(self):
        item = self.gen.current()
        self.assertEqual(item.announce(), "Race, Default")
        self.assertEqual(item.description, "about race")

    def test_style_row(self):
        self.gen.sel, self.gen.choice = 1282, appearance.Choice("m", 0, 1)
        self.assertEqual(self.gen.current().announce(), "Style, Bald")

    def test_a_pack_with_no_words_is_numbered(self):
        self.gen.choice = appearance.Choice("m", 2, 0)
        self.assertEqual(self.gen.current().announce(), "Race, 3")

    def test_without_the_mod_the_row_is_still_named(self):
        self.gen.choice = None
        self.assertEqual(self.gen.current().announce(), "Race")


class TestChanging(unittest.TestCase):
    def setUp(self):
        self.gen = _Editor()
        self.w = CharGenWatcher(self.gen)
        self.ann = _Said()
        self.w.enter(self.ann)
        self.ann.said.clear()

    def test_right_on_race_says_the_new_race(self):
        self.gen.choice = appearance.Choice("m", 1, 0)
        self.w.poll(self.ann)
        self.assertEqual(self.ann.said, ["Race, Black"])

    def test_right_on_style_says_the_new_style(self):
        self.gen.sel = 1282
        self.w.poll(self.ann)
        self.ann.said.clear()
        self.gen.choice = appearance.Choice("m", 0, 1)
        self.w.poll(self.ann)
        self.assertEqual(self.ann.said, ["Style, Bald"])

    def test_tab_onto_the_rows_names_the_choice(self):
        self.gen.sel = 1282
        self.w.poll(self.ann)
        self.assertEqual(self.ann.said, ["Style, Default"])


if __name__ == "__main__":
    unittest.main()
