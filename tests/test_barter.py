"""Pressing OFFER, and knowing it is there to press.

The barter screen's OFFER button carries event code 109, which is below 256 and
therefore looks like the `m` key. It is not: pressing `m` does nothing at all,
while `t` -- code 116, on the same panel -- really does close the barter. So one
of the pair answers its key and the other does not, and only trying settled
which.

That is the counterpart to the loot window's TAKE ALL, which taught the opposite
lesson: code 65 and the `A` key really did press it. `uiwindow` says what a code
below 256 means and what it does not, and this is the case that proves the
warning was worth writing.
"""

import unittest

from fallout2_access.game import barter
from tests import fakes


class FindingThePanel(unittest.TestCase):
    def test_it_needs_both_buttons(self):
        """The dialogue screen puts up a panel of this size without a barter on
        it, and clicking where OFFER would be is not a thing to do on a guess.
        """
        mem = fakes.memory_with_release_windows(
            [(barter.PANEL_WIDTH, barter.PANEL_HEIGHT,
              [(barter.OFFER_CODE, 40, 163), (barter.TALK_CODE, 583, 162)])])
        self.assertTrue(barter.offering(mem))

    def test_offer_alone_is_not_a_barter(self):
        mem = fakes.memory_with_release_windows(
            [(barter.PANEL_WIDTH, barter.PANEL_HEIGHT,
              [(barter.OFFER_CODE, 40, 163)])])
        self.assertFalse(barter.offering(mem))

    def test_a_panel_of_the_wrong_size_is_not_it(self):
        mem = fakes.memory_with_release_windows(
            [(640, 480, [(barter.OFFER_CODE, 40, 163),
                         (barter.TALK_CODE, 583, 162)])])
        self.assertFalse(barter.offering(mem))

    def test_no_windows_at_all(self):
        self.assertFalse(barter.offering(fakes.FakeMemory()))

    def test_offering_declines_rather_than_clicking_blind(self):
        ok, why = barter.offer(fakes.FakeMemory(), hwnd=1)
        self.assertFalse(ok)
        self.assertIn("not bartering", why)


class TheCodes(unittest.TestCase):
    def test_offer_and_talk_are_different_buttons(self):
        self.assertNotEqual(barter.OFFER_CODE, barter.TALK_CODE)

    def test_they_are_the_codes_measured_on_the_live_screen(self):
        """Both were read off the running game's own button list."""
        self.assertEqual(barter.OFFER_CODE, 109)
        self.assertEqual(barter.TALK_CODE, 116)


class TheQuantityWindowDoesNotEndTheBarter(unittest.TestCase):
    """Coming back from "Move Items" must not read as the barter closing.

    That window is a panel drawn OVER the barter screen, so the barter's mode
    bit never clears and gl_inven.ssl never sees a change -- which means it
    never announces the window a second time. The mod, meanwhile, treated the
    return as arriving on the map and cleared what the script had told it,
    permanently.

    Everything that then went wrong went wrong somewhere else, which is why it
    took a while to find. `open` false made `talking()` true, so up and down
    walked the conversation's reply list -- the replies waiting for AFTER the
    trade -- while left and right went on stepping the item lists perfectly,
    because those are the in-game script's keys and never reach the mod at all.
    And `rect` and `side` going None made every attempt to move an item answer
    "Nothing selected."
    """

    def _watcher(self, mode):
        from fallout2_access.app import WorldWatcher

        class _Log:
            path = "debug.log"
            last_hex = None
            game_mode = 0

            def poll(self):
                return []

        log = _Log()
        log.game_mode = mode
        watcher = WorldWatcher(log)
        # As if the script had announced the barter: this is the state the mod
        # is given once and never again.
        watcher.inventory.open = True
        watcher.inventory.rect = (262, 145, 499, 377)
        watcher.inventory.side = 0
        return watcher

    def test_the_barter_survives_a_trip_through_the_counter(self):
        from fallout2_access.game import screens

        w = self._watcher(screens.MODE_DIALOG | screens.MODE_BARTER)
        w.reset()
        self.assertTrue(w.inventory.open)
        self.assertIsNotNone(w.inventory.rect)
        self.assertIsNotNone(w.inventory.side)

    def test_an_ordinary_inventory_survives_it_too(self):
        from fallout2_access.game import screens

        w = self._watcher(screens.MODE_INVENTORY)
        w.reset()
        self.assertTrue(w.inventory.open)

    def test_coming_back_to_the_map_still_clears_it(self):
        """The reading is only kept while the engine says the window is there.
        Nothing here is a licence to hold a stale one."""
        w = self._watcher(0)
        w.reset()
        self.assertFalse(w.inventory.open)
        self.assertIsNone(w.inventory.rect)

    def test_a_trade_is_never_read_as_a_conversation(self):
        """`talking()` decides whether up and down belong to the reply list.
        It asks the game mode now as well as the mod's own latch, so even a
        latch that has been cleared wrongly cannot hand the arrows away."""
        from fallout2_access.game import screens

        w = self._watcher(screens.MODE_DIALOG | screens.MODE_BARTER)
        w.dialogue = object()
        w.inventory.open = False           # the latch cleared, as it used to be
        self.assertFalse(w.talking())

    def test_a_real_conversation_still_talks(self):
        from fallout2_access.game import screens

        w = self._watcher(screens.MODE_DIALOG)
        w.dialogue = object()
        w.inventory.open = False
        self.assertTrue(w.talking())


if __name__ == "__main__":
    unittest.main()
