"""The Pip-Boy: its controls, its rows, and its clock."""

from __future__ import annotations

import datetime
import struct
import unittest

from fallout2_access.game import pipboy, screens

from . import fakes


# The alarm clock as it was measured on a live game: thirteen rows, codes 510
# to 522, twenty pixels apart, starting at y=96.
ALARM_ROWS = [(510 + i, 96 + 20 * i) for i in range(13)]

# The status page as it was measured: two rows, codes 507 and 508.
STATUS_ROWS = [(507, 66), (508, 86)]


class Panel(unittest.TestCase):
    def test_the_panel_is_found_by_its_status_light(self):
        mem = fakes.memory_with_pipboy()
        self.assertTrue(pipboy.showing(mem))

    def test_another_640_by_480_panel_is_not_the_pipboy(self):
        """The character sheet and the save screen are this size too.

        Claiming one of them would not merely mis-name a screen: the Pip-Boy's
        watcher would then own the keyboard on a screen that is not the
        Pip-Boy, and numpad plus would start clicking at rectangles that belong
        to something else.
        """
        mem = fakes.memory_with_release_windows([(640, 480, [(1357, 0, 0)])])
        self.assertFalse(pipboy.showing(mem))

    def test_a_closed_panel_is_not_showing(self):
        mem = fakes.memory_with_pipboy()
        fakes.close_top_window(mem)
        self.assertFalse(pipboy.showing(mem))

    def test_the_five_destinations_come_back_in_screen_order(self):
        win = pipboy.window(fakes.memory_with_pipboy())
        self.assertEqual([code for code, _b in pipboy.destinations(win)],
                         list(pipboy.DESTINATIONS))

    def test_a_button_carrying_its_code_in_release_is_still_found(self):
        """Every Pip-Boy control has -1 in `press`.

        This is the whole reason `Button.release` exists. A reader that only
        consulted `press` saw a panel with twenty buttons as a panel with none.
        """
        win = pipboy.window(fakes.memory_with_pipboy())
        self.assertIsNone(win.by_press(pipboy.STATUS))
        self.assertIsNotNone(win.by_code(pipboy.STATUS))


class Rows(unittest.TestCase):
    def test_a_fresh_panel_has_no_rows(self):
        win = pipboy.window(fakes.memory_with_pipboy())
        self.assertEqual(pipboy.rows(win), [])

    def test_rows_come_back_top_to_bottom(self):
        win = pipboy.window(fakes.memory_with_pipboy(rows=ALARM_ROWS))
        got = pipboy.rows(win)
        self.assertEqual([b.release for b in got], [510 + i for i in range(13)])
        self.assertEqual([b.top for b in got], [96 + 20 * i for i in range(13)])

    def test_an_earlier_pages_leftover_rows_are_not_counted(self):
        """The engine does not destroy a page's rows when you leave it.

        Measured: open STATUS, then the alarm clock, and the panel holds both
        sets. Counting the leftovers would say the alarm clock offers fifteen
        ways to rest and would name every one of them wrongly.
        """
        mem = fakes.memory_with_pipboy(rows=ALARM_ROWS, stale=STATUS_ROWS)
        got = pipboy.rows(pipboy.window(mem))
        self.assertEqual(len(got), 13)
        self.assertEqual(got[0].release, 510)

    def test_a_leftover_page_that_continues_the_numbering_is_still_excluded(self):
        """The case codes alone would get wrong.

        A stale page whose rows end at 509 sits directly below a live page that
        starts at 510, so "the codes keep counting down" is satisfied straight
        through the join. It is reachable as soon as a player has three quest
        locations. The row grid is what separates them: two pages never put
        their rows on the same twenty-pixel ladder.
        """
        stale = [(507, 66), (508, 86), (509, 106)]
        mem = fakes.memory_with_pipboy(rows=ALARM_ROWS, stale=stale)
        got = pipboy.rows(pipboy.window(mem))
        self.assertEqual(len(got), 13)
        self.assertEqual([b.release for b in got],
                         [510 + i for i in range(13)])

    def test_a_page_rendered_twice_is_not_counted_twice(self):
        """Clicking the page you are already on adds a second set of rows.

        Measured, by opening STATUS twice: 507 and 508 arrive again on top of
        the first pair.
        """
        mem = fakes.memory_with_pipboy(rows=STATUS_ROWS, stale=STATUS_ROWS)
        self.assertEqual(len(pipboy.rows(pipboy.window(mem))), 2)


