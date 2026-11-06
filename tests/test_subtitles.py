"""The subtitles: said when the engine draws them, and not when it throws them away."""

import struct
import unittest

from fallout2_access.game import subtitles as sub
from tests.fakes import FakeMemory

NODES = 0x0C000000
TEXTS = 0x0D000000


def movie(mem, lines, on=True):
    """Lay out a .sve the way the engine parses it. Returns the node addresses."""
    nodes = [NODES + 0x10 * i for i in range(len(lines))]
    for i, (frame, text) in enumerate(lines):
        text_at = TEXTS + 0x100 * i
        mem.poke(text_at, text.encode("cp1252") + b"\x00")
        nxt = nodes[i + 1] if i + 1 < len(nodes) else 0
        mem.poke(nodes[i], struct.pack("<IiI", text_at, frame, nxt))
    mem.set_i32(sub.MOVIE_HEAD, nodes[0] if nodes else 0)
    mem.set_i32(sub.MOVIE_FLAGS, sub.MOVIE_SUBTITLES_ON if on else 0)
    return nodes


class Movies(unittest.TestCase):
    def setUp(self):
        self.mem = FakeMemory()
        self.nodes = movie(self.mem, [(30, "Ahh, you're here.  Good."),
                                      (80, "We've got a problem."),
                                      (117, "A big one.")])
        self.subs = sub.MovieSubtitles()

    def tick(self):
        return self.subs.poll(self.mem)

    def draw(self, upto):
        """The engine drawing and freeing every node before `upto`."""
        self.mem.set_i32(sub.MOVIE_HEAD,
                         self.nodes[upto] if upto < len(self.nodes) else 0)

    def test_nothing_until_a_line_is_drawn(self):
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.tick(), [])

    def test_a_drawn_line_is_said_once_the_movie_is_still_going(self):
        self.tick()
        self.draw(1)
        self.assertEqual(self.tick(), [])   # held for a tick
        self.assertEqual(self.tick(), ["Ahh, you're here.  Good."])
        self.assertEqual(self.tick(), [])

    def test_two_lines_in_one_tick_are_both_said_in_order(self):
        self.tick()
        self.draw(2)
        self.tick()
        self.assertEqual(self.tick(), ["Ahh, you're here.  Good.",
                                       "We've got a problem."])

    def test_the_last_line(self):
        self.tick()
        self.draw(3)
        self.tick()
        self.assertEqual(self.tick(), ["Ahh, you're here.  Good.",
                                       "We've got a problem.", "A big one."])

    def test_a_skipped_movie_says_nothing_more(self):
        self.tick()
        # Closing frees the whole list and then clears the flags, all between
        # one tick and the next.
        self.mem.set_i32(sub.MOVIE_HEAD, 0)
        self.mem.set_i32(sub.MOVIE_FLAGS, 0)
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.tick(), [])

    def test_caught_half_way_through_closing(self):
        self.tick()
        # Read while the closing walk was still freeing nodes, flags not yet
        # cleared...
        self.draw(2)
        self.tick()
        # ...and by the next tick it has finished.
        self.mem.set_i32(sub.MOVIE_HEAD, 0)
        self.mem.set_i32(sub.MOVIE_FLAGS, 0)
        self.assertEqual(self.tick(), [])

    def test_the_line_is_kept_after_the_engine_frees_it(self):
        self.tick()
        self.draw(1)
        # The engine's free leaves garbage where the text was.
        self.mem.poke(TEXTS, b"\xdd\xdd\xdd\x00")
        self.tick()
        self.assertEqual(self.tick(), ["Ahh, you're here.  Good."])

    def test_an_empty_line_clears_the_screen_and_is_not_said(self):
        mem = FakeMemory()
        nodes = movie(mem, [(10, "Simply put."), (20, ""), (30, "No water.")])
        subs = sub.MovieSubtitles()
        subs.poll(mem)
        mem.set_i32(sub.MOVIE_HEAD, nodes[2])
        subs.poll(mem)
        self.assertEqual(subs.poll(mem), ["Simply put."])

    def test_a_new_movie_is_not_progress_through_the_old_one(self):
        self.tick()
        other = movie(self.mem, [(5, "Chosen One.")])
        self.mem.set_i32(sub.MOVIE_HEAD, other[0] + 0x1000)
        self.mem.poke(other[0] + 0x1000, struct.pack("<IiI", TEXTS, 5, 0))
        self.tick()
        self.assertEqual(self.tick(), [])

    def test_subtitles_off(self):
        mem = FakeMemory()
        movie(mem, [(10, "Hello.")], on=False)
        subs = sub.MovieSubtitles()
        self.assertEqual(subs.poll(mem), [])
        mem.set_i32(sub.MOVIE_HEAD, 0)
        self.assertEqual(subs.poll(mem), [])

    def test_a_looping_list_does_not_hang(self):
        mem = FakeMemory()
        nodes = movie(mem, [(1, "a"), (2, "b")])
        mem.poke(nodes[1], struct.pack("<IiI", TEXTS + 0x100, 2, nodes[0]))
        self.assertEqual(sub.MovieSubtitles().poll(mem), [])


class Endings(unittest.TestCase):
    LINES = ["After the Enclave's destruction, the refugees resettled.",
             "Two generations were re-united."]

    def setUp(self):
        self.mem = FakeMemory()
        table = 0x0E000000
        for i, text in enumerate(self.LINES):
            self.mem.poke(TEXTS + 0x100 * i, text.encode("cp1252") + b"\x00")
            self.mem.poke(table + 4 * i, struct.pack("<I", TEXTS + 0x100 * i))
        self.mem.set_i32(sub.ENDING_LINES, table)
        self.mem.set_i32(sub.ENDING_ON, 1)
        self.mem.set_i32(sub.ENDING_COUNT, len(self.LINES))
        self.mem.set_i32(sub.ENDING_CURRENT, 0)
        self.subs = sub.EndingSubtitles()

    def test_each_line_as_it_comes_up(self):
        self.assertEqual(self.subs.poll(self.mem), [self.LINES[0]])
        self.assertEqual(self.subs.poll(self.mem), [])
        self.mem.set_i32(sub.ENDING_CURRENT, 1)
        self.assertEqual(self.subs.poll(self.mem), [self.LINES[1]])
        # Past the last: the slide is waiting out its speech.
        self.mem.set_i32(sub.ENDING_CURRENT, 2)
        self.assertEqual(self.subs.poll(self.mem), [])

    def test_the_next_slide_starts_again_from_its_first_line(self):
        self.subs.poll(self.mem)
        self.mem.set_i32(sub.ENDING_COUNT, 0)
        self.mem.set_i32(sub.ENDING_CURRENT, 0)
        self.assertEqual(self.subs.poll(self.mem), [])
        self.mem.set_i32(sub.ENDING_COUNT, len(self.LINES))
        self.assertEqual(self.subs.poll(self.mem), [self.LINES[0]])

    def test_subtitles_off(self):
        self.mem.set_i32(sub.ENDING_ON, 0)
        self.assertEqual(self.subs.poll(self.mem), [])


if __name__ == "__main__":
    unittest.main()
