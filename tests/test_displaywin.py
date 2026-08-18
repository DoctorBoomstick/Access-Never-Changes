"""Parsing the interface bar's message records.

Layout established by planting a known string in the live game and looking at
where it landed: 256-byte records, text at +8, an optional colour byte with the
high bit set in front of the text, NUL terminated.

The fixtures below are built from real captured lines -- the Temple of Trials
description arrives without a colour byte, script messages arrive with one, and
that difference is exactly what an off-by-one in the anchor would hide.
"""

import unittest

from fallout2_access.game.displaywin import (
    RECORD,
    TEXT_OFFSET,
    DisplayWindow,
    _record_text,
)


def record(text: bytes, colour: bool = False) -> bytes:
    body = (b"\x95" if colour else b"") + text + b"\x00"
    rec = b"\x00" * TEXT_OFFSET + body
    return rec + b"\x00" * (RECORD - len(rec))


class FakeProc:
    """Enough of a process to read a synthetic buffer."""

    def __init__(self, base: int, blob: bytes) -> None:
        self.base = base
        self.blob = blob

    def read_chunked(self, addr: int, size: int):
        off = addr - self.base
        if off < 0:
            return b"\x00" * size
        return self.blob[off:off + size].ljust(size, b"\x00")

    def regions(self):
        class R:
            pass
        r = R()
        r.base, r.size = self.base, len(self.blob)
        return [r]


class TestRecordText(unittest.TestCase):
    def test_plain_line(self):
        self.assertEqual(_record_text(record(b"You see: a door.")), "You see: a door.")

    def test_colour_byte_is_stripped_not_spoken(self):
        self.assertEqual(
            _record_text(record(b"It is locked.", colour=True)), "It is locked."
        )

    def test_first_letter_survives_without_a_colour_byte(self):
        """The Temple description arrives with no colour byte. An anchor that
        assumed one would eat the Y."""
        text = b"You are in a dark, musty temple. The shadows seem"
        self.assertEqual(_record_text(record(text)), text.decode())

    def test_empty_record(self):
        self.assertEqual(_record_text(b"\x00" * RECORD), "")

    def test_truncated_record(self):
        self.assertEqual(_record_text(b"\x00" * 4), "")


class TestPolling(unittest.TestCase):
    def setUp(self):
        self.base = 0x00800000
        lines = [
            record(b"Access Never Changes ready.", colour=True),
            record(b"You see: a door."),
            record(b"It is locked.", colour=True),
        ]
        blob = b"".join(lines) + b"\x00" * RECORD * 8
        self.proc = FakeProc(self.base, blob)
        self.win = DisplayWindow(self.proc)

    def test_locates_the_beacon_and_anchors_on_the_record(self):
        self.assertTrue(self.win.locate())
        self.assertEqual(self.win.anchor, self.base)

    def test_beacon_itself_is_not_announced(self):
        self.win.locate()
        self.assertEqual(self.win.poll(), ["You see: a door.", "It is locked."])

    def test_lines_are_reported_once(self):
        self.win.locate()
        self.win.poll()
        self.assertEqual(self.win.poll(), [])

    def test_stops_at_the_first_empty_record(self):
        """Reading past the end would swallow the message about to land there."""
        self.win.locate()
        self.win.poll()
        blob = bytearray(self.proc.blob)
        new = record(b"You hit the Giant Ant for 10 points of damage.")
        blob[3 * RECORD:4 * RECORD] = new
        self.proc.blob = bytes(blob)
        self.assertEqual(
            self.win.poll(), ["You hit the Giant Ant for 10 points of damage."]
        )

    def test_missing_beacon_is_not_an_error(self):
        """Before a game loads the beacon has not been printed, and that is a
        normal state rather than a failure."""
        proc = FakeProc(self.base, b"\x00" * RECORD * 4)
        win = DisplayWindow(proc)
        self.assertFalse(win.locate())
        self.assertFalse(win.located)
        self.assertEqual(win.poll(), [])


if __name__ == "__main__":
    unittest.main()
