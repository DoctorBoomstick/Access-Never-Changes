"""The "Move Items" window, and the window it is not.

Fallout puts this up whenever a stack of more than one is dragged, which in a
shop is constantly. It is the same 259x162 panel as the explosive countdown,
with the same step buttons at 6000 and 7000, and the engine separates them with
a mode argument it keeps in a register -- so a shape test cannot, and the mod's
did not. Moving a pile of bottle caps onto a barter table was announced as
"Explosive timer. Setting it to the shortest.", and then twenty clicks were
sent to wind down a countdown that was not there.
"""

import unittest

from fallout2_access.game import quantity, screens
from tests import fakes


def _mem(open_window=True, codes=None):
    """A fake game with the counter window open, or with nothing open."""
    if not open_window:
        return fakes.memory_with_windows([])
    if codes is None:
        codes = [quantity.STEP_UP, quantity.STEP_DOWN, quantity.TAKE_ALL]
    return fakes.memory_with_windows(
        [(quantity.PANEL_WIDTH, quantity.PANEL_HEIGHT, codes)])


class _Counter(quantity.Quantity):
    """A Quantity whose clicks are recorded rather than sent.

    Its typing is NOT stubbed out: the keys are the thing under test, and a
    fake that recorded "it typed 6" would agree with an implementation that
    sent the wrong keys in the wrong order. `quantity.guarded_tap` is swapped
    for a recorder instead, one level below the code being checked.
    """

    def __init__(self, open_window=True):
        super().__init__(_mem(open_window), hwnd=1)
        self.clicks = []
        self.fail = False

    def _click(self, code, times=1):
        if self.fail or not self.showing:
            return False
        self.clicks.append((code, times))
        return True


class _Typed(unittest.TestCase):
    """Base for anything that lets the real key-sending code run."""

    def setUp(self):
        self.keys = []
        self._real = quantity.guarded_tap
        quantity.guarded_tap = lambda hwnd, key, **kw: self.keys.append(key)
        self.addCleanup(self._restore)

    def _restore(self):
        quantity.guarded_tap = self._real

    def digits(self):
        """Just the digits typed, as the numbers they spell."""
        out, current = [], ""
        for key in self.keys:
            if key.isdigit():
                current += key
            elif current:
                out.append(int(current))
                current = ""
        if current:
            out.append(int(current))
        return out


class TellingItFromTheTimer(unittest.TestCase):
    """Which of the two 259x162 windows is up is decided by the game mode.

    The countdown is opened from the map with nothing else on screen; the
    quantity window only ever appears over an item window. That is a bit the
    engine sets, rather than something inferred from a rectangle the two share.
    """

    def _mem(self):
        # A counter window open, which both of them look like.
        return fakes.memory_with_windows(
            [(quantity.PANEL_WIDTH, quantity.PANEL_HEIGHT,
              [quantity.STEP_UP, quantity.STEP_DOWN])])

    def test_over_an_item_window_it_is_the_quantity(self):
        for mode in (screens.MODE_INVENTORY, screens.MODE_BARTER,
                     screens.MODE_INTFACELOOT, screens.MODE_INTFACEUSE):
            with self.subTest(mode=mode):
                got = screens.detect(self._mem(), in_game=True,
                                     mode=mode | screens.MODE_COUNTERWIN)
                self.assertEqual(got, screens.QUANTITY)

    def test_over_the_map_it_is_still_the_timer(self):
        """Which is the case that used to work and must keep working."""
        got = screens.detect(self._mem(), in_game=True,
                             mode=screens.MODE_COUNTERWIN)
        self.assertEqual(got, screens.TIMER)

    def test_they_are_not_the_same_screen(self):
        self.assertNotEqual(screens.QUANTITY, screens.TIMER)


