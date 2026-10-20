"""Floating text, read back out of the bitmap the engine drew it into.

Torr answered "talk" with a line over his head, and the mod said nothing,
which sounded exactly like the mod failing to talk to him. These build a tiny
font of their own rather than ship the game's, draw text with it the way
text_object_create does, and check that it reads back -- including the case
that matters most in practice, two letters drawn with the same pixels.
"""

import struct
import unittest

from fallout2_access.app import WorldWatcher
from fallout2_access.game import floattext
from fallout2_access.game.worldlog import WorldLog

# Three rows tall, so a glyph is easy to write out by hand. "a" and "o" are
# drawn alike, as they are in font1.aaf; "x" is not.
HEIGHT = 3
GAP = 1
SPACE = 2
GLYPHS = {
    "a": ["##", "##", "##"],
    "o": ["##", "##", "##"],
    "x": ["#.#", ".#.", "#.#"],
    "l": ["#", "#", "#"],
    "T": ["###", ".#.", ".#."],
}
OUTLINE = 9
INK = 5


def _font_bytes():
    header = b"AAFF" + struct.pack(">4H", HEIGHT, GAP, SPACE, 1)
    table = []
    data = b""
    for code in range(256):
        rows = GLYPHS.get(chr(code))
        if rows is None:
            table.append(struct.pack(">HHI", 0, 0, 0))
            continue
        w = len(rows[0])
        table.append(struct.pack(">HHI", w, HEIGHT, len(data)))
        data += bytes(7 if ch == "#" else 0 for row in rows for ch in row)
    return header + b"".join(table) + data


FONT = floattext.Font(_font_bytes())


def _draw(lines, width=24):
    """Pixels as text_object_create leaves them: outlined, a row of margin."""
    pitch = FONT.line_pitch
    height = len(lines) * pitch + 2
    pix = bytearray(width * height)
    for i, text in enumerate(lines):
        x = 1
        top = 1 + i * pitch
        for ch in text:
            if ch == " ":
                x += SPACE + GAP
                continue
            rows = GLYPHS[ch]
            for y, row in enumerate(rows):
                for dx, c in enumerate(row):
                    if c == "#":
                        pix[(top + y) * width + x + dx] = INK
            x += len(rows[0]) + GAP
    # The outline: every empty pixel touching ink, as bufferOutline draws it.
    # The top row is all outline wherever the text would touch it, which is
    # what the outline colour is read from.
    out = bytearray(pix)
    for y in range(height):
        for x in range(width):
            if pix[y * width + x]:
                continue
            near = any(pix[ny * width + nx] == INK
                       for ny in range(max(0, y - 1), min(height, y + 2))
                       for nx in range(max(0, x - 1), min(width, x + 2)))
            if near or y == 0:
                out[y * width + x] = OUTLINE
    return bytes(out), width, height


class ShapeTest(unittest.TestCase):

    def test_one_line_reads_back(self):
        pix, w, h = _draw(["Tx l"])
        self.assertEqual(floattext.decode(pix, w, h, 1, FONT), "Tx l")

    def test_lines_are_joined_with_a_space(self):
        pix, w, h = _draw(["Tx", "lx"])
        self.assertEqual(floattext.decode(pix, w, h, 2, FONT), "Tx lx")

    def test_outline_is_not_read_as_ink(self):
        pix, w, h = _draw(["x"])
        mask = floattext.ink_mask(pix, w, h)
        self.assertEqual(sum(map(sum, mask)), 5)

    def test_letters_drawn_alike_share_a_key(self):
        self.assertEqual(FONT.key("Toxa"), FONT.key("Taxo"))
        self.assertNotEqual(FONT.key("Tox"), FONT.key("Tol"))

    def test_key_ignores_how_the_line_was_wrapped(self):
        self.assertEqual(FONT.key("Tx\r\n  lx"), FONT.key("Tx lx"))


class ContextTest(unittest.TestCase):
    """What the font cannot tell apart, the game's own text can."""

    def test_whole_line_from_the_game_wins(self):
        corpus = floattext.Corpus(["Tox lo"], FONT)
        pix, w, h = _draw(["Tox lo"])
        shape = floattext.decode(pix, w, h, 1, FONT)
        self.assertEqual(corpus.resolve(shape, FONT), "Tox lo")

    def test_a_line_the_game_lacks_is_settled_word_by_word(self):
        corpus = floattext.Corpus(["Tox", "lo lo", "la"], FONT)
        # "lo" twice to "la" once: the more common spelling wins.
        self.assertEqual(corpus.resolve("Tax la", FONT), "Tox lo")

    def test_an_unknown_word_is_left_as_drawn(self):
        corpus = floattext.Corpus(["Tox"], FONT)
        self.assertEqual(corpus.resolve("xax", FONT), "xax")


class LineTest(unittest.TestCase):

    def test_parses_what_the_script_writes(self):
        got = floattext.float_line("WORLD:float 197213576|1603625|0|Torr|")
        self.assertEqual(got, (197213576, 1603625, False, "Torr"))

    def test_a_negative_pointer_is_read_as_unsigned(self):
        ptr, _t, _me, _who = floattext.float_line("WORLD:float -2|5|1||")
        self.assertEqual(ptr, 0xFFFFFFFE)

    def test_garbage_is_ignored(self):
        self.assertIsNone(floattext.float_line("WORLD:float nonsense"))


class _Reader:
    def __init__(self, text):
        self.text = text
        self.asked = []

    def read(self, ptr, created):
        self.asked.append((ptr, created))
        return self.text


class SaidTest(unittest.TestCase):
    """Who said it is the point; your own lines are said bare."""

    def _said(self, line, text="Bugs dead."):
        w = WorldWatcher(WorldLog("nowhere.log"))
        w.floats = _Reader(text)
        return w._float_said(line)

    def test_someone_else_is_named(self):
        self.assertEqual(self._said("WORLD:float 1|2|0|Torr|"),
                         "Torr: Bugs dead.")

    def test_you_are_not(self):
        self.assertEqual(self._said("WORLD:float 1|2|1|Chosen One|"),
                         "Bugs dead.")

    def test_nothing_read_says_nothing(self):
        self.assertIsNone(self._said("WORLD:float 1|2|0|Torr|", text=None))

    def test_no_reader_says_nothing(self):
        w = WorldWatcher(WorldLog("nowhere.log"))
        self.assertIsNone(w._float_said("WORLD:float 1|2|0|Torr|"))


if __name__ == "__main__":
    unittest.main()