class RestOptions(unittest.TestCase):
    def test_thirteen_rows_are_the_fourteen_options_less_the_party_one(self):
        win = pipboy.window(fakes.memory_with_pipboy(rows=ALARM_ROWS))
        self.assertEqual(pipboy.rest_numbers(pipboy.rows(win)),
                         list(range(302, 315)))

    def test_fourteen_rows_include_resting_until_the_party_is_healed(self):
        rows = [(510 + i, 96 + 20 * i) for i in range(14)]
        win = pipboy.window(fakes.memory_with_pipboy(rows=rows))
        self.assertEqual(pipboy.rest_numbers(pipboy.rows(win))[-1],
                         pipboy.REST_LAST)

    def test_a_row_count_the_rule_cannot_explain_is_refused(self):
        """Naming these by position is a rule, not a reading.

        So a page that does not fit the rule gets no names at all. Being wrong
        here rests somebody for six hours when they asked for ten minutes.
        """
        rows = [(510 + i, 96 + 20 * i) for i in range(5)]
        win = pipboy.window(fakes.memory_with_pipboy(rows=rows))
        self.assertIsNone(pipboy.rest_numbers(pipboy.rows(win)))

    def test_the_status_page_is_not_mistaken_for_the_alarm_clock(self):
        win = pipboy.window(fakes.memory_with_pipboy(rows=STATUS_ROWS))
        self.assertFalse(pipboy.is_alarm_page(pipboy.rows(win)))
        self.assertIsNone(pipboy.rest_numbers(pipboy.rows(win)))


# Three real saves, read out of their SAVE.DAT headers: the raw tick count the
# engine stored, and the date the engine wrote beside it. The arithmetic in
# pipboy.py has to agree with all three, which is what makes the epoch a
# measurement rather than a guess.
REAL_SAVES = [
    (302677, datetime.date(2241, 7, 25)),
    (322141, datetime.date(2241, 7, 25)),
    (1488625, datetime.date(2241, 7, 26)),
]


class Clock(unittest.TestCase):
    def test_the_date_agrees_with_what_the_engine_wrote_in_three_saves(self):
        for ticks, expected in REAL_SAVES:
            self.assertEqual(pipboy.from_ticks(ticks).date, expected,
                             "ticks {}".format(ticks))

    def test_a_new_game_starts_at_twenty_four_minutes_past_eight(self):
        """The first of those saves was taken 27 seconds into a new game.

        302,400 ticks is exactly 08:24:00, so the start of the game is 08:24 and
        there is no free offset left to guess at.
        """
        start = pipboy.from_ticks(302400)
        self.assertEqual((start.hour, start.minute), (8, 24))
        self.assertEqual(start.date, pipboy.EPOCH)

    def test_a_days_worth_of_ticks_is_a_day(self):
        a = pipboy.from_ticks(302400)
        b = pipboy.from_ticks(302400 + pipboy.TICKS_PER_DAY)
        self.assertEqual((b.date - a.date).days, 1)
        self.assertEqual((b.hour, b.minute), (a.hour, a.minute))

    def test_the_time_is_spoken_rather_than_printed(self):
        self.assertEqual(pipboy.say_time(8, 24), "8:24 in the morning")
        self.assertEqual(pipboy.say_time(0, 5), "12:05 in the morning")
        self.assertEqual(pipboy.say_time(12, 0), "12:00 in the afternoon")
        self.assertEqual(pipboy.say_time(17, 24), "5:24 in the afternoon")
        self.assertEqual(pipboy.say_time(18, 0), "6:00 in the evening")

    def test_the_parts_of_the_day_are_the_ones_the_game_uses(self):
        """Not borders invented here.

        The alarm clock's own options are "until morning (0800)", "until noon
        (1200)" and "until evening (1800)", so the game puts evening at six.
        Calling half past five evening would have the mod and the row directly
        under it disagreeing about the same clock.
        """
        self.assertIn("morning", pipboy.say_time(7, 59))
        self.assertIn("afternoon", pipboy.say_time(12, 0))
        self.assertIn("evening", pipboy.say_time(18, 0))

    def test_the_month_is_a_number_because_the_game_draws_it_as_a_picture(self):
        said = pipboy.from_ticks(1488625).say()
        self.assertIn("Day 26 of month 7, 2241", said)
        self.assertNotIn("July", said)

    def test_an_implausible_reading_is_refused(self):
        mem = fakes.FakeMemory({pipboy.GAME_TIME: -1})
        self.assertIsNone(pipboy.clock(mem))