class KnowingItIsOpen(unittest.TestCase):
    """Asked of the list of OPEN windows, never of a search through the heap.

    A freed window keeps its fields, so a heap search answers yes for the rest
    of the session once one has been used -- and here saying yes to a window
    that has closed means typing digits at whatever is on screen instead, which
    in a conversation is the reply numbers.
    """

    def test_open(self):
        self.assertTrue(quantity.showing(_mem()))

    def test_closed(self):
        self.assertFalse(quantity.showing(_mem(open_window=False)))

    def test_a_window_of_the_right_size_is_not_enough(self):
        """Both step buttons, or it is some other panel that happens to fit."""
        self.assertFalse(quantity.showing(_mem(codes=[quantity.STEP_UP])))


class Counting(_Typed):
    """The number is caused, not read -- it lives in a register in the engine's
    own modal loop and the routine that draws it stores it nowhere.

    So it is TYPED, as a whole number, which the engine reads at 0x00476A48:
    every press states the count outright rather than nudging it, and a count
    that has drifted out of step with the screen is put right by the next press
    instead of carrying the error forward.
    """

    def test_it_starts_where_the_engine_starts_it(self):
        self.assertEqual(_Counter().count, 1)
        self.assertEqual(quantity.STARTS_AT, 1)

    def test_up_and_down_move_by_one(self):
        c = _Counter()
        c.step(1)
        c.step(1)
        self.assertEqual(c.count, 3)
        c.step(-1)
        self.assertEqual(c.count, 2)
        self.assertEqual(self.digits(), [2, 3, 2])

    def test_the_field_is_emptied_before_a_number_is_typed(self):
        """Each press states the whole number, so what was there must go.

        The engine only clears the field itself on the first digit after a
        button press, and the mod does not press the buttons -- so without the
        backspaces "2" typed onto a 1 would leave the window showing twelve.
        """
        c = _Counter()
        c.step(1)
        # As many as a one-digit field can hold, and two to spare -- not six
        # every time, which is what made each press take the best part of a
        # second.
        self.assertEqual(self.keys, [quantity.CLEAR_KEY] * 3 + ["2"])

    def test_a_two_digit_number_is_typed_a_digit_at_a_time(self):
        c = _Counter()
        c.reset(most=20)
        c.count = 11
        c.step(1)
        self.assertEqual(c.count, 12)
        self.assertEqual(self.keys[-2:], ["1", "2"])

    def test_it_will_not_go_below_one(self):
        """The engine refuses too -- Enter on a count below the floor plays the
        error sound and asks again -- so counting past it would leave the mod's
        number and the screen's out of step for the rest of the window."""
        c = _Counter()
        said = c.step(-1)
        self.assertIn("One is the fewest", said)
        self.assertEqual(c.count, 1)
        self.assertEqual(self.keys, [])

    def test_it_will_not_go_above_the_stack_when_the_stack_is_known(self):
        c = _Counter()
        c.reset(most=2)
        c.step(1)
        said = c.step(1)
        self.assertIn("2 is all of them", said)
        self.assertEqual(c.count, 2)

    def test_an_unknown_maximum_is_not_guessed_at(self):
        """A wrong maximum would be wrong on every stack; an absent one only
        lets the count drift if the player presses past the real end."""
        c = _Counter()
        self.assertIsNone(c.most)
        for _ in range(5):
            c.step(1)
        self.assertEqual(c.count, 6)
        self.assertEqual(c.say(), "6")

    def test_the_count_is_said_against_the_stack_when_known(self):
        c = _Counter()
        c.reset(most=9)
        c.step(1)
        self.assertEqual(c.say(), "2 of 9.")

    def test_nothing_is_typed_once_the_window_has_gone(self):
        """Digits are not harmless keys. In a conversation they are the reply
        numbers and on the map they arm skills, so a count adjusted a moment
        after the window closed would say something to a shopkeeper."""
        c = _Counter(open_window=False)
        self.assertIsNone(c.step(1))
        self.assertEqual(c.count, 1)
        self.assertEqual(self.keys, [])

    def test_reset_returns_to_the_engines_starting_point(self):
        c = _Counter()
        c.step(1)
        c.reset()
        self.assertEqual(c.count, 1)
        self.assertIsNone(c.most)


