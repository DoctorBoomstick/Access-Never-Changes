"""Which screen row holds the item the script calls `index`.

This is arithmetic that was wrong in the live game for weeks, and it hid well:
the move was checked afterwards by counting both lists, the counts were always
right, and a wrong row looks exactly like a right one to a count. Only naming
the item that moved caught it.
"""

import os
import tempfile
import unittest

from fallout2_access.game import itemmove
from fallout2_access.game.inventory import (SIDE_MINE, SIDE_MY_OFFER,
                                            SIDE_THEIRS, SIDE_THEIR_OFFER,
                                            SIDE_WORN)
from fallout2_access.game.itemmove import VISIBLE_ROWS, drawn_row


class TestDrawnRow(unittest.TestCase):
    def test_the_list_is_drawn_backwards(self):
        """The measurement, both ways round, with two items.

        Dragging index 0 moved the Spear -- the script's index 1 -- and dragging
        index 1 moved the Healing Powder, the script's index 0.
        """
        self.assertEqual(drawn_row(0, 2), 1)
        self.assertEqual(drawn_row(1, 2), 0)

    def test_the_scripts_first_item_is_the_engines_last_row(self):
        self.assertEqual(drawn_row(0, 5), 4)
        self.assertEqual(drawn_row(4, 5), 0)

    def test_a_single_item_is_the_only_row(self):
        self.assertEqual(drawn_row(0, 1), 0)

    def test_it_is_its_own_inverse(self):
        """Reversal applied twice is the identity, which is what makes the same
        function correct for reading a row back as for choosing one."""
        for total in range(1, 12):
            for index in range(total):
                self.assertEqual(drawn_row(drawn_row(index, total), total),
                                 index)

    def test_a_stale_total_cannot_produce_a_negative_row(self):
        """A negative row would be added to the base event code and address a
        button belonging to some other control entirely -- a click somewhere
        nobody chose, which is the one outcome worse than refusing."""
        self.assertEqual(drawn_row(5, 2), 0)
        self.assertEqual(drawn_row(3, 0), 0)

    def test_long_lists_push_the_early_items_off_screen(self):
        """With the list drawn backwards it is the script's FIRST items that
        fall outside the six visible rows, not its last."""
        total = 9
        off = [i for i in range(total) if drawn_row(i, total) >= VISIBLE_ROWS]
        self.assertEqual(off, [0, 1, 2])