class _Said:
    """An Announcer that keeps what it was told instead of speaking it."""

    def __init__(self):
        self.lines = []

    def say(self, text, interrupt=False, force=False):
        self.lines.append(" ".join(text.split()))

    def answer(self, text):
        self.say(text)

    @property
    def last(self):
        return self.lines[-1] if self.lines else ""

    def joined(self):
        return " ".join(self.lines)


class _NoClickPipboy(pipboy.Pipboy):
    """The real reader, with the one method that touches the game stubbed.

    Everything about which entry is selected, what it is called and what gets
    clicked is the shipped code; only the pointer is replaced, since a test
    cannot drive one.
    """

    def __init__(self, mem, names=None):
        super().__init__(mem, hwnd=1)
        self.pressed = []
        # Ticks the clock jumps by when a row is clicked, which is how a test
        # says "and the game really did rest". Zero is the refusal case, and
        # the two have to be told apart by reading the clock across the click
        # rather than after it -- so the fake has to move it at the same moment
        # the game would.
        self.advance = 0
        self._messages = names if names is not None else _MESSAGES

    def press(self, win, button):
        self.pressed.append(button.release)
        if self.advance:
            now = self.proc.read_i32(pipboy.GAME_TIME) or 0
            self.proc.set_i32(pipboy.GAME_TIME, now + self.advance)
        return True, ""


# pipboy.msg as the game really has it, cut down to what this screen asks for.
_MESSAGES = {202: "STATUS", 205: "AUTOMAPS", 206: "VIDEO ARCHIVES",
             214: "DONE", 300: "ALARM CLOCK"}
_MESSAGES.update({302 + i: name for i, name in enumerate([
    "Rest for ten minutes", "Rest for thirty minutes", "Rest for an hour",
    "Rest for two hours", "Rest for three hours", "Rest for four hours",
    "Rest for five hours", "Rest for six hours",
    "Rest until morning (0800)", "Rest until noon (1200)",
    "Rest until evening (1800)", "Rest until midnight (0000)",
    "Rest until healed", "Rest until party is healed"])})


def _watcher(mem):
    from fallout2_access.app import PipboyWatcher
    watcher = PipboyWatcher(_NoClickPipboy(mem))
    watcher.SETTLE = 0.0
    return watcher


