"""Character creation: the parts that were silent.

Three separate silences, and the first one is the reason the other two were
hard to notice. Landing on Name, Age or Sex did not merely fail to announce
that control -- it switched the whole editor off, so the next stat stepped to
said nothing either, and the screen looked dead rather than incomplete.
"""

import unittest

from fallout2_access.app import CharGenWatcher
from fallout2_access.game import chargen

from .fakes import memory_with_placed_windows

# The editor panel is a 640x480 art panel centred in a 1024x768 client, which
# is where 192,144 comes from. The three dialogs open directly under their own
# buttons -- measured on a live editor at 209, 346 and 427.
PANEL = (192, 144, 640, 480)
NAME_DIALOG = (209, 144, 139, 72)
AGE_DIALOG = (346, 144, 139, 72)
SEX_DIALOG = (427, 144, 139, 72)


class TestDialogs(unittest.TestCase):
    """Which of the name, age and sex dialogs is open.

    These were the three controls with no way in. The editor's button table
    reads press=-1 for all of them, so they looked mouse-only -- but the editor
    handles N, A and S itself, arrows work inside age and sex, and Escape
    cancels. All three are keyboard-native and always were.
    """

    def _dialog(self, windows):
        mem = memory_with_placed_windows(windows)
        return chargen.CharGen(mem).dialog()

    def test_nothing_open(self):
        self.assertIsNone(self._dialog([PANEL]))

    def test_each_dialog_is_told_apart_by_where_it_sits(self):
        self.assertEqual(self._dialog([PANEL, NAME_DIALOG]), "name")
        self.assertEqual(self._dialog([PANEL, AGE_DIALOG]), "age")
        self.assertEqual(self._dialog([PANEL, SEX_DIALOG]), "sex")

    def test_position_is_read_relative_to_the_panel(self):
        """The panel is centred, so a different resolution moves all four
        together. Absolute positions would name the wrong dialog."""
        shift = 300
        moved = [(l + shift, t, w, h) for (l, t, w, h) in (PANEL, SEX_DIALOG)]
        self.assertEqual(self._dialog(moved), "sex")

    def test_a_dialog_with_no_editor_behind_it_is_not_ours(self):
        """Without the panel there is nothing to measure the offset against,
        and a 139x72 window elsewhere in the game is not one of these three."""
        self.assertIsNone(self._dialog([NAME_DIALOG]))


class TestSexName(unittest.TestCase):
    def test_an_unknown_value_is_not_guessed_at(self):
        """Falls back to the number rather than to English of our own. Saying
        "male" about a value we do not recognise invents the missing half."""
        class _Gen(chargen.CharGen):
            def __init__(self, value):
                self._value = value
                self._msg_cache = {}

            def sex(self):
                return self._value

            def _msg(self, addr):
                return {}

        self.assertEqual(_Gen(7).sex_name(), "sex 7")
        self.assertIsNone(_Gen(None).sex_name())


class _FakeGen:
    """Just enough CharGen to drive is_plausible's callers."""

    def __init__(self, index, stats=(5, 5, 5, 5, 5, 5, 5)):
        self.index = index
        self.stats = list(stats)

    def selection(self):
        return self.index

    def special(self):
        return list(self.stats)


class TestPlausible(unittest.TestCase):
    """`is_plausible` decides whether the editor speaks at all."""

    def _plausible(self, index, stats=(5, 5, 5, 5, 5, 5, 5)):
        return chargen.CharGen.is_plausible(_FakeGen(index, stats))

    def test_a_known_item_is_plausible(self):
        self.assertTrue(self._plausible(0))          # Strength

    def test_an_unmapped_item_does_not_switch_the_editor_off(self):
        """7, 8 and 9 sit between SPECIAL and the condition block, and are
        where Name, Age and Sex are expected to live. They are not in the
        measured index map, and requiring them to be is what muted the whole
        watcher -- including every stat visited afterwards."""
        for index in (7, 8, 9):
            self.assertTrue(self._plausible(index),
                            "index {} muted the editor".format(index))

    def test_nonsense_is_still_rejected(self):
        """The screen test is still a real test. It is the SPECIAL array that
        answers "is this the editor", not the selection index."""
        self.assertFalse(self._plausible(0, stats=(0, 0, 0, 0, 0, 0, 0)))
        self.assertFalse(self._plausible(0, stats=(5, 5, 5)))
        self.assertFalse(self._plausible(None))
        self.assertFalse(self._plausible(-1))


class TestStatRating(unittest.TestCase):
    """The word the editor prints beside each SPECIAL value.

    Message numbers read out of the running game's own stat.msg: 301 "V. Bad"
    through 310 "Heroic", with "Average" on 305 -- which is the value Fallout
    starts every stat at. Ten words, ten values, default in the middle.
    """

    def test_the_default_stat_is_average(self):
        self.assertEqual(chargen.rating_msg(5), 305)

    def test_the_ends_of_the_range(self):
        self.assertEqual(chargen.rating_msg(1), 301)
        self.assertEqual(chargen.rating_msg(10), 310)

    def test_a_bonused_stat_clamps_rather_than_inventing_a_word(self):
        """A stat reaches 14 with bonuses and the game has no word past Heroic.
        Making one up would be inventing English the game does not have."""
        self.assertEqual(chargen.rating_msg(14), 310)
        self.assertEqual(chargen.rating_msg(0), 301)