class TestFastMoveKeys(unittest.TestCase):
    """Reading sfall's two move modifiers out of the game's own config.

    `ItemMoveSkipDragKey` (left Ctrl) turns a click into a move, so nothing has
    to be dragged. `ItemFastMoveKey` (left Shift) moves the whole stack instead
    of opening the "Move Items" window to ask how many. **Both are needed**, and
    that was measured rather than reasoned: a Ctrl-only click on an item in the
    barter window put up the quantity picker and moved nothing.

    They are read rather than assumed because either can be turned off or
    rebound. On an install that has disabled one, sending the click anyway does
    not move the item -- it lifts it onto the cursor, or stops on a window the
    player cannot see -- which is exactly the silently half-finished state this
    module exists to avoid. So if either is missing, the answer is None and the
    caller drags.
    """

    def _dir_with(self, tmp, text):
        path = os.path.join(tmp, "ddraw.ini")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return tmp

    SHIPPED = "[Input]\nItemFastMoveKey=42\nItemMoveSkipDragKey=29\n"

    def test_an_ordinary_move_holds_only_the_no_drag_key(self):
        """**Holding Shift as well was a bug**, and a quiet one: Shift is
        `ItemFastMoveKey`, whose whole job is to take the stack and skip the
        question. Every stack went across entire and the player was never
        asked -- two hundred caps, all of them, silently."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._dir_with(tmp, self.SHIPPED)
            self.assertEqual(itemmove.fast_move_keys(d), ["lctrl"])

    def test_the_whole_stack_holds_both(self):
        """Fallout's own rule: you hold that key when you mean all of it."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._dir_with(tmp, self.SHIPPED)
            self.assertEqual(itemmove.fast_move_keys(d, whole_stack=True),
                             ["lctrl", "lshift"])

    def test_no_skip_drag_key_means_the_drag_stands(self):
        """Without it a plain click does not move an item -- it lifts it onto
        the cursor and leaves it there, which is the silently half-finished
        state this module exists to avoid."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._dir_with(tmp, "[Input]\nItemFastMoveKey=42\n"
                                    "ItemMoveSkipDragKey=0\n")
            self.assertIsNone(itemmove.fast_move_keys(d))
            self.assertIsNone(itemmove.fast_move_keys(d, whole_stack=True))

    def test_no_fast_move_key_only_costs_the_whole_stack_shortcut(self):
        """An ordinary move never needed that key, so its absence must not
        stop one."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._dir_with(tmp, "[Input]\nItemFastMoveKey=0\n"
                                    "ItemMoveSkipDragKey=29\n")
            self.assertEqual(itemmove.fast_move_keys(d), ["lctrl"])
            self.assertIsNone(itemmove.fast_move_keys(d, whole_stack=True))

    def test_one_key_doing_both_jobs_is_held_once(self):
        """sfall's own note says the two can be mapped to the same key."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._dir_with(
                tmp, "[Input]\nItemFastMoveKey=29\nItemMoveSkipDragKey=29\n")
            self.assertEqual(itemmove.fast_move_keys(d), ["lctrl"])

    def test_a_key_the_mod_cannot_send_is_declined_rather_than_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._dir_with(
                tmp, "[Input]\nItemFastMoveKey=42\nItemMoveSkipDragKey=88\n")
            self.assertIsNone(itemmove.fast_move_keys(d))

    def test_a_missing_setting_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._dir_with(tmp, "[Input]\nItemFastMoveKey=42\n")
            self.assertIsNone(itemmove.fast_move_keys(d))

    def test_a_missing_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(itemmove.fast_move_keys(tmp))

    def test_no_game_directory_is_not_an_error(self):
        self.assertIsNone(itemmove.fast_move_keys(None))


class TestWhichMovesCanSkipTheDrag(unittest.TestCase):
    """Only a move between the two item lists may take the shortcut.

    The modifier click lets the ENGINE choose where the item lands, and sfall's
    own note says items "go to appropriate slots". Between two lists there is
    only one other place to go, so its judgement and the player's cannot
    disagree. Equipping is different: there are three worn slots, the player
    picked one, and letting the engine pick instead would put the weapon in the
    wrong hand without saying so. That one still drags.
    """

    def _may_skip(self, source_side, target_side):
        return frozenset((source_side, target_side)) in itemmove.FAST_PAIRS

    def test_between_the_two_lists_may_skip(self):
        self.assertTrue(self._may_skip(SIDE_MINE, SIDE_THEIRS))
        self.assertTrue(self._may_skip(SIDE_THEIRS, SIDE_MINE))

    def test_equipping_must_not_skip(self):
        self.assertFalse(self._may_skip(SIDE_MINE, SIDE_WORN))
        self.assertFalse(self._may_skip(SIDE_WORN, SIDE_MINE))

    def test_within_one_list_must_not_skip(self):
        """There is nowhere else for the engine to send it, so a modifier click
        would move the item to the other list -- the opposite of what was
        asked."""
        self.assertFalse(self._may_skip(SIDE_MINE, SIDE_MINE))
        self.assertFalse(self._may_skip(SIDE_THEIRS, SIDE_THEIRS))


class TestBarterPanes(unittest.TestCase):
    """The barter window is four lists, and two of them are new.

    Two things about it break assumptions the loot window taught. It draws
    THREE rows a list where the others draw six, so the row arithmetic has to
    be asked rather than assumed; and "the other list" is not the other side of
    the window -- an item clicked in your own pack goes onto your own half of
    the table, not into the shopkeeper's.
    """

    def test_every_list_has_row_codes(self):
        for side in (SIDE_MINE, SIDE_THEIRS, SIDE_MY_OFFER, SIDE_THEIR_OFFER):
            with self.subTest(side=side):
                self.assertIn(side, itemmove.ROW_CODE)

    def test_every_list_can_be_scrolled(self):
        for side in (SIDE_MINE, SIDE_THEIRS, SIDE_MY_OFFER, SIDE_THEIR_OFFER):
            with self.subTest(side=side):
                self.assertIn(side, itemmove.SCROLL_UP)
                self.assertIn(side, itemmove.SCROLL_DOWN)

    def test_the_row_codes_do_not_collide(self):
        """Two lists sharing a code would press the wrong pane's button."""
        codes = list(itemmove.ROW_CODE.values())
        self.assertEqual(len(codes), len(set(codes)))

    def test_a_click_moves_within_a_side_not_across_the_window(self):
        """The engine picks the destination, so the shortcut is only allowed
        where there is one place it could mean."""
        allowed = itemmove.FAST_PAIRS
        self.assertIn(frozenset((SIDE_MINE, SIDE_MY_OFFER)), allowed)
        self.assertIn(frozenset((SIDE_THEIRS, SIDE_THEIR_OFFER)), allowed)
        # Straight across the barter table is NOT one move, and treating it as
        # one would put an item somewhere nobody asked for.
        self.assertNotIn(frozenset((SIDE_MINE, SIDE_THEIR_OFFER)), allowed)
        self.assertNotIn(frozenset((SIDE_MY_OFFER, SIDE_THEIR_OFFER)), allowed)

    def test_equipping_is_still_never_a_click(self):
        self.assertNotIn(frozenset((SIDE_MINE, SIDE_WORN)), itemmove.FAST_PAIRS)


