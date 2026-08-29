"""Parsing the interface bar's message ring.

Layout established by planting a known string in the live game and looking at
where it landed: 256-byte records, text at +8, an optional colour byte with the
high bit set in front of the text, NUL terminated, and exactly 100 records.

The fixtures below are built from real captured lines -- the Temple of Trials
description arrives without a colour byte, script messages arrive with one, and
that difference is exactly what an off-by-one in the anchor would hide. It is
also what tells a wrapped continuation line from the start of a new message.

The ring is the point of most of this file. It holds 100 records and then does
something -- append stops being possible and the engine either scrolls or wraps.
The reader is not told which; it works it out from consecutive snapshots. So
each of the three behaviours is exercised here, because "we never found out
which one it is" is precisely the state the code was written to survive.
"""

import unittest

from fallout2_access.game.displaywin import (
    CAPACITY,
    RECORD,
    TEXT_OFFSET,
    DisplayWindow,
    _record_text,
)


def record(text: bytes, colour: bool = False) -> bytes:
    body = (b"\x95" if colour else b"") + text + b"\x00"
    rec = b"\x00" * TEXT_OFFSET + body
    return rec + b"\x00" * (RECORD - len(rec))


EMPTY = b"\x00" * RECORD


class FakeRing:
    """A process holding one 100-record message ring."""

    def __init__(self, base: int) -> None:
        self.base = base
        self.slots = [EMPTY] * CAPACITY

    # -- what the engine does to it ---------------------------------------

    def append(self, *records: bytes) -> None:
        """Write into the next free slots, as the engine does until it is full."""
        for rec in records:
            self.slots[self.slots.index(EMPTY)] = rec

    def scroll(self, *records: bytes) -> None:
        """Shift everything up and write the new lines at the end."""
        for rec in records:
            self.slots = self.slots[1:] + [rec]

    def wrap(self, at: int, *records: bytes) -> None:
        """Overwrite in place, running off the end and back to the start."""
        for i, rec in enumerate(records):
            self.slots[(at + i) % CAPACITY] = rec

    # -- process interface -------------------------------------------------

    @property
    def blob(self) -> bytes:
        return b"".join(self.slots)

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
        self.assertEqual(_record_text(EMPTY), "")

    def test_truncated_record(self):
        self.assertEqual(_record_text(b"\x00" * 4), "")

    # -- records that are not messages at all ------------------------------
    #
    # cp1252 decodes very nearly any byte, so "it decoded" was being taken for
    # "it is text". Seen live: once the anchor this window is read from goes
    # stale, every poll finds heap noise, and it was spoken -- "D?", "pE?",
    # over and over, on top of everything else the mod had to say. The cause is
    # upstream and is not fixed by these; refusing to speak what cannot be a
    # sentence is.

    def test_an_accented_sentence_still_arrives(self):
        """A translated game writes these, and they are not noise."""
        text = "Vous voyez : une porte.".encode("cp1252")
        self.assertEqual(_record_text(record(text)), text.decode("cp1252"))

    def test_control_characters_are_not_prose(self):
        self.assertEqual(_record_text(record(b"D\x01\x02\x03")), "")

    def test_a_two_character_scrap_is_not_a_message(self):
        """The engine does not write one- or two-character lines."""
        self.assertEqual(_record_text(record(b"pE")), "")

    def test_mostly_high_bytes_are_not_a_message(self):
        self.assertEqual(
            _record_text(record(b"\x8a\x9e\x9f\xd0\xd8\xf0\xfe")), "")


class RingTestCase(unittest.TestCase):
    """A located reader sitting on a ring that holds only the beacon."""

    def setUp(self):
        self.base = 0x00800000
        self.ring = FakeRing(self.base)
        self.ring.append(record(b"Access Never Changes ready.", colour=True))
        self.win = DisplayWindow(self.ring)
        self.assertTrue(self.win.locate())
        self.assertEqual(self.win.poll(), [])   # first look adopts in silence

    def settled(self):
        """Poll, then poll again to release the held final message."""
        out = self.win.poll()
        return out + self.win.poll()


