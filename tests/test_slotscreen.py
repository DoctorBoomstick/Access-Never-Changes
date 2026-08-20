"""Reading the save and load screens.

Everything here guards the same thing: this is the one screen in the game where
a wrong sentence destroys something. Saying "empty" about a row that holds a
game is how an evening gets overwritten, so the engine's own answer decides
whether a row is occupied and the savegame folder only supplies the words.
"""

import struct
import unittest

import fakes

from fallout2_access.game.saves import OFF_CHARACTER, OFF_DESCRIPTION, SIGNATURE
from fallout2_access.game.slotscreen import (
    HEADER_SIZE,
    MAX_PAGES,
    OCCUPIED,
    PAGE_BACK_TEN,
    PAGE_FORWARD_TEN,
    PAGE_NEXT,
    PAGE_PREV,
    Pager,
    SELECTION,
    SLOTS_PER_PAGE,
    SLOT_HEADERS,
    SlotScreen,
    describe,
    pages_holding,
)


# Somewhere sfall could plausibly have been loaded. Deliberately not the
# 0x11000000 it happened to load at on the machine this was measured on: the
# page address is a module base plus an offset, and a test that hardcodes one
# launch's base would pass while the real thing broke on relocation.
FAKE_SFALL_BASE = 0x21000000


class FakeModule:
    def __init__(self, base):
        self.base = base


class FakeProc:
    """A process with just the handful of addresses this reads.

    Keyed by address, so it takes a dict rather than keywords -- integers are
    not valid keyword names.
    """

    directory = r"C:\game"

    def __init__(self, values=None, blobs=None, sfall=FAKE_SFALL_BASE):
        self.values = dict(values or {})
        self.blobs = dict(blobs or {})
        self.sfall = sfall

    def read_i32(self, addr):
        return self.values.get(addr)

    def read_chunked(self, addr, size):
        return self.blobs.get(addr)

    def module_at(self, name, directory):
        if self.sfall is None:
            return None
        return FakeModule(self.sfall)


def header_bytes(character="Narg", description="a description"):
    """A save header laid out the way the engine holds one on screen."""
    blob = bytearray(b"\x00" * HEADER_SIZE)
    blob[0:len(SIGNATURE)] = SIGNATURE
    blob[OFF_CHARACTER:OFF_CHARACTER + len(character)] = character.encode("cp1252")
    blob[OFF_DESCRIPTION:OFF_DESCRIPTION + len(description)] = description.encode("cp1252")
    return bytes(blob)


def proc(selection=0, occupied=(), page=None, headers=None,
         sfall=FAKE_SFALL_BASE):
    values = {SELECTION: selection}
    for i in range(SLOTS_PER_PAGE):
        values[OCCUPIED + 4 * i] = 1 if i < len(occupied) and occupied[i] else 0
    if page is not None:
        values[FAKE_SFALL_BASE + 0xEF4B8] = page
    blobs = {}
    for index, blob in (headers or {}).items():
        blobs[SLOT_HEADERS + HEADER_SIZE * index] = blob
    return FakeProc(values, blobs, sfall)


class TestShowing(unittest.TestCase):
    """Recognised by its window, not by a flag.

    There was a flag, 0x00614858, and it never went back to zero once the
    screen had been opened. Because `detect` tests this screen before any
    other, that did not mis-name one screen -- it made every other screen in
    the game unreachable for the rest of the session.
    """

    PANEL = (640, 480, [PAGE_PREV, PAGE_NEXT])

    def test_open_when_the_panel_is_open(self):
        p = fakes.memory_with_windows([(800, 100, []), self.PANEL])
        self.assertTrue(SlotScreen(p).showing)

    def test_closed_when_it_is_not_in_the_window_list(self):
        p = fakes.memory_with_windows([(800, 100, []), (1024, 768, [])])
        self.assertFalse(SlotScreen(p).showing)

    def test_a_different_640_by_480_panel_is_not_this_screen(self):
        """The character sheet and Pipboy are 640x480 as well."""
        p = fakes.memory_with_windows([(640, 480, [500, 501])])
        self.assertFalse(SlotScreen(p).showing)

    def test_nothing_open_at_all_is_not_open(self):
        self.assertFalse(SlotScreen(fakes.memory_with_windows([])).showing)

    def test_unreadable_memory_is_not_open(self):
        self.assertFalse(SlotScreen(FakeProc()).showing)


class TestSelection(unittest.TestCase):
    def test_the_highlighted_row_is_read(self):
        self.assertEqual(SlotScreen(proc(selection=4)).selection(), 4)

    def test_both_ends_of_the_range_are_valid(self):
        self.assertEqual(SlotScreen(proc(selection=0)).selection(), 0)
        self.assertEqual(SlotScreen(proc(selection=9)).selection(), 9)

    def test_a_value_off_the_end_is_refused(self):
        """This is the number that decides which game gets overwritten, so a
        reading outside the ten rows is not repaired into a guess."""
        self.assertIsNone(SlotScreen(proc(selection=10)).selection())
        self.assertIsNone(SlotScreen(proc(selection=-1)).selection())

    def test_an_unreadable_selection_is_none(self):
        self.assertIsNone(SlotScreen(FakeProc()).selection())


