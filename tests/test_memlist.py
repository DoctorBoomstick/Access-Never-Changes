"""Which message texts the in-memory list reader accepts."""

import unittest

from fallout2_access.msg.memlist import _printable


class TestPrintable(unittest.TestCase):
    def test_english_and_blank_entries_are_text(self):
        self.assertTrue(_printable("Strength"))
        self.assertTrue(_printable(""))

    def test_a_translated_name_is_text(self):
        """Refusing these left the character sheet saying "Stat 0"."""
        self.assertTrue(_printable("Сила"))
        self.assertTrue(_printable("Stärke"))
        self.assertTrue(_printable("Agilité"))

    def test_control_bytes_are_not(self):
        self.assertFalse(_printable("St\x01r"))
        self.assertFalse(_printable(None))


if __name__ == "__main__":
    unittest.main()