class TestLocating(RingTestCase):
    def test_anchors_on_the_beacon_record(self):
        self.assertEqual(self.win.anchor, self.base)

    def test_missing_beacon_is_not_an_error(self):
        """Before a game loads the beacon has not been printed, and that is a
        normal state rather than a failure."""
        win = DisplayWindow(FakeRing(self.base))
        self.assertFalse(win.locate())
        self.assertFalse(win.located)
        self.assertEqual(win.poll(), [])

    def test_what_was_already_there_is_not_narrated(self):
        """Attaching mid-session must not read out the last hour as news."""
        ring = FakeRing(self.base)
        ring.append(
            record(b"Access Never Changes ready.", colour=True),
            record(b"You see: a door.", colour=True),
            record(b"It is locked.", colour=True),
        )
        win = DisplayWindow(ring)
        self.assertTrue(win.locate())
        self.assertEqual(win.poll(), [])

    def test_a_beacon_partway_into_the_ring_still_anchors_at_the_start(self):
        """If the ring is not reallocated on a save load, the second session's
        beacon lands partway in -- and anchoring there would put every read that
        many records past the end of the ring, which is the original bug."""
        ring = FakeRing(self.base)
        ring.append(
            record(b"You see: a door.", colour=True),
            record(b"It is locked.", colour=True),
            record(b"Access Never Changes ready.", colour=True),
        )
        win = DisplayWindow(ring)
        self.assertTrue(win.locate())
        self.assertEqual(win.anchor, self.base)

    def test_reset_forgets_a_stale_anchor(self):
        self.win.reset()
        self.assertFalse(self.win.located)
        self.assertEqual(self.win.poll(), [])


class TestAppending(RingTestCase):
    def test_a_new_line_is_reported(self):
        self.ring.append(record(b"You see: a door.", colour=True))
        self.assertEqual(self.settled(), ["You see: a door."])

    def test_lines_are_reported_once(self):
        self.ring.append(record(b"You see: a door.", colour=True))
        self.settled()
        self.assertEqual(self.win.poll(), [])

    def test_several_at_once_keep_their_order(self):
        self.ring.append(
            record(b"You missed.", colour=True),
            record(b"Giant Ant was hit for 4 hit points.", colour=True),
            record(b"Giant Ant was hit for 1 hit point and was killed.", colour=True),
        )
        self.assertEqual(
            self.settled(),
            [
                "You missed.",
                "Giant Ant was hit for 4 hit points.",
                "Giant Ant was hit for 1 hit point and was killed.",
            ],
        )

    def test_repeated_identical_lines_are_all_reported(self):
        """Looting a pot writes 'You search the Pot.' over and over, and each
        one is a real event -- suppressing duplicates would hide half of them."""
        self.ring.append(*[record(b"You search the Pot.", colour=True)] * 3)
        self.assertEqual(self.settled(), ["You search the Pot."] * 3)