class Watching(unittest.TestCase):
    def setUp(self):
        self.mem = fakes.memory_with_pipboy(
            values={pipboy.GAME_TIME: 1488625})
        self.watcher = _watcher(self.mem)
        self.ann = _Said()

    def test_arriving_names_the_time_and_the_five_places(self):
        self.watcher.enter(self.ann)
        said = self.ann.joined()
        self.assertIn("Day 26 of month 7, 2241", said)
        for word in ("ALARM CLOCK", "STATUS", "AUTOMAPS", "VIDEO ARCHIVES"):
            self.assertIn(word.capitalize(), said)

    def test_arriving_on_a_page_reads_the_page_rather_than_the_main_list(self):
        """`Z` is the engine's key for the alarm clock and skips the menu.

        Measured: from a closed panel, Z opens it with all thirteen rest rows
        already drawn. Reading out the five destinations there would describe a
        screen the player is not looking at, and would hide the one thing they
        pressed Z to reach.
        """
        mem = fakes.memory_with_pipboy(rows=ALARM_ROWS,
                                       values={pipboy.GAME_TIME: 1488625})
        watcher = _watcher(mem)
        watcher.enter(self.ann)
        said = self.ann.joined()
        self.assertIn("13 ways to rest", said)
        self.assertIn("Rest for ten minutes, 1 of 13", said)
        self.assertEqual(watcher.page, pipboy.ALARM_CLOCK)

    def test_backing_out_of_a_page_arrived_at_by_the_engines_key_still_works(self):
        mem = fakes.memory_with_pipboy(rows=ALARM_ROWS,
                                       values={pipboy.GAME_TIME: 1488625})
        watcher = _watcher(mem)
        watcher.enter(self.ann)
        watcher.back(self.ann)
        self.assertIsNone(watcher.page)
        self.assertIn("Alarm clock, 1 of 5", self.ann.last)

    def test_a_destination_is_called_what_the_game_calls_it(self):
        """"Status" is a bad name for the quest screen and it is the name.

        A gloss was added here once and taken straight back out. The panel
        reads as the game wrote it; a mod that quietly improves the game's
        labels is one where the player and everyone else are looking at
        different software.
        """
        self.watcher.enter(self.ann)
        said = self.ann.joined()
        self.assertIn("Status.", said)
        self.assertNotIn("Status,", said)

    def test_the_way_out_says_what_it_does(self):
        """The bottom light reads out as "Done", which the art calls CLOSE."""
        self.watcher.enter(self.ann)
        self.assertIn("Done, closes the Pip-Boy", self.ann.joined())

    def test_down_walks_the_destinations_and_stops_at_the_bottom(self):
        self.watcher.enter(self.ann)
        for _ in range(4):
            self.watcher.step(self.ann, 1)
        self.assertIn("5 of 5", self.ann.last)
        self.watcher.step(self.ann, 1)
        self.assertIn("Bottom.", self.ann.last)
        self.assertIn("5 of 5", self.ann.last)

    def test_up_from_the_first_says_so_rather_than_wrapping(self):
        """A list that silently wraps is one you can walk off without noticing."""
        self.watcher.enter(self.ann)
        self.watcher.step(self.ann, -1)
        self.assertIn("Top.", self.ann.last)
        self.assertIn("1 of 5", self.ann.last)

    def test_choosing_a_destination_clicks_that_destinations_button(self):
        self.watcher.enter(self.ann)
        self.watcher.step(self.ann, 1)          # onto STATUS
        self.watcher.choose(self.ann)
        self.assertEqual(self.watcher.pip.pressed, [pipboy.STATUS])

    def test_choosing_never_clicks_by_position_in_the_constant(self):
        """A destination the engine is not offering must not shift the rest.

        Indexing `DESTINATIONS` by the cursor's position would open Archives
        for somebody who asked for Automaps the moment one light is missing.
        """
        controls = [(pipboy.CLOSE, 53, 449), (pipboy.ARCHIVES, 53, 423),
                    (pipboy.STATUS, 53, 340)]
        mem = fakes.memory_with_release_windows(
            [(640, 480, controls)], {pipboy.GAME_TIME: 1488625})
        watcher = _watcher(mem)
        watcher.enter(self.ann)
        watcher.step(self.ann, 1)               # second of three: ARCHIVES
        watcher.choose(self.ann)
        self.assertEqual(watcher.pip.pressed, [pipboy.ARCHIVES])


class RestingByKeyboard(unittest.TestCase):
    def setUp(self):
        self.mem = fakes.memory_with_pipboy(
            rows=ALARM_ROWS, values={pipboy.GAME_TIME: 1488625})
        self.watcher = _watcher(self.mem)
        self.watcher.page = pipboy.ALARM_CLOCK
        self.ann = _Said()

    def test_the_rest_options_are_read_out_by_name(self):
        self.watcher.describe(self.ann)
        said = self.ann.joined()
        self.assertIn("Rest for ten minutes", said)
        self.assertIn("Rest until healed", said)
        self.assertIn("13", said)

    def test_choosing_the_third_option_clicks_the_third_row(self):
        self.watcher.step(self.ann, 1)
        self.watcher.step(self.ann, 1)
        self.assertIn("Rest for an hour", self.ann.last)
        self.watcher.choose(self.ann)
        self.assertEqual(self.watcher.pip.pressed, [512])

    def test_a_rest_is_reported_from_the_clock_rather_than_from_the_click(self):
        """An hour asked for, an hour that actually passed."""
        watcher, ann = self.watcher, self.ann
        watcher.step(ann, 1)
        watcher.step(ann, 1)                    # "Rest for an hour"
        watcher.pip.advance = 3600 * pipboy.TICKS_PER_SECOND
        watcher.choose(ann)
        self.assertIn("Rested 1 hour", ann.joined())

    def test_a_rest_that_did_not_happen_is_not_reported_as_one(self):
        """The engine's refusal is painted onto the panel and cannot be read.

        A refused rest is a clock that did not move, and that can be read
        exactly -- so the mod reports what happened rather than what it asked
        for, which is the same rule every click in this project follows.
        """
        self.watcher.choose(self.ann)           # the clock is left where it was
        said = self.ann.joined()
        self.assertIn("clock has not moved", said)
        self.assertNotIn("Rested", said)

    def test_a_long_rest_is_said_in_hours(self):
        self.watcher.pip.advance = (8 * 3600 + 30 * 60) * pipboy.TICKS_PER_SECOND
        self.watcher.choose(self.ann)
        self.assertIn("Rested 8 hours 30 minutes", self.ann.joined())

    def test_a_rest_across_midnight_is_still_counted_correctly(self):
        """The clock rolls the date over, and the span has to follow it."""
        self.mem.set_i32(pipboy.GAME_TIME, 1488625)
        self.watcher.pip.advance = 12 * 3600 * pipboy.TICKS_PER_SECOND
        self.watcher.choose(self.ann)
        said = self.ann.joined()
        self.assertIn("Rested 12 hours", said)
        self.assertIn("Day 27 of month 7", said)

    def test_backing_out_returns_to_the_five_places_without_clicking(self):
        """Nothing is sent: the lights are drawn on every page."""
        self.watcher.back(self.ann)
        self.assertEqual(self.watcher.pip.pressed, [])
        self.assertIn("1 of 5", self.ann.last)