class TestVisibleRows(unittest.TestCase):
    """How many rows a list draws, counted off the engine's own buttons.

    Counted by code AND by column. The rows of a list are one stack of equally
    wide buttons; the worn slots carry the very next codes and are drawn
    somewhere else entirely, so a walk that only asks "is there a button 1006?"
    keeps going straight through them.
    """

    class _Btn:
        def __init__(self, left, right):
            self.left, self.right = left, right

    class _Win:
        """Rows in one column, plus whatever else the caller puts elsewhere."""

        def __init__(self, codes, others=()):
            self.buttons = {code: TestVisibleRows._Btn(44, 107)
                            for code in codes}
            self.buttons.update(
                {code: TestVisibleRows._Btn(l, r) for code, l, r in others})

        def by_press(self, code):
            return self.buttons.get(code)

    def test_it_counts_what_the_engine_made(self):
        win = self._Win(range(1000, 1006))          # six, as in the loot window
        self.assertEqual(itemmove.visible_rows(win, SIDE_MINE), 6)

    def test_the_worn_slots_are_not_three_more_rows(self):
        """The live inventory window, and the bug it caused. 1006, 1007 and
        1008 follow the six rows without a gap, so this used to answer nine --
        and `ROW_CODE + 8` is the armour slot, which is where sixteen carried
        items got dropped."""
        win = self._Win(range(1000, 1006),
                        others=((1008, 154, 243), (1007, 154, 243),
                                (1006, 245, 334)))
        self.assertEqual(itemmove.visible_rows(win, SIDE_MINE), 6)

    def test_barters_three_rows_are_not_read_as_six(self):
        """Six would compute a row off the bottom of the pane and press a
        button belonging to some other control."""
        win = self._Win(range(1000, 1003))
        self.assertEqual(itemmove.visible_rows(win, SIDE_MINE), 3)

    def test_a_window_with_no_rows_falls_back_rather_than_returning_zero(self):
        """Zero would make every row number look off-screen and refuse every
        move, which is a worse answer than the old assumption."""
        self.assertEqual(itemmove.visible_rows(self._Win(()), SIDE_MINE),
                         itemmove.VISIBLE_ROWS)

    def test_an_unknown_side_falls_back(self):
        self.assertEqual(itemmove.visible_rows(self._Win(()), SIDE_WORN),
                         itemmove.VISIBLE_ROWS)


