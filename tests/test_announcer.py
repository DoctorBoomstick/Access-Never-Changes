"""Who may cut off whom.

The rule: what you asked for interrupts, what the world did queues up.

Before this existed, everything interrupted, and a burst of lines left only the
last one alive. Captured from a real fight -- a miss was reliably erased by the
action-point count that followed it a moment later, so combat read as a string
of bare numbers with no account of what had happened.
"""

import unittest

from fallout2_access.app import Announcer


class Recorder:
    def __init__(self):
        self.said = []

    def speak(self, text, interrupt=True):
        self.said.append((text, interrupt))

    def silence(self):
        pass


class TestInterruptPolicy(unittest.TestCase):
    def setUp(self):
        self.rec = Recorder()
        self.ann = Announcer(self.rec)

    def test_events_queue_rather_than_cut_each_other_off(self):
        """The reported bug: 'You missed.' then '6.' lost the miss entirely."""
        self.ann.say("You missed.")
        self.ann.say("6.")
        self.assertEqual([i for _t, i in self.rec.said], [False, False])

    def test_a_burst_survives_intact(self):
        for line in ("Giant Ant's turn.", "You were hit for 4 hit points.",
                     "Your turn.", "9 of 9 action points."):
            self.ann.say(line)
        self.assertEqual(len(self.rec.said), 4)
        self.assertFalse(any(i for _t, i in self.rec.said))

    def test_an_answer_interrupts(self):
        self.ann.answer("Torch, west 2 hexes.")
        self.assertEqual(self.rec.said, [("Torch, west 2 hexes.", True)])

    def test_repeated_answers_still_speak(self):
        """Numpad 5 re-reads the hex you are on, so the text is identical every
        time. Silence there is indistinguishable from the key not arriving."""
        self.ann.answer("empty, 1 hex")
        self.ann.answer("empty, 1 hex")
        self.assertEqual(len(self.rec.said), 2)

    def test_repeated_events_are_suppressed(self):
        """A 20Hz poll re-reporting the same state should not repeat itself."""
        self.ann.say("exploring")
        self.ann.say("exploring")
        self.assertEqual(len(self.rec.said), 1)

    def test_forced_events_repeat(self):
        self.ann.say("Moved 1 hex.", force=True)
        self.ann.say("Moved 1 hex.", force=True)
        self.assertEqual(len(self.rec.said), 2)

    def test_whitespace_is_collapsed(self):
        self.ann.say("Giant   Ant\n  hits you")
        self.assertEqual(self.rec.said[0][0], "Giant Ant hits you")

    def test_empty_text_says_nothing(self):
        self.ann.say("")
        self.ann.answer("   ")
        self.assertEqual(self.rec.said, [])


if __name__ == "__main__":
    unittest.main()
