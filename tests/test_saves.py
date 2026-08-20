"""Noticing that a game was saved.

Quick save and quick load already work in the engine -- F6 and F7, no pointer
and no screen -- so the only thing missing was any sign that they had happened.
These tests are mostly about that: a save must be heard, and a save that was
already on disk when the mod started must not be announced as though it had
just occurred.
"""

import os
import tempfile
import time
import unittest

from fallout2_access.game.saves import SAVE_FILE, SaveWatcher


class SaveTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = self.tmp.name
        self.root = os.path.join(self.game, "data", "SAVEGAME")
        os.makedirs(self.root)
        self.w = SaveWatcher(self.game)
        self.clock = 1000.0

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, number, when=None):
        folder = os.path.join(self.root, "SLOT{:02d}".format(number))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, SAVE_FILE)
        with open(path, "wb") as fh:
            fh.write(b"FALLOUT SAVE FILE\x00" + b"\x00" * 64)
        if when is not None:
            os.utime(path, (when, when))
        return path

    def tick(self, step=1.0):
        """Poll, with time moved on past the throttle."""
        self.clock += step
        return self.w.poll(now=self.clock)


class TestScanning(SaveTestCase):
    def test_no_saves_is_said_plainly(self):
        self.assertEqual(self.w.summary(), "No saved games.")

    def test_an_empty_slot_folder_is_not_a_saved_game(self):
        """The folder can exist with nothing in it, and offering that as a game
        to load is how you pick a slot that cannot be loaded."""
        os.makedirs(os.path.join(self.root, "SLOT03"))
        self.assertEqual(self.w.scan(), [])

    def test_slots_are_listed_in_order(self):
        self.write(3)
        self.write(1)
        self.assertEqual([s.number for s in self.w.scan()], [1, 3])

    def test_the_summary_counts_and_names_them(self):
        self.write(1)
        self.write(2)
        text = self.w.summary()
        self.assertIn("2 saved games", text)
        self.assertIn("Slot 1", text)
        self.assertIn("Slot 2", text)

    def test_one_save_is_singular(self):
        self.write(1)
        self.assertIn("1 saved game.", self.w.summary())

    def test_a_missing_savegame_folder_is_not_an_error(self):
        """A game that has never been saved has no folder at all."""
        w = SaveWatcher(os.path.join(self.game, "nowhere"))
        self.assertEqual(w.scan(), [])
        self.assertEqual(w.summary(), "No saved games.")
        self.assertEqual(w.poll(now=1.0), [])


class TestWatching(SaveTestCase):
    def test_the_first_poll_only_takes_stock(self):
        """Saves already on disk at startup are not news, for the same reason
        the message ring's backlog is not read out on attach."""
        self.write(1)
        self.assertEqual(self.tick(), [])

    def test_a_new_save_is_announced(self):
        self.tick()
        self.write(1)
        self.assertEqual(self.tick(), ["Saved to slot 1."])

    def test_it_is_announced_once(self):
        self.tick()
        self.write(1)
        self.tick()
        self.assertEqual(self.tick(), [])

    def test_overwriting_a_slot_is_announced_differently(self):
        """Quick save writes the same slot over and over, and 'saved to slot 1'
        every time hides the one case that matters -- landing on a slot that
        already held something."""
        self.write(1, when=self.clock)
        self.tick()
        self.write(1, when=self.clock + 100)
        self.assertEqual(self.tick(), ["Slot 1 saved over."])

    def test_several_saves_are_all_announced(self):
        self.tick()
        self.write(2)
        self.write(5)
        self.assertEqual(self.tick(), ["Saved to slot 2.", "Saved to slot 5."])

    def test_polling_is_throttled(self):
        """This runs beside a 20Hz loop and must not stat the disk on each."""
        self.tick()
        self.write(1)
        self.assertEqual(self.w.poll(now=self.clock + 0.01), [])

    def test_reset_takes_stock_again(self):
        self.tick()
        self.write(1)
        self.w.reset()
        self.assertEqual(self.w.poll(now=self.clock + 10), [])


class TestSample(SaveTestCase):
    def test_a_real_save_can_be_sampled_for_its_layout(self):
        """Groundwork: the slot description lives in here somewhere, and it
        will be read off a real file rather than guessed at."""
        self.write(1)
        self.assertTrue(self.w.sample(1).startswith(b"FALLOUT SAVE FILE"))

    def test_sampling_an_empty_slot_is_not_an_error(self):
        self.assertEqual(self.w.sample(9), b"")


if __name__ == "__main__":
    unittest.main()
