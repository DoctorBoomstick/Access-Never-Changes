"""The window cache, and a window that died at the address it remembered.

Trading broke after a reload with "cannot find the scroll control". The barter
window opens at the same rectangle every time, and a freed window keeps its
rectangle and a button list in the heap -- so the address remembered from the
last barter still looked like the window, and was handed back, without the
scroll arrows the move was about to press.
"""

import unittest
from unittest import mock

from fallout2_access.game import uiwindow

RECT = (272, 384, 480, 180)


def _button(code):
    return uiwindow.Button(id=1, flags=0, left=0, top=0, right=10, bottom=10,
                           press=code, addr=0)


def _window(addr, codes):
    return uiwindow.Window(id=5, flags=0, left=RECT[0], top=RECT[1],
                           width=RECT[2], height=RECT[3], addr=addr,
                           buttons=[_button(c) for c in codes])


class ADeadWindowAtTheRememberedAddress(unittest.TestCase):
    def setUp(self):
        self.finder = uiwindow.WindowFinder(proc=None)
        self.finder._addr[RECT] = 0x1000
        self.dead = _window(0x1000, [2000, 2001])        # no arrows
        self.live = _window(0x2000, [2000, 2001, 397, 401])
        self.finder._read = lambda addr: self.dead

    def test_a_remembered_window_missing_a_needed_button_is_searched_again(self):
        with mock.patch.object(uiwindow, "find_window_at",
                               return_value=self.live) as search:
            win = self.finder.at(*RECT, need=(2000, 397, 401))
        self.assertIs(win, self.live)
        search.assert_called_once()
        self.assertEqual(self.finder._addr[RECT], 0x2000)

    def test_with_nothing_needed_the_remembered_window_still_answers(self):
        with mock.patch.object(uiwindow, "find_window_at") as search:
            win = self.finder.at(*RECT)
        self.assertIs(win, self.dead)
        search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