class AnUnreadablePage(unittest.TestCase):
    def setUp(self):
        self.mem = fakes.memory_with_pipboy(
            rows=STATUS_ROWS, values={pipboy.GAME_TIME: 1488625})
        self.watcher = _watcher(self.mem)
        self.watcher.page = pipboy.STATUS
        self.ann = _Said()

    def test_entries_are_numbered_rather_than_named(self):
        self.watcher.repeat(self.ann)
        self.assertIn("Entry 1, 1 of 2", self.ann.last)

    def test_it_is_still_choosable(self):
        self.watcher.step(self.ann, 1)
        self.watcher.choose(self.ann)
        self.assertEqual(self.watcher.pip.pressed, [508])


# Arroyo's block, verbatim from the live game's quest table, with the two
# blocks after it. Real records, so the rule is tested against what the engine
# was actually handed rather than against something shaped to agree with it.
ARROYO = [pipboy.Quest(*r) for r in [
    (1500, 100, 9, 2, 6),      # Kill the evil plants
    (1500, 110, 183, 1, 3),    # Obtain flint
    (1500, 120, 191, 1, 3),    # Rescue Nagor's dog
    (1500, 130, 480, 0, 1),    # Retrieve the GECK -- shown from the first
    (1500, 140, 619, 1, 2),    # Find Vic the Trader
    (1501, 200, 100, 1, 2),    # The Den: free Vic from his debt
    (1502, 300, 198, 1, 3),    # Klamath: refuel the still
]]

# The state that character was really in: Nagor's dog and Find Vic set, and
# nothing else.
LIVE_VARS = [0] * 800
LIVE_VARS[191] = 1
LIVE_VARS[619] = 1

QUEST_WORDS = {100: "Kill the evil plants that infest Hakunin's garden.",
               110: "Obtain flint to have Mynoc sharpen your spear.",
               120: "Rescue Nagor's dog, Smoke, from the wilds.",
               130: "Retrieve the GECK for Arroyo.",
               140: "Find Vic the Trader.",
               200: "Free Vic from his debt.",
               300: "Refuel the still."}
PLACE_WORDS = {1500: "Arroyo", 1501: "The Den", 1502: "Klamath"}