class TakingAllOfIt(_Typed):
    def test_all_uses_the_windows_own_button(self):
        """It lands exactly on the maximum without this module needing to know
        what the maximum is, which is why it is worth an aim."""
        c = _Counter()
        c.all()
        self.assertEqual(c.clicks, [(quantity.TAKE_ALL, 1)])
        self.assertEqual(self.keys, [])

    def test_all_with_an_unknown_maximum_says_what_is_true(self):
        c = _Counter()
        self.assertEqual(c.all(), "All of them.")
        self.assertEqual(c.say(), "All of them.")

    def test_all_with_a_known_maximum_names_the_number(self):
        c = _Counter()
        c.reset(most=7)
        self.assertEqual(c.all(), "7 of 7.")

    def test_a_failed_aim_falls_back_to_typing_the_number(self):
        """Inside this window the aim is the doubtful half: it is a modal loop
        of the engine's own, and the pointer is driven by asking a script where
        it is. Typing needs nothing pointed at."""
        c = _Counter()
        c.fail = True
        c.reset(most=7)
        self.assertEqual(c.all(), "7 of 7.")
        self.assertEqual(self.digits(), [7])

    def test_with_no_maximum_and_no_aim_it_admits_it(self):
        """There is no number to type, so there is nothing to claim."""
        c = _Counter()
        c.fail = True
        self.assertIsNone(c.all())
        self.assertEqual(self.keys, [])


class Confirming(_Typed):
    def test_done_and_cancel_are_the_games_own_keys(self):
        """Their event codes are 13 and 27 -- below 256, so GNW treats them as
        key presses, and the engine's loop tests for them at 0x004768DB and
        0x004768EA. The two decisions that matter need no pointer."""
        self.assertEqual(quantity.ACCEPT_KEY, "enter")
        self.assertEqual(quantity.CANCEL_KEY, "escape")

    def test_cancel_presses_escape(self):
        c = _Counter()
        self.assertTrue(c.cancel())
        self.assertEqual(self.keys, [quantity.CANCEL_KEY])

    def test_accept_presses_enter(self):
        c = _Counter()
        self.assertTrue(c.accept())
        self.assertEqual(self.keys, [quantity.ACCEPT_KEY])

    def test_neither_is_sent_once_the_window_has_gone(self):
        """The mod's idea of which screen is up is a tick behind the game's,
        and Escape in the barter window closes the barter."""
        c = _Counter(open_window=False)
        self.assertFalse(c.cancel())
        self.assertFalse(c.accept())
        self.assertEqual(self.keys, [])


class _Inventory:
    counts = (3, 0)


class _World:
    inventory = _Inventory()


class _Silent:
    def answer(self, _text):
        pass


class AskingWhatMoved(unittest.TestCase):
    """After a drag the mod taps numpad 0, which asks gl_inven.ssl for both
    lists' totals -- the only way to say what actually moved.

    **Dragging a stack is exactly what puts the "How many?" window up**, so in
    a shop that key landed in the window every time. It is a modal loop of the
    engine's own and it reads numpad 0 as the digit zero, and gl_inven.ssl
    stands down while it is showing, so the key was not even swallowed on the
    way past. The mod answered the game's question with "none" before the
    player had touched anything: the window then sat on a count the engine
    refuses, and Enter answered with the error sound.
    """

    def setUp(self):
        from fallout2_access import app as app_module

        self.app_module = app_module
        self.keys = []
        self._real = app_module.guarded_tap
        app_module.guarded_tap = lambda hwnd, key, **kw: self.keys.append(key)
        self.addCleanup(self._restore)

    def _restore(self):
        self.app_module.guarded_tap = self._real

    def _app(self, window_up):
        app = self.app_module.App.__new__(self.app_module.App)
        app.hwnd = 1
        app.proc = _mem(window_up)
        app.screen = screens.QUANTITY if window_up else screens.WORLD
        app._owed_totals = False
        app._moved = None
        app.world = _World()
        app.ann = _Silent()
        return app

    def test_it_is_not_asked_while_the_window_is_up(self):
        app = self._app(True)
        app._ask_totals()
        self.assertEqual(self.keys, [])
        self.assertTrue(app._owed_totals)

    def test_the_live_window_decides_rather_than_the_screen(self):
        """The drag takes seconds and the window opens in the middle of it, so
        the mod's idea of which screen is up is from before the question."""
        app = self._app(True)
        app.screen = screens.WORLD
        app._ask_totals()
        self.assertEqual(self.keys, [])

    def test_it_is_asked_when_there_is_no_such_window(self):
        app = self._app(False)
        app._ask_totals()
        self.assertEqual(self.keys, ["numpad0"])
        self.assertFalse(app._owed_totals)

    def test_the_owed_question_is_asked_once_the_window_closes(self):
        """Or the totals never arrive, and every stack moved in a shop is
        reported as one that did not move."""
        import time

        app = self._app(False)
        app._owed_totals = True
        app._moved = ("Stimpak", (1, 0), time.time() + 1.5)
        app._settle_move()
        self.assertEqual(self.keys, ["numpad0"])
        self.assertFalse(app._owed_totals)