class TestOccupancy(unittest.TestCase):
    def test_the_engines_own_answer_is_read_per_row(self):
        s = SlotScreen(proc(occupied=(1, 1, 1, 1, 1, 0, 0, 0, 0, 0)))
        self.assertEqual(s.occupied(),
                         [True] * 5 + [False] * 5)

    def test_an_empty_page_reads_as_all_empty(self):
        self.assertEqual(SlotScreen(proc()).occupied(), [False] * 10)


class TestSlotNumbers(unittest.TestCase):
    """Rows are 0-based on screen; slots are 1-based on disk. Mixing the two
    silently targets the wrong saved game."""

    def test_the_first_page_starts_at_one(self):
        s = SlotScreen(proc())
        self.assertEqual(s.slot_number(0, 0), 1)
        self.assertEqual(s.slot_number(0, 9), 10)

    def test_the_second_page_continues(self):
        s = SlotScreen(proc())
        self.assertEqual(s.slot_number(1, 0), 11)
        self.assertEqual(s.slot_number(1, 4), 15)


class TestPage(unittest.TestCase):
    """The page is READ, from sfall's own offset. It used to be counted from
    the mod's own clicks, which is how it came to announce slots 1 to 10 over a
    screen showing 81 to 90."""

    def test_the_offset_is_slots_not_pages(self):
        self.assertEqual(SlotScreen(proc(page=0)).page(), 0)
        self.assertEqual(SlotScreen(proc(page=10)).page(), 1)
        self.assertEqual(SlotScreen(proc(page=80)).page(), 8)

    def test_unreadable_is_none_not_zero(self):
        """Zero is a real page. Reporting it when nothing could be read is the
        difference between "I do not know" and a confident wrong slot number."""
        self.assertIsNone(SlotScreen(proc()).page())

    def test_sfall_absent_means_no_page(self):
        self.assertIsNone(SlotScreen(proc(page=10, sfall=None)).page())

    def test_a_value_that_is_not_a_whole_page_is_refused(self):
        self.assertIsNone(SlotScreen(proc(page=13)).page())

    def test_a_negative_or_overlarge_offset_is_refused(self):
        self.assertIsNone(SlotScreen(proc(page=-10)).page())
        self.assertIsNone(SlotScreen(proc(page=MAX_PAGES * 10)).page())

    def test_the_address_follows_the_module_base(self):
        """sfall is a DLL and can be relocated, so the address is its base plus
        an offset -- never the absolute one it happened to load at once."""
        p = proc(page=20, sfall=0x30000000)
        p.values[0x30000000 + 0xEF4B8] = 20
        self.assertEqual(SlotScreen(p).page(), 2)


class TestHeader(unittest.TestCase):
    """What the screen is displaying, read from the engine rather than looked
    up on disk -- so there is no slot number to compute wrongly in between."""

    def test_the_rows_words_are_read(self):
        s = SlotScreen(proc(headers={0: header_bytes("Narg", "at the temple")}))
        self.assertEqual(s.header(0), ("Narg", "at the temple"))

    def test_each_row_is_a_stride_further_on(self):
        s = SlotScreen(proc(headers={3: header_bytes("Chosen", "third")}))
        self.assertEqual(s.header(3), ("Chosen", "third"))
        self.assertEqual(s.header(0), (None, None))

    def test_a_row_without_the_signature_claims_nothing(self):
        """An empty row holds whatever was there before. Reading it as words
        would put a stale description against a slot that is now empty."""
        s = SlotScreen(proc(headers={0: b"\x00" * HEADER_SIZE}))
        self.assertEqual(s.header(0), (None, None))

    def test_an_unreadable_row_claims_nothing(self):
        self.assertEqual(SlotScreen(proc()).header(0), (None, None))


class TestDescribe(unittest.TestCase):
    WORDS = "QUICK: 20/08/2026 - 01:42:25"

    def test_an_occupied_row_reads_out_the_saves_own_words(self):
        self.assertEqual(describe(15, True, self.WORDS),
                         "Slot 15, QUICK: 20/08/2026 - 01:42:25.")

    def test_an_empty_row_says_empty(self):
        self.assertEqual(describe(3, False, ""), "Slot 3, empty.")

    def test_an_occupied_row_with_no_readable_header_is_still_occupied(self):
        """The engine says the row holds a game, so it will be overwritten --
        saying "empty" here is the most expensive wrong sentence available."""
        self.assertEqual(describe(7, True, ""), "Slot 7, a saved game.")

    def test_words_without_the_engine_calling_the_row_taken_are_ignored(self):
        """The occupancy flag is what the screen is drawing, so it wins over a
        header left behind from whatever the row held before."""
        self.assertEqual(describe(15, False, self.WORDS), "Slot 15, empty.")