class TheEnginesRule(unittest.TestCase):
    """The filter that decides what the Status page lists.

    Taken from the engine's own drawing loop, after a rule that looked obvious
    predicted one row where the panel drew two. Walk the table in order; a
    quest counts once its variable reaches its display threshold; the first
    quest that counts puts its location on the list and the rest of that
    location's block is skipped.
    """

    def test_only_the_places_with_something_to_do(self):
        self.assertEqual(pipboy.shown_locations(ARROYO, LIVE_VARS), [1500])

    def test_a_threshold_of_zero_shows_from_the_first_minute(self):
        """"Retrieve the GECK" needs nothing set, which is why Arroyo is
        listed on a character who has done nothing at all."""
        self.assertEqual(pipboy.shown_locations(ARROYO, [0] * 800), [1500])

    def test_a_place_is_listed_once_however_many_quests_it_has(self):
        vars_ = list(LIVE_VARS)
        vars_[9] = 6
        vars_[183] = 3
        self.assertEqual(pipboy.shown_locations(ARROYO, vars_), [1500])

    def test_a_second_place_appears_when_its_own_quest_starts(self):
        vars_ = list(LIVE_VARS)
        vars_[100] = 1
        self.assertEqual(pipboy.shown_locations(ARROYO, vars_), [1500, 1501])

    def test_the_quests_at_a_place_carry_whether_they_are_finished(self):
        vars_ = list(LIVE_VARS)
        vars_[191] = 3          # Nagor's dog, at its completed threshold
        got = pipboy.quests_at(ARROYO, vars_, 1500)
        # The GECK is shown from the first minute and is not finished
        # until somebody actually hands it over, so it stays open.
        self.assertEqual(got, [(120, True), (130, False), (140, False)])

    def test_a_quest_below_its_display_threshold_is_not_mentioned(self):
        got = pipboy.quests_at(ARROYO, LIVE_VARS, 1500)
        self.assertNotIn(100, [n for n, _done in got])

    def test_a_wild_index_is_skipped_rather_than_crashing(self):
        """A table read out of freed memory shows up as a nonsense index.

        The panel frees both tables when it closes, so this is not a
        hypothetical -- it is what a read taken half a frame late looks like.
        """
        broken = [pipboy.Quest(1500, 100, 999999, 0, 1)]
        self.assertEqual(pipboy.shown_locations(broken, LIVE_VARS), [])
        self.assertEqual(pipboy.quests_at(broken, LIVE_VARS, 1500), [])


class Holodisks(unittest.TestCase):
    TABLE = [pipboy.Holodisk(220, 401, 2000),
             pipboy.Holodisk(221, 402, 3000),
             pipboy.Holodisk(577, 420, 21000)]

    def test_only_the_ones_you_have(self):
        vars_ = [0] * 800
        vars_[221] = 1
        self.assertEqual(pipboy.held_holodisks(self.TABLE, vars_),
                         [self.TABLE[1]])

    def test_none_of_them_at_the_start_of_a_game(self):
        self.assertEqual(pipboy.held_holodisks(self.TABLE, [0] * 800), [])

    def test_the_text_is_joined_back_up_into_paragraphs(self):
        """The engine hard-wraps a holodisk to the panel's width.

        That wrapping is a fact about the panel, not about the writing, and a
        screen reader has no column to respect -- so the lines are put back
        together. Hearing a sentence delivered in six pieces is worse than
        hearing it.
        """
        page = {2000: "To: CHQ",
                2001: "Our team of scientists has finished",
                2002: "testing the sample.",
                2003: "**END-PAR**",
                2004: "It is 99% pure.",
                2005: "**END-DISK**",
                2006: "this belongs to the next disk"}
        got = pipboy.disk_paragraphs(page.get, 2000)
        self.assertEqual(got, ["To: CHQ Our team of scientists has finished "
                               "testing the sample.", "It is 99% pure."])

    def test_it_stops_at_the_end_marker(self):
        page = {100: "one", 101: "**END-DISK**", 102: "not this"}
        self.assertEqual(pipboy.disk_paragraphs(page.get, 100), ["one"])

    def test_it_stops_when_the_messages_run_out(self):
        self.assertEqual(pipboy.disk_paragraphs({100: "only"}.get, 100),
                         ["only"])


def _content_watcher(rows, quests=ARROYO, holodisks=(), variables=LIVE_VARS,
                     movies=(), page=None):
    places = len(pipboy.shown_locations(list(quests), list(variables)))
    disks = len(pipboy.held_holodisks(
        [pipboy.Holodisk(*h) for h in holodisks], list(variables)))
    mem = fakes.memory_with_pipboy(
        rows=rows,
        values={pipboy.GAME_TIME: 1488625,
                pipboy.REST_OPTION_COUNT: 13,
                # The engine's own counters, set to agree -- the disagreement
                # case gets its own test rather than being the default.
                pipboy.LINES_QUEST_LOCATIONS: places,
                pipboy.LINES_STATUS_HOLODISKS: disks,
                pipboy.LINES_ARCHIVES: len(movies)})
    fakes.with_pipboy_tables(mem, quests=quests, holodisks=holodisks,
                             variables=variables, movies=movies)
    watcher = _watcher(mem)
    watcher.pip._lists = {pipboy.MSG_MAP: PLACE_WORDS,
                          pipboy.MSG_QUESTS: QUEST_WORDS}
    watcher.page = page
    return watcher