class TestNameEcho(unittest.TestCase):
    """Typing into the name field.

    The buffer was readable the whole time and simply never watched. What it
    says matters as much as that it says anything: echoing the whole field on
    every keystroke ("C", "Ch", "Cho") is how you stop being able to follow
    your own typing.
    """

    def echo(self, before, after):
        return CharGenWatcher._name_change(before, after)

    def test_a_typed_letter_is_echoed_alone(self):
        self.assertEqual(self.echo("Cho", "Chos"), "s")

    def test_the_first_letter(self):
        self.assertEqual(self.echo(None, "C"), "C")

    def test_a_backspace_says_what_went_and_what_is_left(self):
        self.assertEqual(self.echo("Chos", "Cho"), "s, Cho")

    def test_clearing_the_field(self):
        self.assertEqual(self.echo("Chosen", ""), "Name cleared.")

    def test_anything_else_reads_the_whole_field(self):
        """A paste, or a field replaced wholesale. Then the whole thing really
        is the news."""
        self.assertEqual(self.echo("Chosen", "Narg"), "Name Narg")


if __name__ == "__main__":
    unittest.main()


class TestInGameSections(unittest.TestCase):
    """Sections the creation editor does not have.

    The in-game sheet is the same panel serving a character who exists, and it
    has rows the editor never shows. Tabbing onto them announced nothing at all,
    which is indistinguishable from the key not arriving.
    """

    def test_name_age_and_sex_are_the_gap_in_the_map(self):
        """7, 8 and 9 sat unexplained between SPECIAL and the condition block
        from the day the map was measured. Walking the in-game sheet named
        them."""
        for index, pos in ((7, 0), (8, 1), (9, 2)):
            self.assertEqual(chargen._SECTION_OF[index], ("identity", pos))

    def test_the_perks_karma_kills_box(self):
        """71 Perks, 48 Karma, 46 Kills -- read off the trait pointer while
        stepping those very indices."""
        for index in (46, 47, 48, 54, 71, 135):
            self.assertEqual(chargen._SECTION_OF[index][0], "record")

    def test_the_creation_sections_are_untouched(self):
        self.assertEqual(chargen._SECTION_OF[0], ("special", 0))
        self.assertEqual(chargen._SECTION_OF[10], ("condition", 0))
        self.assertEqual(chargen._SECTION_OF[28], ("skill", 0))
        self.assertEqual(chargen._SECTION_OF[94], ("trait", 13))


class TestLabelText(unittest.TestCase):
    """A label pointer is only trusted when it reads like a label.

    These pointers track one section each and keep whatever they last held
    everywhere else, so off their own section they return a stale label or
    outright rubbish -- measured on the derived block as a run of high bytes.
    A confident wrong label is the one thing this file will not say.
    """

    class _Gen(chargen.CharGen):
        def __init__(self, text):
            self._text = text

        def _ptr_text(self, addr, limit=400):
            return self._text

    def label(self, text):
        return self._Gen(text)._label_text(0)

    def test_a_real_label_is_kept(self):
        self.assertEqual(self.label("Karma"), "Karma")
        self.assertEqual(self.label("Giant Ants Kills"), "Giant Ants Kills")

    def test_high_byte_rubbish_is_refused(self):
        self.assertIsNone(self.label("\xff\xfe\xd0\x19"))

    def test_punctuation_with_no_letters_is_refused(self):
        self.assertIsNone(self.label(">?@APP@"[0:0] + "@?><"))

    def test_nothing_at_all(self):
        self.assertIsNone(self.label(None))
        self.assertIsNone(self.label("   "))

    def test_a_whole_paragraph_is_not_a_label(self):
        self.assertIsNone(self.label("Perks add additional abilities. Every "
                                     "third experience level you may choose"))


class TestModifiedStatsAreNotAnnounced(unittest.TestCase):
    """A modified stat reads as its total, and says nothing about the modifier.

    This briefly announced "Perception, 6, Good, down from 8", on the belief
    that Fallout marks a modified stat by drawing it in a different colour. A
    screenshot of the live sheet says otherwise: the only row drawn differently
    is the SELECTED one -- its rating word is white where the other six are
    green -- and Perception, reduced by two by a drug at that moment, was green
    like the rest.

    So the screen shows the total and nothing more, and saying where the total
    came from would hand a blind player a reference a sighted one does not get.
    """

    def test_the_base_value_is_still_readable_for_the_fallback(self):
        """`special` falls back to it during character creation, where the
        editor's working copy is the character."""
        class _Gen(chargen.CharGen):
            def __init__(self):
                self.sheet = None

            def base_special(self):
                return [5, 8, 3, 7, 5, 8, 4]

        self.assertEqual(_Gen().special(), [5, 8, 3, 7, 5, 8, 4])

    def test_a_modified_stat_reads_as_its_total_and_nothing_more(self):
        """Perception 6 on a character built with 8, which is the live case
        that prompted this. The row says 6 and stops."""
        from fallout2_access.game import charsheet

        sheet = charsheet.Sheet()
        for line in ("CHAR:stats 5|6|3|7|5|8|4|",
                     "CHAR:derived 8|9|150|1|0|15|6|12|1|4|",
                     "CHAR:cond 7|26|19|0|0|",
                     "CHAR:skills " + "|".join(["20"] * 18) + "|",
                     "CHAR:pc 1|765|0|"):
            sheet.handle(line)

        class _Gen(chargen.CharGen):
            def __init__(self):
                self._msg_cache = {}
                self.sheet = sheet

            def selection(self):
                return 1                      # Perception

            def base_special(self):
                return [5, 8, 3, 7, 5, 8, 4]  # built with 8

            def _msg(self, addr):
                return {101: "Perception", 306: "Good"}

        said = _Gen().current().announce()
        self.assertEqual(said, "Perception, 6, Good")
        self.assertNotIn("8", said, "the base value is not on the screen")
