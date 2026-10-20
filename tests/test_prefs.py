"""The preferences screen as a list, against a fake of the game's memory."""

import struct
import unittest

from fallout2_access.game import pausemenu, prefs
from fallout2_access.game.prefs import CHANGED, SETTINGS, Prefs


class _Mem:
    """Reads and writes little-endian values at addresses, like the game."""

    def __init__(self):
        self.bytes = {}

    def put(self, addr, data):
        for i, b in enumerate(data):
            self.bytes[addr + i] = b

    def read(self, addr, size):
        if addr not in self.bytes:
            return None
        return bytes(self.bytes.get(addr + i, 0) for i in range(size))

    def read_i32(self, addr):
        raw = self.read(addr, 4)
        return struct.unpack("<i", raw)[0] if raw else None

    def write(self, addr, data):
        self.put(addr, data)
        return True


def _game(over=None):
    """Every setting at the game's defaults, or as given by title number."""
    mem = _Mem()
    defaults = {101: 1, 102: 1, 103: 3, 104: 2, 105: 0, 106: 0, 107: 1,
                108: 0, 109: 0, 110: 0, 111: 0, 112: 0, 122: 0, 113: 3.5,
                114: 22281, 115: 22281, 116: 22281, 117: 22281, 118: 1.0,
                119: 1.0}
    defaults.update(over or {})
    for s in SETTINGS:
        v = defaults[s.title]
        mem.put(s.addr, struct.pack("<d", v) if s.double
                else struct.pack("<i", int(v)))
    mem.put(CHANGED, struct.pack("<i", 0))
    return mem


def _at(title):
    return next(i for i, s in enumerate(SETTINGS) if s.title == title)


class ReadingTheSettings(unittest.TestCase):
    def test_a_knob_says_its_label(self):
        p = Prefs(_game())
        self.assertEqual(p.say(_at(101)), "Game difficulty: Normal. 1 of 20.")
        self.assertEqual(p.say(_at(103)).split(".")[0],
                         "Violence level: Maximum Blood")

    def test_a_volume_is_a_percentage(self):
        p = Prefs(_game({114: 32767}))
        self.assertIn("100%, Loud", p.say(_at(114)))
        p = Prefs(_game({114: 0}))
        self.assertIn("0%, Off", p.say(_at(114)))

    def test_text_delay_reads_as_a_speed(self):
        """Stored as a delay, drawn Slow to Faster: a long delay is slow."""
        p = Prefs(_game({113: 6.0}))
        self.assertIn("0%, Slow", p.say(_at(113)))
        p = Prefs(_game({113: 3.5}))
        self.assertIn("50%, Normal", p.say(_at(113)))


class ChangingThem(unittest.TestCase):
    def test_right_moves_a_knob_one_place_and_marks_it_changed(self):
        mem = _game()
        p = Prefs(mem)
        p.index = _at(101)
        self.assertEqual(p.change(1), "Hard.")
        self.assertEqual(mem.read_i32(SETTINGS[p.index].addr), 2)
        self.assertEqual(mem.read_i32(CHANGED), 1,
                         "Done saves nothing unless the flag is set")

    def test_a_knob_stops_at_its_ends(self):
        p = Prefs(_game({101: 2}))
        p.index = _at(101)
        self.assertEqual(p.change(1), "Hard.")

    def test_a_slider_moves_a_tenth(self):
        mem = _game({114: 0})
        p = Prefs(mem)
        p.index = _at(114)
        p.change(1)
        self.assertEqual(mem.read_i32(SETTINGS[p.index].addr), 3277)

    def test_doubles_are_written_as_doubles(self):
        mem = _game()
        p = Prefs(mem)
        p.index = _at(119)
        p.extreme(True)
        raw = mem.read(SETTINGS[p.index].addr, 8)
        self.assertEqual(struct.unpack("<d", raw)[0], 2.5)

    def test_faster_text_is_a_shorter_delay(self):
        mem = _game()
        p = Prefs(mem)
        p.index = _at(113)
        p.extreme(True)
        raw = mem.read(SETTINGS[p.index].addr, 8)
        self.assertEqual(struct.unpack("<d", raw)[0], 1.0)

    def test_the_list_does_not_wrap(self):
        p = Prefs(_game())
        p.step(-1)
        self.assertEqual(p.index, 0)
        for _ in range(40):
            p.step(1)
        self.assertEqual(p.index, len(SETTINGS) - 1)


class TheTable(unittest.TestCase):
    def test_every_setting_has_a_name_and_labels_in_english(self):
        for s in SETTINGS:
            self.assertIn(s.title, prefs.ENGLISH)
            for n in s.labels:
                self.assertIn(n, prefs.ENGLISH)

    def test_no_two_settings_share_an_address(self):
        addrs = [s.addr for s in SETTINGS]
        self.assertEqual(len(addrs), len(set(addrs)))


class ThePauseMenu(unittest.TestCase):
    def test_the_quit_question_has_words_without_the_game(self):
        self.assertIn("quit", pausemenu.quit_question(_Mem()))


if __name__ == "__main__":
    unittest.main()
