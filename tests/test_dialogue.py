"""The dialogue screen.

The cases here are the ones a player cannot check for themselves: a reply list
that is really the *last* conversation's, a number that no longer matches the
key that chooses it, and a conversation that loops back to the line it just
said. All three produce announcements that sound entirely reasonable.
"""

from __future__ import annotations

import unittest

from fallout2_access.game import dialogue

from .fakes import memory_with_dialogue

GREETING = "Greetings, Chosen One! It is good to see you."


class CleanTest(unittest.TestCase):
    def test_strips_the_bullet(self):
        self.assertEqual(dialogue.clean("• Just saying hello"),
                         "Just saying hello")

    def test_keeps_the_game_s_own_punctuation(self):
        # "[Done]" is what is on screen, brackets and all. They are the game's
        # words; inventing tidier ones is how a mod stops matching the game.
        self.assertEqual(dialogue.clean("• [Done]"), "[Done]")

    def test_survives_text_with_no_bullet(self):
        self.assertEqual(dialogue.clean("  Plain  "), "Plain")


class ReadTest(unittest.TestCase):
    def test_reads_a_conversation(self):
        mem = memory_with_dialogue(GREETING, ["Say hello", "[Done]"])
        reading = dialogue.Dialogue(mem).read()
        self.assertEqual(reading.reply, GREETING)
        self.assertEqual(reading.options, ["Say hello", "[Done]"])

    def test_stops_at_the_count(self):
        """The array is never cleared, only overwritten.

        Five replies are readable; the engine says there are two. Believing the
        array over the count means offering three replies from a conversation
        that has already ended -- and they read perfectly.
        """
        mem = memory_with_dialogue(
            GREETING,
            ["Yes", "No", "Tell me about the temple", "Buy something", "[Done]"],
            count=2)
        reading = dialogue.Dialogue(mem).read()
        self.assertEqual(reading.options, ["Yes", "No"])

    def test_an_unreadable_reply_keeps_its_number(self):
        """Reply three is chosen by pressing 3, readable or not.

        Closing the gap would renumber every reply below it, so the player
        would press the number they were told and say something else entirely.
        """
        mem = memory_with_dialogue(GREETING, ["Yes", "", "No"])
        reading = dialogue.Dialogue(mem).read()
        self.assertEqual(len(reading.options), 3)
        self.assertEqual(reading.options[2], "No")
        self.assertIn("3, No", dialogue.say_options(reading.options))

    def test_no_conversation_reads_as_nothing(self):
        mem = memory_with_dialogue("", [], msglist=0, msgid=0)
        reading = dialogue.Dialogue(mem).read()
        self.assertEqual(reading.options, [])
        self.assertEqual(reading.reply, "")


class ChangeTest(unittest.TestCase):
    def test_the_same_line_with_different_replies_is_a_change(self):
        """A conversation that loops back says the same thing again.

        Keyed on the message id alone, the second visit to a line is silence --
        and silence after a keypress is indistinguishable from the key never
        having arrived, which is the misreading this whole project keeps
        designing against.
        """
        first = dialogue.Dialogue(
            memory_with_dialogue(GREETING, ["Ask about the temple", "[Done]"])
        ).read()
        second = dialogue.Dialogue(
            memory_with_dialogue(GREETING, ["[Done]"])
        ).read()
        self.assertEqual((first.msglist, first.msgid),
                         (second.msglist, second.msgid))
        self.assertNotEqual(first.key(), second.key())

    def test_the_engine_s_done_entry_is_recognisable(self):
        mem = memory_with_dialogue("Farewell.", ["[Done]"], msglist=-2, msgid=-2)
        self.assertTrue(dialogue.Dialogue(mem).read().ending)


