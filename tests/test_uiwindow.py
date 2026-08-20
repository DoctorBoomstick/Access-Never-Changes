"""Reading GNW windows and buttons out of memory.

The fixtures are built to the layout confirmed against the live process. The
interface bar was the key that opened this: the in-game script reports its
rectangle through sfall independently, so the struct holding 112,668 800x100
could be identified without guessing, and everything else follows from it.

The case that matters most is the last one. A button whose event code is below
256 is a button a *key* already presses, because GNW puts key presses and button
presses in one stream -- which is how the loot window's TAKE ALL turned out to
be reachable by pressing A, with no pointer involved at all.
"""

import struct
import unittest

from fallout2_access.game.uiwindow import (
    B_SIZE,
    W_SIZE,
    find_window_at,
    find_windows,
)


def button(bid, flags, l, t, r, b, press, nxt=0):
    raw = bytearray(B_SIZE)
    struct.pack_into("<6i", raw, 0, bid, flags, l, t, r, b)
    struct.pack_into("<i", raw, 0x20, press)
    struct.pack_into("<I", raw, 0x78, nxt)
    return bytes(raw)


def window(wid, flags, l, t, w, h, buttons_ptr=0):
    raw = bytearray(W_SIZE)
    struct.pack_into("<8i", raw, 0, wid, flags, l, t,
                     l + w - 1, t + h - 1, w, h)
    struct.pack_into("<I", raw, 0x30, buttons_ptr)
    return bytes(raw)


class FakeProc:
    """A flat address space holding whatever structs a test needs."""

    def __init__(self, base=0x01000000):
        self.base = base
        self.blob = bytearray()

    def place(self, data: bytes) -> int:
        addr = self.base + len(self.blob)
        self.blob += data
        return addr

    def pad(self, n: int) -> None:
        self.blob += b"\x00" * n

    def read_chunked(self, addr, size):
        off = addr - self.base
        if off < 0 or off >= len(self.blob):
            return b"\x00" * size
        return bytes(self.blob[off:off + size]).ljust(size, b"\x00")

    def regions(self, writable_only=False):
        class R:
            pass
        r = R()
        r.base, r.size = self.base, len(self.blob)
        return [r]


class TestFindingWindows(unittest.TestCase):
    def setUp(self):
        self.proc = FakeProc()
        self.proc.pad(64)
        self.proc.place(window(4, 2, 112, 668, 800, 100))
        self.proc.pad(32)
        self.proc.place(window(5, 0x10, 243, 146, 537, 376))
        self.proc.pad(64)

    def test_both_windows_are_found(self):
        ids = sorted(w.id for w in find_windows(self.proc))
        self.assertEqual(ids, [4, 5])

    def test_a_window_can_be_found_by_its_rectangle(self):
        """Matched on the rect rather than the id, because the script can ask
        sfall for the rect -- so the struct is confirmed, not assumed."""
        win = find_window_at(self.proc, 243, 146, 537, 376)
        self.assertIsNotNone(win)
        self.assertEqual(win.id, 5)

    def test_a_rectangle_nothing_has_is_not_invented(self):
        self.assertIsNone(find_window_at(self.proc, 1, 2, 3, 4))

    def test_width_must_agree_with_the_rectangle(self):
        """The check that stops four unrelated heap integers reading as a
        window. Without it a scan of live memory is mostly false positives."""
        proc = FakeProc()
        proc.pad(32)
        raw = bytearray(window(9, 0, 10, 10, 100, 100))
        struct.pack_into("<i", raw, 0x18, 999)   # width that fits nothing
        proc.place(bytes(raw))
        proc.pad(32)
        self.assertEqual(find_windows(proc), [])