class TestScrollFor(unittest.TestCase):
    """How far down a list has to be scrolled to reach an item.

    **One press of the arrow is one row**, and that was measured rather than
    assumed: the list was put at the top, the down arrow pressed once, the top
    row moved with a modifier click, and the item that arrived was named. With
    seven items on a three-row pane the top row holds the script's last item at
    rest, and after one press it held the one before it.

    This mattered because the mod used to refuse instead of scrolling, and on
    the barter window -- three rows a pane -- that meant refusing everything but
    the last three items of every list. "That item is item 1 and only 3 fit on
    screen" was the whole of trying to trade.
    """

    def test_a_list_that_fits_needs_no_scrolling(self):
        for index in range(3):
            self.assertEqual(itemmove.scroll_for(index, 3, 3), 0)

    def test_the_scripts_first_item_needs_the_most(self):
        """The engine draws these backwards, so index 0 is furthest down."""
        self.assertEqual(itemmove.scroll_for(0, 7, 3), 4)
        self.assertEqual(itemmove.scroll_for(6, 7, 3), 0)

    def test_it_never_asks_for_more_than_the_list_has(self):
        """Scrolling past the end lands on a clamp the arithmetic has not
        accounted for, and every row would then be off by the overshoot."""
        for total in range(1, 30):
            for rows in (3, 6):
                with self.subTest(total=total, rows=rows):
                    self.assertLessEqual(itemmove.scroll_for(0, total, rows),
                                         max(0, total - rows))

    def test_every_item_ends_up_on_a_real_row(self):
        """The whole point: after scrolling, the row pressed must be inside the
        pane. Outside it addresses a button belonging to another control."""
        for total in range(1, 30):
            for rows in (3, 6):
                for index in range(total):
                    with self.subTest(total=total, rows=rows, index=index):
                        down = itemmove.scroll_for(index, total, rows)
                        row = drawn_row(index, total) - down
                        self.assertGreaterEqual(row, 0)
                        self.assertLess(row, rows)

    def test_the_measured_case_comes_out_as_measured(self):
        """Seven items, three rows, one press down: the top row is the script's
        index 5. That is the observation the step size rests on."""
        self.assertEqual(drawn_row(5, 7) - 1, 0)

    def test_the_live_barter_case(self):
        """Six items on a three-row pane, which is the list that could not be
        traded from. Index 0 scrolls three and presses the bottom row -- run
        against the game, it moved exactly that item."""
        self.assertEqual(itemmove.scroll_for(0, 6, 3), 3)
        self.assertEqual(drawn_row(0, 6) - itemmove.scroll_for(0, 6, 3), 2)