class TestWrappedMessages(RingTestCase):
    """The engine breaks one long message over several records, and only the
    first carries the colour byte."""

    def test_continuation_lines_join_the_sentence(self):
        self.ring.append(
            record(b"For destroying your enemies without taking a", colour=True),
            record(b"scratch,  you earn 25 exp. points."),
        )
        self.assertEqual(
            self.settled(),
            ["For destroying your enemies without taking a "
             "scratch,  you earn 25 exp. points."],
        )

    def test_three_line_message(self):
        self.ring.append(
            record(b"You are in a dark, musty temple. The shadows seem", colour=True),
            record(b"to play tricks with your eyes, and you can hear the"),
            record(b"faint sound of movement."),
        )
        self.assertEqual(
            self.settled(),
            ["You are in a dark, musty temple. The shadows seem "
             "to play tricks with your eyes, and you can hear the "
             "faint sound of movement."],
        )

    def test_a_continuation_landing_a_poll_later_still_joins(self):
        """The held-back tail. Both records normally arrive in one frame, but a
        poll can fall between them, and a fragment spoken on its own is exactly
        the thing this is meant to prevent."""
        self.ring.append(record(b"For slaying your opponents,  you earn 25 exp.",
                                colour=True))
        self.assertEqual(self.win.poll(), [])       # held, not yet spoken
        self.ring.append(record(b"points."))
        self.assertEqual(self.settled(),
                         ["For slaying your opponents,  you earn 25 exp. points."])

    def test_the_next_message_releases_the_one_before(self):
        self.ring.append(record(b"You missed.", colour=True))
        self.assertEqual(self.win.poll(), [])
        self.ring.append(record(b"You see: Narg.", colour=True))
        self.assertEqual(self.win.poll(), ["You missed."])
        self.assertEqual(self.win.poll(), ["You see: Narg."])


class TestFullRing(RingTestCase):
    """What happens at message 100 -- the failure this file was rewritten for.

    The reader is not told whether the engine scrolls or wraps, so both are
    tested. Under the old index-only reader either one silenced the game's own
    words for the rest of the session.
    """

    def fill(self):
        """Take the ring right up to its last free slot."""
        for i in range(CAPACITY - 1):
            self.ring.append(record("line {}".format(i).encode(), colour=True))
        self.settled()

    def test_the_ring_is_full(self):
        self.fill()
        self.assertNotIn(EMPTY, self.ring.slots)

    def test_scrolling_past_the_end_still_speaks(self):
        self.fill()
        self.ring.scroll(record(b"Giant Ant hits you for 7.", colour=True))
        self.assertEqual(self.settled(), ["Giant Ant hits you for 7."])

    def test_scrolling_several_at_once_keeps_their_order(self):
        self.fill()
        self.ring.scroll(
            record(b"You missed.", colour=True),
            record(b"Giant Ant dies.", colour=True),
        )
        self.assertEqual(self.settled(), ["You missed.", "Giant Ant dies."])

    def test_wrapping_past_the_end_still_speaks(self):
        self.fill()
        self.ring.wrap(0, record(b"Giant Ant hits you for 7.", colour=True))
        self.assertEqual(self.settled(), ["Giant Ant hits you for 7."])

    def test_a_write_straddling_the_end_keeps_its_order(self):
        """The run of new records runs off the end of the array and back to the
        start, so ring order and writing order are not the same thing."""
        self.fill()
        self.ring.wrap(
            CAPACITY - 2,
            record(b"You missed.", colour=True),
            record(b"Giant Ant was hit for 4 hit points.", colour=True),
            record(b"Giant Ant dies.", colour=True),
        )
        self.assertEqual(
            self.settled(),
            ["You missed.", "Giant Ant was hit for 4 hit points.", "Giant Ant dies."],
        )

    def test_a_wrapped_message_still_joins_across_the_end(self):
        self.fill()
        self.ring.wrap(
            CAPACITY - 1,
            record(b"For slaying your opponents,  you earn 25 exp.", colour=True),
            record(b"points."),
        )
        self.assertEqual(
            self.settled(),
            ["For slaying your opponents,  you earn 25 exp. points."],
        )

    def test_it_never_reads_past_the_ring(self):
        """The bug itself: an index that only grows walks into the next heap
        block. Nothing here may look beyond the hundredth record."""
        reads = []
        real = self.ring.read_chunked

        def watched(addr, size):
            reads.append((addr, size))
            return real(addr, size)

        self.ring.read_chunked = watched
        self.fill()
        for _ in range(20):
            self.ring.scroll(record(b"and another.", colour=True))
            self.settled()
        end = self.base + CAPACITY * RECORD
        for addr, size in reads:
            self.assertLessEqual(addr + size, end)


if __name__ == "__main__":
    unittest.main()