class TestPagesHolding(unittest.TestCase):
    """Which pages to offer to go to. Slots are 1-based, pages are 0-based, and
    that boundary is exactly where an off-by-one sends a player to the wrong
    page and tells them their saves are gone."""

    def test_the_first_ten_slots_are_page_zero(self):
        self.assertEqual(pages_holding({1, 10}), [0])

    def test_eleven_starts_the_second_page(self):
        self.assertEqual(pages_holding({11, 15, 20}), [1])

    def test_pages_are_reported_once_each_and_in_order(self):
        self.assertEqual(pages_holding({35, 11, 12, 3}), [0, 1, 3])

    def test_nothing_saved_is_no_pages(self):
        self.assertEqual(pages_holding(set()), [])


class FakeScreen:
    """A screen whose page a fake Pager can move."""

    def __init__(self, page=0):
        self._page = page

    def page(self):
        return self._page


class TestPager(unittest.TestCase):
    """Moving between pages, and knowing whether it worked.

    The version before this one decided that from the occupancy flags, which
    say what is ON the page and not which page it is -- so stepping between two
    empty pages looked exactly like a click that failed, and the mod said
    "Could not change page" over a control that was working perfectly.
    """

    class Fake(Pager):
        def __init__(self, screen, pages=MAX_PAGES, drops=0):
            Pager.__init__(self, None, None, None, pages)
            self.SETTLE = 0.01
            self.screen = screen
            self.clicks = []
            self.drops = drops

        def _click(self, code):
            self.clicks.append(code)
            if self.drops > 0:
                self.drops -= 1
                return True          # sent, and went nowhere
            move = {PAGE_NEXT: 1, PAGE_PREV: -1,
                    PAGE_FORWARD_TEN: 10, PAGE_BACK_TEN: -10}[code]
            self.screen._page = (self.screen._page + move) % self.pages
            return True

    def test_one_page_forward_and_back(self):
        screen = FakeScreen(4)
        pager = self.Fake(screen)
        self.assertEqual(pager.step(screen, 1), 5)
        self.assertEqual(pager.step(screen, -1), 4)
        self.assertEqual(pager.clicks, [PAGE_NEXT, PAGE_PREV])

    def test_ten_page_jumps_use_the_outer_buttons(self):
        """These were once guessed to be first and last. They are not, and the
        guess is what made 'first page' land on page 999."""
        screen = FakeScreen(20)
        pager = self.Fake(screen)
        self.assertEqual(pager.step(screen, 10), 30)
        self.assertEqual(pager.step(screen, -10), 20)
        self.assertEqual(pager.clicks, [PAGE_FORWARD_TEN, PAGE_BACK_TEN])

    def test_a_stride_with_no_button_moves_nothing(self):
        screen = FakeScreen(4)
        pager = self.Fake(screen)
        self.assertIsNone(pager.step(screen, 3))
        self.assertEqual(pager.clicks, [])
        self.assertEqual(screen.page(), 4)

    def test_a_lost_click_is_retried_once(self):
        screen = FakeScreen(0)
        pager = self.Fake(screen, drops=1)
        self.assertEqual(pager.step(screen, 1), 1)
        self.assertEqual(len(pager.clicks), 2)

    def test_two_lost_clicks_report_failure_rather_than_guess(self):
        screen = FakeScreen(7)
        pager = self.Fake(screen, drops=2)
        self.assertIsNone(pager.step(screen, 1))
        self.assertEqual(screen.page(), 7)

    def test_an_unreadable_page_sends_no_clicks(self):
        """Without a page to check against, a click cannot be verified -- and an
        unverifiable move on this screen is how a save gets overwritten."""
        class Blind:
            def page(self):
                return None
        pager = self.Fake(FakeScreen(0))
        self.assertIsNone(pager.step(Blind(), 1))
        self.assertEqual(pager.clicks, [])

    def test_goto_spends_the_big_jumps_first(self):
        screen = FakeScreen(0)
        pager = self.Fake(screen)
        self.assertEqual(pager.goto(screen, 23), 23)
        self.assertEqual(pager.clicks,
                         [PAGE_FORWARD_TEN] * 2 + [PAGE_NEXT] * 3)

    def test_goto_already_there_costs_nothing(self):
        screen = FakeScreen(5)
        pager = self.Fake(screen)
        self.assertEqual(pager.goto(screen, 5), 5)
        self.assertEqual(pager.clicks, [])

    def test_goto_wraps_the_short_way_round(self):
        """The control wraps -- measured, 9990 to 0 on one forward step -- so
        page 998 is two steps from page 0, not 998."""
        screen = FakeScreen(998)
        pager = self.Fake(screen)
        self.assertEqual(pager.goto(screen, 0), 0)
        self.assertEqual(pager.clicks, [PAGE_NEXT, PAGE_NEXT])

    def test_goto_gives_up_inside_its_budget(self):
        screen = FakeScreen(0)
        pager = self.Fake(screen, drops=99)
        self.assertIsNone(pager.goto(screen, 40, budget=3))
        # Two clicks per attempt, and it stops rather than clicking for a minute.
        self.assertLessEqual(len(pager.clicks), 6)


if __name__ == "__main__":
    unittest.main()