class TestNothingIsClickedMidDrag(unittest.TestCase):
    """The drag must be a press, a move, and a release -- and nothing else.

    Bringing a row into view means CLICKING a scroll arrow, and the destination
    used to be worked out after the button was already down. So the first
    scroll click released the item over the arrow, and the move became a
    pick-up-and-put-down with a burst of clicking in front of it. That is
    exactly how it was reported: "a bunch of clicking, but nothing moves."

    It bit every move into or out of an equipment slot, because the carried
    list is nearly always longer than the six rows that fit and therefore
    nearly always needs scrolling.

    The window here is the real one, measured out of the running game: the
    inventory panel at (262,145) 499x377, its six rows at 1000..1005, its
    scroll arrows at 328 and 336, and the three worn slots at 1006..1008.
    """

    from fallout2_access.game import uiwindow as _uiwindow

    LAYOUT = [
        (1000, 44, 35, 107, 82), (1001, 44, 83, 107, 130),
        (1002, 44, 131, 107, 178), (1003, 44, 179, 107, 226),
        (1004, 44, 227, 107, 274), (1005, 44, 275, 107, 322),
        (328, 128, 39, 149, 61), (336, 128, 62, 149, 84),
        (1008, 154, 183, 243, 243), (1007, 154, 286, 243, 346),
        (1006, 245, 286, 334, 346),
    ]

    ROWS = 6
    UP_CENTRE = (400, 195)
    DOWN_CENTRE = (400, 218)

    class _Proc:
        directory = None            # no ddraw.ini, so nothing takes the fast path

    class _Finder:
        """The engine's scrolling, as it was measured, answering back.

        Home goes to the top and End to the bottom; a page key moves one pane
        and clamps; one arrow click is one row. The arrows carry the dead flag
        at the end they cannot pass, which is what the mod reads to know an
        anchor landed.
        """

        def __init__(self, outer, total):
            self.outer = outer
            self.proc = outer._Proc()
            self.offset = 0
            self.most = max(0, total - outer.ROWS)

        def key(self, name):
            if name == "home":
                self.offset = 0
            elif name == "end":
                self.offset = self.most
            elif name == "pagedown":
                self.offset = min(self.most, self.offset + self.outer.ROWS)
            elif name == "pageup":
                self.offset = max(0, self.offset - self.outer.ROWS)

        def click(self, at):
            if at == self.outer.DOWN_CENTRE:
                self.offset = min(self.most, self.offset + 1)
            elif at == self.outer.UP_CENTRE:
                self.offset = max(0, self.offset - 1)

        def at(self, *_rect, need=()):
            dead = itemmove.BUTTON_DEAD
            flags = {328: 0x10000 | (dead if self.offset == 0 else 0),
                     336: 0x10000 | (dead if self.offset >= self.most else 0)}
            buttons = [self.outer._uiwindow.Button(
                id=i, flags=flags.get(code, 0x10000), left=l, top=t, right=r,
                bottom=b, press=code, addr=i)
                for i, (code, l, t, r, b) in enumerate(self.outer.LAYOUT)]
            return self.outer._uiwindow.Window(
                id=5, flags=16, left=262, top=145, width=499, height=377,
                addr=0, buttons=buttons)

    def _setup(self, total):
        self.finder = self._Finder(self, total)
        self.proc = self.finder.proc

    def setUp(self):
        self._setup(16)
        self.events = []
        self.pointer = None

        def aim(_p, _h, x, y, **_k):
            self.events.append(("aim", x, y))
            self.pointer = (x, y)
            return True, (x, y), ""

        def click(*_a, **_k):
            self.events.append(("click",))
            self.finder.click(self.pointer)

        def tap(_h, key, **_k):
            self.events.append(("tap", key))
            self.finder.key(key)

        # A clock the test winds itself. The drag sleeps a third of a second to
        # let the engine's input loop keep up, which is right in the game and
        # is a quarter of a minute across an exhaustive sweep.
        class _Clock:
            now = 0.0

            def time(self):
                self.now += 0.001      # so no wait can spin for ever
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        self._saved = {name: getattr(itemmove, name) for name in
                       ("require_focus", "aim_ui", "aim_to", "mouse_down",
                        "mouse_up", "guarded_click", "guarded_click_with",
                        "guarded_tap", "time")}
        itemmove.time = _Clock()
        itemmove.require_focus = lambda *a, **k: None
        itemmove.aim_ui = aim
        itemmove.aim_to = aim
        itemmove.mouse_down = lambda *a, **k: self.events.append(("down",))
        itemmove.mouse_up = lambda *a, **k: self.events.append(("up",))
        itemmove.guarded_click = click
        itemmove.guarded_tap = tap
        itemmove.guarded_click_with = lambda *a, **k: self.events.append(
            ("modclick",))
        self.addCleanup(self._restore)

    def _restore(self):
        for name, fn in self._saved.items():
            setattr(itemmove, name, fn)

    def _kinds(self):
        return [e[0] for e in self.events]

    def _held(self):
        """Everything that happened while the mouse button was down."""
        kinds = self._kinds()
        return kinds[kinds.index("down") + 1:kinds.index("up")]

    def _row_reached(self, released_at, total):
        """Which item the row the mod released over is actually showing.

        The end-to-end question, asked of the simulated engine rather than of
        the mod's own arithmetic: screen row `r` of a list scrolled to `offset`
        draws position `offset + r`, and the lists are drawn backwards.
        """
        rows = {(337, 203): 0, (337, 251): 1, (337, 299): 2,
                (337, 347): 3, (337, 395): 4, (337, 443): 5}
        row = rows[(released_at[1], released_at[2])]
        return total - 1 - (self.finder.offset + row)

    def test_unequipping_into_a_long_list_clicks_nothing_while_held(self):
        """The reported bug, in the direction it was reported: a weapon out of
        a hand and into sixteen carried items, which needs ten rows of
        scrolling to reach the top of."""
        itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                      (SIDE_WORN, 2, 3), (SIDE_MINE, 0, 16))
        self.assertNotEqual(self.finder.offset, 0)   # it really did scroll
        self.assertEqual(self._held(), ["aim"])      # and not while holding

    def test_equipping_out_of_a_long_list_clicks_nothing_while_held(self):
        itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                      (SIDE_MINE, 0, 16), (SIDE_WORN, 0, 3))
        self.assertNotEqual(self.finder.offset, 0)
        self.assertEqual(self._held(), ["aim"])

    def test_the_item_is_pressed_on_after_both_lists_have_settled(self):
        """Order matters as much as the count: all the scrolling, then the
        press. A scroll after the press moves the row out from under it."""
        itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                      (SIDE_WORN, 2, 3), (SIDE_MINE, 0, 16))
        kinds = self._kinds()
        scrolls = [i for i, k in enumerate(kinds) if k in ("click", "tap")]
        self.assertTrue(scrolls)
        self.assertLess(max(scrolls), kinds.index("down"))

    def test_the_press_and_the_release_land_on_the_two_chosen_buttons(self):
        """Unequipping slot 2 presses button 1007 and releases over the row
        that is really showing item 0 once the list has stopped moving."""
        itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                      (SIDE_WORN, 2, 3), (SIDE_MINE, 0, 16))
        kinds = self._kinds()
        pressed_at = [e for i, e in enumerate(self.events)
                      if e[0] == "aim" and i < kinds.index("down")][-1]
        released_at = [e for i, e in enumerate(self.events)
                       if e[0] == "aim" and i > kinds.index("down")][0]
        self.assertEqual(pressed_at, ("aim", 460, 461))     # button 1007
        self.assertEqual(self._row_reached(released_at, 16), 0)

    def test_every_item_of_a_long_list_is_reached(self):
        """The whole route, item by item, against the engine's own scrolling.
        Anchor, pages, remainder and row arithmetic all have to agree or this
        lands on somebody else's item -- which is the failure that hides."""
        for total in (7, 16, 40):
            for index in range(total):
                with self.subTest(total=total, index=index):
                    self._setup(total)
                    self.events = []
                    itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                                  (SIDE_WORN, 2, 3), (SIDE_MINE, index, total))
                    kinds = self._kinds()
                    released_at = [e for i, e in enumerate(self.events)
                                   if e[0] == "aim"
                                   and i > kinds.index("down")][0]
                    self.assertEqual(self._row_reached(released_at, total),
                                     index)

    def test_the_first_item_of_a_long_list_needs_no_pointer_at_all(self):
        """The bottom anchor lands exactly on it, so End is the whole of the
        scrolling: no aim, no click, one keystroke."""
        itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                      (SIDE_WORN, 2, 3), (SIDE_MINE, 0, 16))
        self.assertEqual([e for e in self.events if e[0] == "tap"],
                         [("tap", "end")])
        self.assertNotIn("click", self._kinds())

    def test_no_route_ever_needs_more_than_a_pane_of_clicks(self):
        """A page key covers whole panes, so the remainder cannot be a whole
        one -- which is what stops a forty-item pack costing forty clicks."""
        for total in (7, 16, 40, 99):
            for index in range(total):
                with self.subTest(total=total, index=index):
                    self._setup(total)
                    self.events = []
                    itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                                  (SIDE_WORN, 2, 3), (SIDE_MINE, index, total))
                    self.assertLess(self._kinds().count("click"), self.ROWS)

    def test_the_arrows_are_still_there_when_the_anchor_will_not_land(self):
        """The keyboard route is only ever taken when the engine confirms it
        worked. A window that does not answer Home falls back to pressing the
        arrow more times than the list can scroll, which needs nothing read."""
        self.finder.key = lambda _name: None        # the keys do nothing
        itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                      (SIDE_WORN, 2, 3), (SIDE_MINE, 0, 16))
        self.assertIn("click", self._kinds())
        self.assertEqual(self._held(), ["aim"])

    def test_two_places_in_one_list_is_refused_rather_than_scrolled_twice(self):
        """Fallout has no order to a list that a player could rearrange, so
        this was already a drag that did nothing. It is refused now because
        settling the destination would scroll the source out from under the
        press."""
        with self.assertRaises(itemmove.CannotMove):
            itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                          (SIDE_MINE, 0, 16), (SIDE_MINE, 5, 16))
        self.assertEqual(self.events, [])

    def test_one_hand_to_the_other_is_still_a_move(self):
        """The worn slots never scroll, so the two points cannot disturb each
        other and swapping hands stays a thing to do."""
        itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                      (SIDE_WORN, 1, 3), (SIDE_WORN, 2, 3))
        self.assertEqual(self._held(), ["aim"])

    def test_the_press_is_given_time_to_be_noticed(self):
        """**The bug that made every move a no-op.** Fallout polls its input a
        frame at a time, and the drag used to start servoing twenty
        milliseconds after the press -- so the engine looked, found the pointer
        already gone, and never lifted the item. Measured against the running
        game by its own sounds: no pause meant no ipickup1 at all, while a
        third of a second meant ipickup1, iputdown, and the item in the hand.

        The clock here is the test's own, so this asserts the wait exists
        rather than sitting through it."""
        clock = itemmove.time
        started = clock.now
        marks = []
        real_down, real_up = itemmove.mouse_down, itemmove.mouse_up
        itemmove.mouse_down = lambda *a, **k: (marks.append(clock.now),
                                               real_down())
        itemmove.mouse_up = lambda *a, **k: (marks.append(clock.now),
                                             real_up())
        itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                      (SIDE_WORN, 2, 3), (SIDE_MINE, 0, 16))
        down, up = marks[0], marks[1]
        self.assertGreaterEqual(down - started, 0.0)
        self.assertGreaterEqual(up - down,
                                itemmove.GRAB_SETTLE + itemmove.DROP_SETTLE)

    def test_nothing_is_typed_between_the_press_and_the_release(self):
        """A keystroke reaches the engine's own pick-up loop, and one arriving
        mid-hold threw the aim off the panel entirely -- measured landing at
        (346,669), on the interface bar, with the item still on the cursor. So
        the travel is servoed off memory and the script is not asked."""
        typed = []
        itemmove.guarded_tap = lambda _h, key, **_k: (
            typed.append((len(self.events), key)) or self.finder.key(key))
        itemmove.drag(self.finder, 1, (262, 145, 499, 377),
                      (SIDE_WORN, 2, 3), (SIDE_MINE, 0, 16))
        kinds = self._kinds()
        held = range(kinds.index("down"), kinds.index("up"))
        self.assertFalse([k for at, k in typed if at in held],
                         "a key was pressed while the item was held")


if __name__ == "__main__":
    unittest.main()