class SizedByWhatIsDragged(unittest.TestCase):
    """The window's maximum comes from the item picked up, not the cursor.

    203 of Sajag's caps dropped beside four boxes of 10mm JHP could only be
    moved a few at a time: the window was sized off the list cursor, and the
    cursor was on the bullets. The watcher is reset twice on the way in, so
    the count has to survive being read twice.
    """

    def test_the_dragged_stack_sets_the_most(self):
        from fallout2_access.app import QuantityWatcher
        from fallout2_access.game.inventory import InventoryWatcher

        inv = InventoryWatcher()
        inv.handle("INVEN:entry 1|0|11|Money|203|0|-1|1|-1|0|1|-1|")
        inv.start_moving(inv.selected_count)
        inv.handle("INVEN:entry 4|0|1|10mm JHP|4|1|-1|2|-1|0|75|96|")
        counter = _Counter()
        watcher = QuantityWatcher(counter, inv)
        watcher.reset()
        watcher.reset()
        self.assertEqual(counter.most, 203)

    def test_without_a_drag_the_cursor_is_the_fallback(self):
        from fallout2_access.app import QuantityWatcher
        from fallout2_access.game.inventory import InventoryWatcher

        inv = InventoryWatcher()
        inv.handle("INVEN:entry 1|0|11|Money|203|0|-1|1|-1|0|1|-1|")
        counter = _Counter()
        QuantityWatcher(counter, inv).reset()
        self.assertEqual(counter.most, 203)


if __name__ == "__main__":
    unittest.main()


class _Typist(quantity.Quantity):
    """A counter whose typing is recorded rather than sent."""

    def __init__(self, most=None):
        self.proc = None
        self.hwnd = 1
        self.reset(most)
        self.put = []

    def _type(self, value):
        self.put.append(value)
        return True


class TestTypedAmounts(unittest.TestCase):

    def test_digits_build_the_number(self):
        q = _Typist(most=457)
        self.assertEqual(q.digit(6), "6")
        self.assertEqual(q.digit(0), "60")
        self.assertEqual(q.count, 60)
        self.assertEqual(q.put, [6, 60])

    def test_more_than_the_stack_is_the_stack(self):
        q = _Typist(most=50)
        q.digit(6)
        self.assertEqual(q.digit(0), "50 is all of them.")
        self.assertEqual(q.count, 50)

    def test_a_step_ends_the_typing(self):
        q = _Typist(most=457)
        q.digit(6)
        q.step(10)
        self.assertEqual(q.count, 16)
        q.digit(2)
        self.assertEqual(q.count, 2)

    def test_a_big_step_stops_at_the_ends(self):
        q = _Typist(most=12)
        self.assertEqual(q.step(10), "11 of 12.")
        self.assertEqual(q.step(10), "12 of 12.")
        self.assertEqual(q.step(10), "12 is all of them.")
        self.assertEqual(q.step(-10), "2 of 12.")
        self.assertEqual(q.step(-10), "1 of 12.")
        self.assertEqual(q.step(-10), "One is the fewest.")