class TestButtons(unittest.TestCase):
    def setUp(self):
        self.proc = FakeProc()
        self.proc.pad(16)
        # Built back to front so each button can point at the next.
        row1 = self.proc.place(button(11, 0x10000, 176, 85, 239, 132, 1001))
        row0 = self.proc.place(button(12, 0x10000, 176, 37, 239, 84, 1000, row1))
        take = self.proc.place(button(30, 0x10000, 432, 204, 470, 244, 65, row0))
        self.proc.place(window(5, 0x10, 243, 146, 537, 376, take))
        self.proc.pad(16)
        self.win = find_window_at(self.proc, 243, 146, 537, 376)

    def test_the_whole_list_is_walked(self):
        self.assertEqual([b.id for b in self.win.buttons], [30, 12, 11])

    def test_a_button_can_be_found_by_its_event_code(self):
        self.assertEqual(self.win.by_press(1001).id, 11)

    def test_button_size_comes_from_the_rectangle(self):
        row = self.win.by_press(1000)
        self.assertEqual((row.width, row.height), (64, 48))

    def test_centre_is_absolute_not_window_relative(self):
        """Buttons are stored relative to their window; a click is not."""
        self.assertEqual(self.win.by_press(1000).centre(self.win),
                         (243 + 207, 146 + 60))

    def test_a_low_event_code_is_a_key_that_already_works(self):
        """The find that made TAKE ALL reachable with no pointer at all."""
        take = self.win.by_press(65)
        self.assertEqual(take.key, 65)
        self.assertEqual(self.win.keyed(), {65: take})

    def test_a_high_event_code_is_not_a_key(self):
        """Row codes are synthetic, so rows still need the pointer."""
        self.assertIsNone(self.win.by_press(1000).key)

    def test_a_cycle_in_the_list_does_not_hang(self):
        proc = FakeProc()
        proc.pad(16)
        first = proc.base + 16
        proc.place(button(1, 0, 0, 0, 10, 10, 5, first))   # points at itself
        proc.place(window(7, 0, 0, 0, 100, 100, first))
        proc.pad(16)
        win = find_window_at(proc, 0, 0, 100, 100)
        self.assertEqual(len(win.buttons), 1)




class TestItemWindowLayout(unittest.TestCase):
    """The rectangles read off the live inventory window.

    Recorded as a test so that a change in how they are interpreted has to be
    deliberate. These are the engine's own numbers at 1024x768 -- the mod reads
    them fresh every time rather than trusting these, but the *meaning* of each
    event code is the thing worth pinning down.
    """

    def setUp(self):
        self.proc = FakeProc()
        self.proc.pad(16)
        # Built back to front so each button can point at the next.
        nxt = 0
        for code, l, t, r, b in [
            (1006, 245, 286, 334, 346),   # ITEM2, right of ITEM1
            (1007, 154, 286, 243, 346),   # ITEM1, below ARMOR
            (1008, 154, 183, 243, 243),   # ARMOR, under the character figure
            (1000, 44, 35, 107, 82),      # first row of the carried list
            (1001, 44, 83, 107, 130),
        ]:
            nxt = self.proc.place(button(code, 0x10000, l, t, r, b, code, nxt))
        self.proc.place(window(5, 0x10, 262, 145, 499, 377, nxt))
        self.proc.pad(16)
        self.win = find_window_at(self.proc, 262, 145, 499, 377)

    def test_every_slot_is_reachable_by_its_code(self):
        for code in (1000, 1001, 1006, 1007, 1008):
            self.assertIsNotNone(self.win.by_press(code),
                                 "no button for code {}".format(code))

    def test_the_equipment_slots_are_all_the_same_size(self):
        sizes = {(self.win.by_press(c).width, self.win.by_press(c).height)
                 for c in (1006, 1007, 1008)}
        self.assertEqual(sizes, {(90, 61)})

    def test_armour_sits_above_the_two_hands(self):
        armour = self.win.by_press(1008)
        for hand in (1007, 1006):
            self.assertLess(armour.top, self.win.by_press(hand).top)

    def test_the_hands_sit_side_by_side(self):
        left, right = self.win.by_press(1007), self.win.by_press(1006)
        self.assertEqual(left.top, right.top)
        self.assertLess(left.left, right.left)

    def test_list_rows_step_by_the_row_height(self):
        first, second = self.win.by_press(1000), self.win.by_press(1001)
        self.assertEqual(second.top - first.top, 48)

    def test_no_slot_is_reachable_by_a_key(self):
        """Unlike TAKE ALL, every one of these is above the keyboard range, so
        they need a real click -- which is the whole reason the aimer exists."""
        for code in (1000, 1001, 1006, 1007, 1008):
            self.assertIsNone(self.win.by_press(code).key)


if __name__ == "__main__":
    unittest.main()
