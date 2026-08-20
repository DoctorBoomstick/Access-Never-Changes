"""Noticing that a game was saved, and reading what a save calls itself.

Quick save and quick load already work in the engine -- F6 and F7, no pointer
and no screen -- so the only thing missing was any sign that they had happened.
Much of this is about that: a save must be heard, and a save that was already on
disk when the mod started must not be announced as though it had just occurred.

The header tests are stricter than the rest of this project, on purpose. A save
slot is the one thing a player can destroy by acting on a wrong description, so
the rule is that anything not positively understood is not described at all --
the number and the time come from the filesystem and cannot be misparsed.
"""

import os
import tempfile
import time
import unittest

from fallout2_access.game.saves import (
    OFF_CHARACTER,
    OFF_DESCRIPTION,
    SAVE_FILE,
    SIGNATURE,
    SaveWatcher,
)

NUL = chr(0)


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

    def write(self, number, when=None, character="Narg", description="",
              signature=SIGNATURE):
        """A save file with a header laid out the way the engine writes one."""
        folder = os.path.join(self.root, "SLOT{:02d}".format(number))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, SAVE_FILE)
        head = bytearray(256)
        head[0:len(signature)] = signature
        head[OFF_CHARACTER:OFF_CHARACTER + len(character)] = character.encode("cp1252")
        body = description.encode("cp1252")
        head[OFF_DESCRIPTION:OFF_DESCRIPTION + len(body)] = body
        with open(path, "wb") as fh:
            fh.write(bytes(head))
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


class TestHeaders(SaveTestCase):
    """Reading what a save calls itself.

    The layout was taken from five real saves, all of which agreed: the
    signature at the start, the character name at 29, the description at 61.
    """

    def test_the_description_is_read_and_led_with(self):
        self.write(3, description="QUICK: 20/08/2026 - 01:42:25")
        self.assertEqual(self.w.slot(3).announce(),
                         "Slot 3, QUICK: 20/08/2026 - 01:42:25.")

    def test_the_character_name_is_read(self):
        self.write(3, character="Narg")
        self.assertEqual(self.w.slot(3).character, "Narg")

    def test_a_slot_with_no_description_falls_back_to_its_time(self):
        self.write(6)
        self.assertIn("Slot 6, saved", self.w.slot(6).announce())

    def test_a_file_without_the_signature_is_not_described(self):
        """Better the number and the time -- which come from the filesystem and
        cannot be misparsed -- than bytes whose meaning was assumed."""
        self.write(4, description="not a real save", signature=b"NOPE")
        slot = self.w.slot(4)
        self.assertEqual(slot.description, "")
        self.assertIn("Slot 4, saved", slot.announce())

    def test_an_unprintable_description_is_refused(self):
        """A wrong offset on some other build would produce exactly this, and a
        mangled description on a save slot is worse than none."""
        self.write(5, description="bad" + chr(1) + chr(2) + "text")
        self.assertEqual(self.w.slot(5).description, "")

    def test_the_name_stops_at_its_terminator(self):
        """Fixed-width fields padded with NULs -- reading the whole field would
        drag the next one in behind it."""
        self.write(7, character="Narg", description="Temple")
        self.assertEqual(self.w.slot(7).character, "Narg")

    def test_a_missing_slot_is_none_not_a_guess(self):
        self.assertIsNone(self.w.slot(9))


class TestSample(SaveTestCase):
    def test_a_real_save_can_be_sampled(self):
        self.write(1)
        self.assertTrue(self.w.sample(1).startswith(SIGNATURE))

    def test_sampling_an_empty_slot_is_not_an_error(self):
        self.assertEqual(self.w.sample(9), b"")


if __name__ == "__main__":
    unittest.main()