class LeavingTest(unittest.TestCase):
    """What happens on the way out of a conversation.

    Choosing [Done] does not close the screen in one frame. The engine empties
    the reply list while the NPC's last line is still in memory and the game
    mode still reads DIALOG, and that transient holds steady long enough to be
    believed -- so the mod announced it, which read as the character repeating
    their last line at you as you walked away.
    """

    def _watcher(self, mem, mode):
        from fallout2_access.app import Announcer, WorldWatcher

        class _Log:
            path = "debug.log"
            last_hex = None

            def poll(self):
                return []

        class _Speaker:
            def __init__(self):
                self.said = []

            def speak(self, text, interrupt=False):
                self.said.append(text)

        log = _Log()
        log.game_mode = mode
        watcher = WorldWatcher(log, None, mem)
        speaker = _Speaker()
        return watcher, Announcer(speaker), speaker

    def test_the_last_line_is_not_repeated_on_the_way_out(self):
        from fallout2_access.game import screens

        mem = memory_with_dialogue(GREETING, ["Say hello", "[Done]"])
        watcher, ann, speaker = self._watcher(mem, screens.MODE_DIALOG)

        # Settle into the conversation: it takes DIALOGUE_STABLE_TICKS polls
        # before anything is believed.
        for _ in range(4):
            watcher._pump_dialogue(ann)
        self.assertTrue(any(GREETING[:20] in s for s in speaker.said))
        spoken = len(speaker.said)

        # [Done] chosen. The replies go first; the line is still sitting there.
        mem.set_i32(dialogue.OPTION_COUNT, 0)
        for _ in range(4):
            watcher._pump_dialogue(ann)
        self.assertEqual(len(speaker.said), spoken,
                         "the torn-down screen was announced: {!r}"
                         .format(speaker.said[spoken:]))

    def test_nothing_is_said_when_the_conversation_closes(self):
        """"Conversation over." was the mod's own sentence. The mode change back
        to the map is announced on its own and says where the player now is."""
        from fallout2_access.game import screens

        mem = memory_with_dialogue(GREETING, ["Say hello"])
        watcher, ann, speaker = self._watcher(mem, screens.MODE_DIALOG)
        for _ in range(4):
            watcher._pump_dialogue(ann)
        speaker.said.clear()

        watcher.log.game_mode = 0          # back to the map
        watcher._pump_dialogue(ann)
        self.assertEqual(speaker.said, [])


class SayTest(unittest.TestCase):
    def test_numbers_are_the_keys_that_press_them(self):
        said = dialogue.say_options(["Yes", "No", "[Done]"])
        self.assertTrue(said.startswith("3 replies."))
        self.assertIn("1, Yes.", said)
        self.assertIn("3, [Done].", said)

    def test_one_reply_reads_as_one(self):
        self.assertTrue(dialogue.say_options(["[Done]"]).startswith("One reply."))

    def test_no_replies_says_so(self):
        self.assertEqual(dialogue.say_options([]), "No replies offered.")

    def test_a_stepped_reply_says_which_number_it_is(self):
        # The number is not decoration: it is the key that says this line.
        self.assertEqual(dialogue.say_option(2, ["a", "b", "c", "d"]),
                         "3 of 4. c")

    def test_stepping_past_the_end_clamps(self):
        # Clamped rather than wrapped, and clamped rather than raising: every
        # entry here is something about to be said to somebody.
        self.assertEqual(dialogue.say_option(9, ["a", "b"]), "2 of 2. b")
        self.assertEqual(dialogue.say_option(-3, ["a", "b"]), "1 of 2. a")

    def test_stepping_with_no_replies(self):
        self.assertEqual(dialogue.say_option(0, []), "No replies offered.")

    def test_the_line_comes_before_the_answers(self):
        reading = dialogue.Dialogue(
            memory_with_dialogue(GREETING, ["Say hello"])).read()
        said = dialogue.say_reading(reading, opening=True, hint=True)
        self.assertLess(said.index("Greetings"), said.index("Say hello"))
        self.assertTrue(said.startswith("Conversation."))
        self.assertTrue(said.endswith(dialogue.hint_text()))

    def test_a_later_line_does_not_reintroduce_itself(self):
        reading = dialogue.Dialogue(
            memory_with_dialogue(GREETING, ["Say hello"])).read()
        said = dialogue.say_reading(reading)
        self.assertNotIn("Conversation.", said)
        self.assertNotIn(dialogue.hint_text(), said)


if __name__ == "__main__":
    unittest.main()