class TheStatusPage(unittest.TestCase):
    # One place, and the engine draws one row button more than it has entries.
    ROWS = [(507, 66), (508, 86)]

    def setUp(self):
        self.ann = _Said()

    def test_the_place_is_named_from_the_games_own_words(self):
        w = _content_watcher(self.ROWS, page=pipboy.STATUS)
        w.repeat(self.ann)
        self.assertIn("Arroyo, 1 of 1", self.ann.last)

    def test_the_spare_row_the_engine_draws_is_not_an_entry(self):
        """The Status page creates one button past the end of its list.

        Measured: one quest location, two row buttons. Counting the buttons
        would put a phantom entry at the bottom of every quest list.
        """
        w = _content_watcher(self.ROWS, page=pipboy.STATUS)
        w.describe(self.ann)
        self.assertIn("1 of 1", self.ann.last)

    def test_choosing_a_place_reads_its_tasks_out(self):
        w = _content_watcher(self.ROWS, page=pipboy.STATUS)
        w.choose(self.ann)
        said = self.ann.joined()
        self.assertIn("Arroyo. 3 tasks", said)
        self.assertIn("Rescue Nagor's dog", said)
        self.assertIn("Retrieve the GECK", said)
        self.assertIn("Find Vic the Trader", said)

    def test_choosing_a_place_clicks_nothing(self):
        """The mod already computed the list, so there is nothing to aim at.

        The same choice the world's action menu makes: act on the thing you
        picked, by identity, rather than by pointing at it.
        """
        w = _content_watcher(self.ROWS, page=pipboy.STATUS)
        w.choose(self.ann)
        self.assertEqual(w.pip.pressed, [])

    def test_done_is_read_off_the_screen_not_added_to_it(self):
        """The engine draws a finished quest in a different colour.

        So saying "Done." is not the mod knowing more than a sighted player --
        it is the same fact, in the only form a screen reader has. The
        threshold and the comparison are the engine's own.
        """
        vars_ = list(LIVE_VARS)
        vars_[191] = 2          # started, one short of its completed threshold
        self.assertEqual(pipboy.quests_at(ARROYO, vars_, 1500)[0], (120, False))
        vars_[191] = 3          # exactly at it -- the engine's test is >=
        self.assertEqual(pipboy.quests_at(ARROYO, vars_, 1500)[0], (120, True))

    def test_a_finished_task_says_so(self):
        vars_ = list(LIVE_VARS)
        vars_[191] = 3
        w = _content_watcher(self.ROWS, variables=vars_, page=pipboy.STATUS)
        w.choose(self.ann)
        self.assertIn("Rescue Nagor's dog, Smoke, from the wilds. Done.",
                      self.ann.joined())

    def test_holodisks_are_listed_under_the_places(self):
        disks = [(221, 402, 3000)]
        vars_ = list(LIVE_VARS)
        vars_[221] = 1
        w = _content_watcher([(507, 66), (508, 86), (509, 106)],
                             holodisks=disks, variables=vars_,
                             page=pipboy.STATUS)
        w.pip._messages = dict(_MESSAGES)
        w.pip._messages[402] = 'Military Base Level 1'
        w.step(self.ann, 1)
        self.assertIn("2 of 2", self.ann.last)

    def test_the_engines_own_count_can_veto_the_reconstruction(self):
        """The sharpest check there is.

        Not "does my list have as many entries as there are buttons", which a
        wrong rule could still satisfy, but "does my list have as many entries
        as the engine counted while drawing".
        """
        w = _content_watcher(self.ROWS, page=pipboy.STATUS)
        w.pip.proc.set_i32(pipboy.LINES_QUEST_LOCATIONS, 4)
        w.repeat(self.ann)
        self.assertIn("Entry 1", self.ann.last)

    def test_a_counter_that_cannot_be_read_is_a_refusal(self):
        """Nothing is clicked on this page, so the rows check nothing.

        The engine's counters are therefore the only check there is, and a
        reconstruction with no check on it is a guess with extra steps.
        """
        w = _content_watcher(self.ROWS, page=pipboy.STATUS)
        w.pip.proc.set_i32(pipboy.LINES_QUEST_LOCATIONS, -1)
        w.repeat(self.ann)
        self.assertIn("Entry 1", self.ann.last)

    def test_the_row_count_is_not_used_on_this_page(self):
        """How many rows there are is a fact about the install.

        The engine creates one button past the end of the list, and sfall's
        `UseScrollingQuestsList` adds controls of its own on top of that. An
        install with a different setting must still hear its quests.
        """
        for rows in ([(507, 66)], self.ROWS,
                     [(507, 66), (508, 86), (509, 106), (510, 126)]):
            w = _content_watcher(rows, page=pipboy.STATUS)
            ann = _Said()
            w.repeat(ann)
            self.assertIn("Arroyo, 1 of 1", ann.last, "rows: %s" % (rows,))


class TheArchives(unittest.TestCase):
    def setUp(self):
        self.ann = _Said()

    def test_the_films_are_named(self):
        w = _content_watcher([(507, 66), (508, 86)], movies=(2, 3),
                             page=pipboy.ARCHIVES)
        w.pip._messages = {502: "Elder Speech", 503: "Vault Suit Recovery"}
        w.describe(self.ann)
        said = self.ann.last
        self.assertIn("Elder Speech", said)
        self.assertIn("Vault Suit Recovery", said)

    def test_archives_rows_match_one_for_one_with_no_spare(self):
        """Unlike Status, this page draws exactly what it lists."""
        w = _content_watcher([(507, 66)], movies=(2,), page=pipboy.ARCHIVES)
        w.pip._messages = {502: "Elder Speech"}
        w.repeat(self.ann)
        self.assertIn("Elder Speech, 1 of 1", self.ann.last)


class KeyWiring(unittest.TestCase):
    """The keys reach the Pip-Boy, and reach nothing else while they do.

    Driven through the real dispatcher rather than by looking up method names.
    A method that exists is not the same claim as a key that does something,
    and this project has already lost several rounds to the difference.
    """

    def setUp(self):
        from fallout2_access.app import App

        mem = fakes.memory_with_pipboy(rows=ALARM_ROWS,
                                       values={pipboy.GAME_TIME: 1488625})
        self.watcher = _watcher(mem)
        self.app = App.__new__(App)
        self.app.ann = _Said()
        self.app.screen = screens.PIPBOY
        self.app.watchers = {screens.PIPBOY: self.watcher}
        self.app.world = None

    def _press(self, what):
        from fallout2_access.app import App
        App._do_action(self.app, what)

    def test_down_moves_the_cursor(self):
        self._press("dlg_next")
        self.assertIn("2 of 5", self.app.ann.last)

    def test_up_moves_it_back(self):
        self._press("dlg_next")
        self._press("dlg_prev")
        self.assertIn("1 of 5", self.app.ann.last)

    def test_numpad_plus_chooses(self):
        self._press("click")
        self.assertEqual(self.watcher.pip.pressed, [pipboy.ALARM_CLOCK])

    def test_numpad_minus_backs_out_and_never_falls_through_to_a_raw_click(self):
        """The `return` in the dispatcher is the whole point of this test.

        Without it these fall through to `App.click`, which sends a real mouse
        click at wherever the pointer was last left -- on a panel where that is
        a page nobody asked for, and one of whose rows costs six hours.
        """
        self.watcher.page = pipboy.ALARM_CLOCK
        self._press("rclick")
        self.assertEqual(self.watcher.pip.pressed, [])
        self.assertIn("main list", self.app.ann.last)

    def test_the_dialogue_keys_still_belong_to_a_conversation_elsewhere(self):
        class _World:
            def __init__(self):
                self.calls = []

            def talking(self):
                return True

            def dlg_step(self, ann, delta):
                self.calls.append(delta)

        self.app.screen = screens.WORLD
        self.app.world = _World()
        self._press("dlg_next")
        self.assertEqual(self.app.world.calls, [1])
        self.assertEqual(self.watcher.pip.pressed, [])


class ScreenDetection(unittest.TestCase):
    def test_the_pipboy_mode_names_the_pipboy(self):
        mem = fakes.memory_with_pipboy()
        self.assertEqual(
            screens.detect(mem, in_game=True, mode=screens.MODE_PIPBOY),
            screens.PIPBOY)

    def test_the_character_screen_is_still_the_character_screen(self):
        mem = fakes.memory_with_pipboy()
        self.assertEqual(
            screens.detect(mem, in_game=True, mode=screens.MODE_CHARSCREEN),
            screens.CHARGEN)

    def test_the_pipboy_is_not_a_map_mode(self):
        self.assertFalse(screens.is_map_mode(screens.MODE_PIPBOY))


if __name__ == "__main__":
    unittest.main()
