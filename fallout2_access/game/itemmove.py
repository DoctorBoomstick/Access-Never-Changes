"""Move the item the list cursor is on, by dragging the row the engine drew it in.

This is the last thing in the inventory that needed a pointer, and it is done
the same way walking is: the mod puts the pointer where the player already said,
the game decides what that means, and nothing is claimed until the game confirms
it happened.

**It is a drag, not a click, and that was the whole bug.** Fallout's inventory
moves items by pressing on one, moving, and releasing over the destination. A
press and release in the same place picks the item up and sets it straight back
down. An earlier version sent exactly that, twice, and reported the resulting
nothing as "holding" the item -- while the aim was landing to the pixel and both
clicks were no-ops. Confirmed by sending a real press-move-release against a
live game: the spear left the carried list on the first attempt.

**Rows are the engine's own buttons.** Each list is six buttons with consecutive
event codes -- 1000..1005 down the player's side, 2000..2005 down the other --
read live out of the window's button list. So a row's rectangle is not measured
off a screenshot or computed from a layout table; it is the rectangle the engine
is drawing into, whatever the resolution and whatever the high-res patch did.

**The scroll position is caused, not read.** A list taller than six rows needs to
know how far it has been scrolled, and the obvious answer -- go and find the
offset in memory -- would have added another absolute address to a project whose
addresses are already the reason it does not run on GOG. It is not needed. The
scroll-up arrow is a button too, so clicking it more times than the list is long
puts the list at the top *by construction*, and from there row and index are the
same number. One aim, several clicks, no address, and it cannot drift.

**Verified afterwards, not before.** The mod cannot ask "is the pointer on row
three" the way it can ask which hex the pointer is over -- there is no such
question for a UI. What it can do is read both inventories after the click and
say what actually moved, which is a stronger claim than a prediction: it is what
happened. For movement a wrong click is silent and costly, so it is refused; for
an item it is visible and recoverable, so it is reported.
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

import os

from ..input.send import (guarded_click, guarded_click_with, guarded_tap,
                          mouse_down, mouse_up, require_focus)
from . import uiwindow
from .inventory import (SIDE_MINE, SIDE_MY_OFFER, SIDE_THEIRS,
                        SIDE_THEIR_OFFER, SIDE_WORN)
from .pointer import aim_to, aim_ui
from ..i18n import tr

# -- how long the engine needs to see a button before the pointer may move ----
#
# **This is what made every move a no-op, and it is a fact about frames rather
# than about pixels.** Fallout polls its input once a frame. A press it has not
# looked at yet is a press that happens wherever the pointer has got to by the
# time it looks -- and the drag started servoing twenty milliseconds after
# `mouse_down`, which is well inside one frame at any speed the game runs at.
#
# The engine therefore never saw a press on the item at all. Measured against
# the live game by watching the sounds it plays, which is the engine saying what
# it thinks happened:
#
#     press, move immediately, release on the slot     no sound whatsoever
#     press, wait 0.3s, move, wait 0.3s, release       ipickup1 ... iputdown,
#                                                      and the item is in the
#                                                      hand: 16 carried -> 15
#
# `ipickup1` is the lift and `iputdown` is the placement. Silence was the engine
# reporting, accurately, that nothing had been picked up -- while the mod
# reported the aim as perfect, because the aim WAS perfect. Both halves were
# right and the move still did not happen.
#
# The same measurement is why a plain click was not silent: `mouse_click` holds
# for 60ms without moving, which is long enough to be seen, so a click lifted
# the item and set it straight back down -- exactly what this module's opening
# docstring has always said a click does.
GRAB_SETTLE = 0.3
DROP_SETTLE = 0.3

# -- the drag that does not have to happen -----------------------------------
#
# sfall has a setting for exactly the thing this module was built to do the hard
# way. `ItemMoveSkipDragKey` in ddraw.ini names a key that, held down, turns a
# plain click on an item into a move to the other list -- no press, no travel,
# no release. It ships enabled, set to left Ctrl.
#
# That halves the work and rather more than halves the time. A drag aims twice,
# and an aim is a servo that asks the game where the pointer is once per step;
# a modifier click aims once and lets the engine choose the destination. The
# whole "Moving X..." pause the player learned to sit through is one of those
# two aims.
#
# **Read from the game's own ddraw.ini, never assumed.** The setting can be
# turned off, and it can be moved to another key. Assuming left Ctrl on an
# install that has disabled it would send a plain click, which does not move an
# item -- it picks it up onto the cursor and leaves it there, which is the
# silent half-done state this module's docstring already warns about.
_MODIFIER_SCANCODES = {29: "lctrl", 157: "rctrl", 42: "lshift", 54: "rshift"}


def _setting(game_dir: str, name: str) -> Optional[str]:
    """One ddraw.ini setting, as the key name this mod can send."""
    path = os.path.join(game_dir, "ddraw.ini")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.lower().startswith(name):
                    _, _, value = line.partition("=")
                    return _MODIFIER_SCANCODES.get(int(value.strip() or 0))
    except (OSError, ValueError):
        return None
    return None


def fast_move_keys(game_dir: Optional[str],
                   whole_stack: bool = False) -> Optional[list]:
    """The keys to hold so that a click moves an item without a drag.

    `ItemMoveSkipDragKey` -- left Ctrl -- is the one that matters: it turns the
    click into a move, so nothing has to be dragged. That is all this holds by
    default, and **holding more than that was a bug worth being clear about.**

    `ItemFastMoveKey` -- left Shift -- does something quite different: it takes
    the whole stack and skips the "Move Items" window that would otherwise ask
    how many. Holding it on every move meant every stack went across entire and
    the player was never asked. Twenty-four stimpaks or two hundred caps, all of
    it, silently. Fallout's own rule is that you hold that key when you mean
    "all of it", and the mod now follows the same rule rather than deciding for
    the player.

    So `whole_stack` is the caller saying the player asked for everything. Left
    alone, a stack puts the question up and the quantity window answers it.

    Either key being disabled in ddraw.ini returns None and the caller drags,
    rather than sending a click that half works.
    """
    if not game_dir:
        return None
    skip = _setting(game_dir, "itemmoveskipdragkey")
    if skip is None:
        return None
    if not whole_stack:
        return [skip]
    fast = _setting(game_dir, "itemfastmovekey")
    if fast is None:
        return None
    return [skip] if skip == fast else [skip, fast]

# Event codes the engine gives each visible row, by side. The two offer lists
# are the barter window's middle pair, read off the live window: 2300 up the
# player's offer and 2400 up the shopkeeper's.
ROW_CODE = {
    SIDE_MINE: 1000,
    SIDE_THEIRS: 2000,
    SIDE_MY_OFFER: 2300,
    SIDE_THEIR_OFFER: 2400,
}

# The worn slots down the middle of the inventory window, by the slot index
# gl_inven.ssl reports: 0 armour, 1 and 2 the two hands.
#
# The hands are NOT in drawn order, which is why this is measured rather than
# assumed. Dragging a spear onto button 1007 -- the left-hand one on screen --
# put it in slot index 2, the slot the mod calls "Item 2". So the on-screen
# left/right order and the engine's slot order run opposite ways. Guessing from
# the layout would have equipped the wrong hand every time, and the mod would
# have announced the slot the player did not choose.
#
# 1008 is armour, confirmed by geometry: it is the only one drawn above the
# other two, and a weapon dragged to a hand did not land there.
WORN_CODE = {0: 1008, 1: 1006, 2: 1007}

# How many rows a list shows at once, when the window cannot be asked.
#
# **Not a constant, and assuming it was would be wrong in barter.** The
# inventory and loot windows draw six rows a list; the barter window is four
# lists across the same space and draws THREE. Six would compute a row number
# off the bottom of the pane and press a button belonging to another control,
# so `visible_rows` counts the buttons the engine actually made and this is
# only the fallback for arithmetic done before the window has been read.
VISIBLE_ROWS = 6


def visible_rows(win: uiwindow.Window, side: int, default: int = VISIBLE_ROWS) -> int:
    """How many rows of `side` the engine is drawing, counted from its buttons.

    The same discipline as everything else here: the row rectangles are read
    from the live window rather than measured off a layout, so this is read too
    rather than being a second table that has to be kept in step with the first.

    **Counting codes alone gave nine, and nine is what broke equipping.** The
    carried list's rows are 1000 to 1005 and the three worn slots are 1006,
    1007 and 1008 -- consecutive, in the same window, on the same button list.
    A walk that stops at the first missing code does not stop until it has
    swallowed all three, so a six-row pane measured as nine.

    Everything downstream then went wrong quietly and consistently. Sixteen
    carried items scrolled seven rows instead of ten, the wanted item was left
    off screen, and `ROW_CODE + 8` addressed button 1008 -- the ARMOUR slot. So
    the mod pressed on the item, scrolled the list under it, and released over
    a piece of armour. Confirmed against the game's own log, which recorded
    exactly those seven scroll clicks and a final aim at (460,358): the centre
    of the armour slot, to the pixel.

    So a row is identified by where it is drawn as well as by its code. The six
    rows of a list are one column -- the same left and right edge, stacked --
    and the worn slots are elsewhere on the panel entirely. That is a fact
    about the window rather than a table of exceptions, so it holds for the
    barter panes too without anybody having to remember to add them.
    """
    base = ROW_CODE.get(side)
    if base is None:
        return default
    first = win.by_press(base)
    if first is None:
        return default
    n = 1
    while n < 32:
        button = win.by_press(base + n)
        if button is None:
            break
        if (button.left, button.right) != (first.left, first.right):
            break
        n += 1
    return n

# The scroll-up buttons, one per list, identified by their event codes. Measured
# from the live loot window: the left list's arrows raise 328 and 336, the right
# list's 397 and 401, with the upper rectangle of each pair being "up".
SCROLL_UP = {SIDE_MINE: 328, SIDE_THEIRS: 397,
             SIDE_MY_OFFER: 329, SIDE_THEIR_OFFER: 388}
SCROLL_DOWN = {SIDE_MINE: 336, SIDE_THEIRS: 401,
               SIDE_MY_OFFER: 337, SIDE_THEIR_OFFER: 374}

# The pairs of lists the engine will move an item between on a modifier click.
# It chooses the destination itself, so the shortcut is only safe where there
# is one place it could mean -- and in barter that is NOT "the other side of
# the window": an item clicked in your own inventory goes onto your own half of
# the table, not into the shopkeeper's pack.
FAST_PAIRS = (
    frozenset((SIDE_MINE, SIDE_THEIRS)),
    frozenset((SIDE_MINE, SIDE_MY_OFFER)),
    frozenset((SIDE_THEIRS, SIDE_THEIR_OFFER)),
)


class CannotMove(RuntimeError):
    """The move was not attempted, and nothing was clicked."""


def _window(finder, rect: Tuple[int, int, int, int],
            need=()) -> uiwindow.Window:
    """The live item window, through the caching finder.

    Always the finder, never a bare search: the search reads a quarter of a
    gigabyte and takes two seconds, and doing that between a keypress and its
    answer is exactly the dead air this is meant to avoid.

    `need` is the buttons about to be pressed; see WindowFinder.at for why a
    window found without them is not the live one.
    """
    win = finder.at(*rect, need=need)
    if win is None:
        raise CannotMove(tr("move.no_window", "cannot find the item window in memory"))
    if not win.buttons:
        raise CannotMove(tr("move.no_buttons", "the item window has no buttons to click"))
    return win


def drawn_row(index: int, total: int) -> int:
    """Which screen row holds the item the script calls `index`.

    **The engine draws these lists backwards.** The script walks an inventory
    with inven_ptr and reports what it finds in that order; the window draws the
    same items bottom-to-top. So the mod's "first item" is the engine's LAST
    row, and pressing row zero for index zero grabs a different object entirely.

    That was the bug where moving one item moved its neighbour. It is worth
    being precise about why it survived: the move was verified afterwards by
    counting both lists, and the counts were always right -- something did leave
    the carried list every time. Counting cannot tell you WHICH thing moved, so
    a wrong row looked exactly like a correct one.

    Measured twice, in opposite directions, with the same two items:

      * carried [Healing Powder, Spear], dragged index 0 -> the Spear moved
      * carried [Healing Powder, Spear], dragged index 1 -> the Powder moved

    One rule fits both, and the second was run as a prediction rather than an
    explanation: the reversal was inferred from the first, then used to say in
    advance what the second would do.

    Clamped at zero so a stale `total` cannot produce a negative row, which
    would silently address a button belonging to some other control.
    """
    return max(0, total - 1 - index)


def _row_button(win: uiwindow.Window, side: int, row: int):
    base = ROW_CODE.get(side)
    if base is None:
        raise CannotMove(tr("move.no_rows", "that list has no rows to click"))
    button = win.by_press(base + row)
    if button is None:
        raise CannotMove(tr("move.no_row", "the engine is not drawing a row {row}",
                            row=row + 1))
    return button


def scroll_to_top(finder, hwnd: int, win: uiwindow.Window, side: int,
                  count: int, log_path=None, rows: int = VISIBLE_ROWS) -> None:
    """Put the list at the top, by pressing up more times than it can scroll.

    The fallback, for when the keyboard route in `scroll_to` cannot be shown to
    have worked. Deliberately not clever: pressing the up arrow more times than
    the list can scroll cannot leave it anywhere but the top, whatever the
    arrow's step size turns out to be, and it needs nothing read from memory to
    be sure of it.

    **`count - rows` presses, not `count`.** The furthest a list of `count`
    items can be scrolled in a pane of `rows` is `count - rows` rows -- measured
    on the live window, where End followed by single clicks back to the top came
    to exactly ten on sixteen items in six rows. So the extra `rows` presses
    were pressing a dead arrow, and a press costs a tenth of a second whether or
    not it does anything.
    """
    if count <= rows:
        return          # a list that fits cannot be scrolled
    code = SCROLL_UP.get(side)
    if code is None:
        return
    button = win.by_press(code)
    if button is None:
        raise CannotMove(tr("move.no_scroll", "cannot find the scroll control"))
    ok, _where, why = aim_ui(finder.proc, hwnd, *button.centre(win), log_path=log_path)
    if not ok:
        raise CannotMove(tr("move.scroll_unreachable",
                            "cannot reach the scroll control: {why}", why=why))
    # Aim once, then click repeatedly -- the arrow does not move.
    for _ in range(count - rows):
        guarded_click(hwnd, "left", settle=0.05)


def scroll_down(finder, hwnd: int, win: uiwindow.Window, side: int,
                presses: int, log_path=None) -> None:
    """Step a list down, from the top, by a known number of rows.

    **One press is one row.** Measured rather than assumed, and measured the
    only way that actually proves it: the list was put at the top, the down
    arrow was pressed once, the top row was moved with a modifier click, and
    the item that arrived in the offer table was named. With seven items on a
    three-row pane, the top row at rest holds the script's last item; after one
    press it held the one before it. That is a step of exactly one row, and it
    is a fact about the item that moved rather than about a number this mod
    read back and hoped meant what it wanted.

    Only ever called straight after `scroll_to_top`, so the starting point is
    known by construction and the offset here is a count rather than a
    position. That is the same trick the scroll-up has always used, and it is
    why neither needs an address.
    """
    if presses <= 0:
        return
    code = SCROLL_DOWN.get(side)
    if code is None:
        raise CannotMove(tr("move.no_scrolling", "that list cannot be scrolled"))
    button = win.by_press(code)
    if button is None:
        raise CannotMove(tr("move.no_scroll", "cannot find the scroll control"))
    ok, _where, why = aim_ui(finder.proc, hwnd, *button.centre(win), log_path=log_path)
    if not ok:
        raise CannotMove(tr("move.scroll_unreachable",
                            "cannot reach the scroll control: {why}", why=why))
    for _ in range(presses):
        guarded_click(hwnd, "left", settle=0.05)


# -- the scrolling that needs no pointer at all ------------------------------
#
# gl_inven.ssl has logged Home, End, Page Up and Page Down as INVEN:listkey and
# passed them through since the day it was written, with a note saying that if
# the engine acts on them then the scroll hunt is unnecessary. Nobody had ever
# looked at what came back. The engine acts on all four.
#
# Measured on the live inventory, sixteen items in a six-row pane, and judged by
# the arrows' own dead flag rather than by anything this mod believed:
#
#     Home       up arrow goes dead        -- the list is at the top
#     End        down arrow goes dead      -- the list is at the bottom
#     Page Down  six rows, then clamps     -- exactly one pane
#     one click  one row                   -- as measured before
#
# So the whole "put it at the top by pressing up more times than it can scroll"
# pass -- an aim and sixteen clicks, about two seconds of the pause a player sat
# through after asking for an item to be moved -- is one keystroke. The pointer
# is only needed for the last few rows now, and often not at all.
ANCHOR_KEY = {"top": "home", "bottom": "end"}
PAGE_KEY = {"down": "pagedown", "up": "pageup"}

# GNW's "this button can do nothing", which on a scroll arrow means the list is
# already at that end. Established with the mouse rather than assumed from the
# flag's name: at rest the up arrow carried it, one click on the DOWN arrow --
# which is known to scroll, because it is what this module has always done --
# cleared it. That is the bit doing the one job, watched through a change caused
# by something else.
#
# It is what makes the keyboard route safe to take. An anchor that did not land
# says so, and the caller falls back to the arrows rather than pressing a row
# it merely hopes is the right one.
BUTTON_DEAD = 0x08


def at_end(win: uiwindow.Window, side: int, which: str) -> Optional[bool]:
    """Can this list still scroll that way? None when there is no arrow to ask."""
    code = (SCROLL_UP if which == "up" else SCROLL_DOWN).get(side)
    if code is None:
        return None
    button = win.by_press(code)
    if button is None:
        return None
    return bool(button.flags & BUTTON_DEAD)


def scroll_plan(wanted: int, most: int, rows: int):
    """(anchor, direction, pages, singles) -- the cheapest way to reach `wanted`.

    Both ends are free now, so the list is anchored at whichever one is nearer
    and then walked in. What is being minimised is SINGLE ROWS, not distance:
    a page is a keystroke costing a twentieth of a second, while one row is a
    click, and any row at all means the pointer has to be driven onto an arrow
    first. So a route with more pages and no remainder beats a shorter one that
    ends in three clicks, and a great many moves come out needing no pointer at
    all -- the first item of a long list is exactly the bottom anchor.
    """
    best = None
    for anchor, offset in (("top", 0), ("bottom", most)):
        delta = wanted - offset
        pages, singles = divmod(abs(delta), rows)
        cost = (singles > 0, singles, pages)
        if best is None or cost < best[0]:
            best = (cost, (anchor, "down" if delta >= 0 else "up",
                           pages, singles))
    return best[1]


def scroll_to(finder, hwnd: int, win: uiwindow.Window, side: int, wanted: int,
              most: int, rows: int, log_path=None) -> bool:
    """Put a list on a known scroll offset. True if it got there.

    False means the keyboard route could not be shown to have worked, and the
    caller should fall back to the arrows. It is never a guess: the anchor is
    checked against the arrow that reports whether the list can still move that
    way, so "it landed" is something the engine said.
    """
    anchor, direction, pages, singles = scroll_plan(wanted, most, rows)
    guarded_tap(hwnd, ANCHOR_KEY[anchor], settle=0.04)

    # Wait for it, rather than sleeping a fixed amount and hoping. The engine's
    # input loop is slow and uneven, and the arrow says when it is done.
    dead_end = "up" if anchor == "top" else "down"
    deadline = time.time() + 0.5
    landed = False
    while time.time() < deadline:
        fresh = finder.at(win.left, win.top, win.width, win.height)
        if fresh is not None and at_end(fresh, side, dead_end):
            landed = True
            break
        time.sleep(0.02)
    if not landed:
        return False

    for _ in range(pages):
        guarded_tap(hwnd, PAGE_KEY[direction], settle=0.06)
    if not singles:
        return True

    # The remainder, on the arrow, which is the only part that still needs the
    # pointer -- at most one pane's worth of rows however long the list is.
    code = (SCROLL_DOWN if direction == "down" else SCROLL_UP).get(side)
    button = win.by_press(code) if code is not None else None
    if button is None:
        return False
    ok, _where, why = aim_ui(finder.proc, hwnd, *button.centre(win),
                             log_path=log_path)
    if not ok:
        raise CannotMove(tr("move.scroll_unreachable",
                            "cannot reach the scroll control: {why}", why=why))
    for _ in range(singles):
        guarded_click(hwnd, "left", settle=0.05)
    return True


def scroll_for(index: int, total: int, rows: int) -> int:
    """How many rows down to scroll so that `index` is on screen.

    The engine draws these lists backwards, so the script's FIRST item is the
    one furthest down and needs the most scrolling -- see `drawn_row`. Scrolling
    just far enough puts the wanted item on the last visible row.

    It can never ask for more than the list has: for index 0 this comes to
    `total - rows`, which is exactly the furthest the engine will go, and for
    anything already on screen it comes to nothing. So the arithmetic cannot
    run past the end and land on a clamp the mod has not accounted for.
    """
    if total <= rows:
        return 0
    return max(0, drawn_row(index, total) - rows + 1)


def _target(finder, hwnd, rect, side, index, total, log_path, keyboard=False):
    """The screen point for one list position, having scrolled it into view."""
    if side == SIDE_WORN:
        need = (WORN_CODE[index],) if index in WORN_CODE else ()
    else:
        need = tuple(c for c in (ROW_CODE.get(side), SCROLL_UP.get(side),
                                 SCROLL_DOWN.get(side)) if c is not None)
    win = _window(finder, rect, need)

    if side == SIDE_WORN:
        # A fixed slot: nothing to scroll, and the index IS the slot. This is
        # the destination half of equipping something -- picking an item up puts
        # it on the cursor, and the slot is where it goes down.
        code = WORN_CODE.get(index)
        button = code is not None and win.by_press(code) or None
        if button is None:
            raise CannotMove(tr("move.no_equip_slot", "cannot find that equipment slot"))
    else:
        rows = visible_rows(win, side)
        down = scroll_for(index, total, rows)
        # The keyboard first, when it is allowed: Home or End anchors the list
        # in one keystroke and Page Up and Page Down cover it a pane at a time,
        # so only the last few rows cost a click and often none do. It reports
        # honestly whether it landed, and the arrows are the fallback.
        #
        # Otherwise: top first, which is guaranteed by pressing up more times
        # than the list can scroll, then down by exactly as many rows as it
        # takes. Both halves are counts from a known position rather than
        # readings, so neither needs a scroll offset in memory.
        #
        # **This used to refuse instead**, and on the barter window that meant
        # refusing nearly everything: its panes are three rows deep, so anything
        # but the last three items of a list was unreachable and the mod said so
        # rather than scrolling. The loot window hid it -- six rows covers most
        # containers -- but it was the same gap.
        done = (total > rows and keyboard
                and scroll_to(finder, hwnd, win, side, down, total - rows,
                              rows, log_path))
        if not done:
            scroll_to_top(finder, hwnd, win, side, total, log_path, rows)
            scroll_down(finder, hwnd, win, side, down, log_path)
        row = drawn_row(index, total) - down
        if not 0 <= row < rows:
            # Arithmetic, not the game, has gone wrong. Refusing is the honest
            # answer; pressing a row number outside the pane addresses a button
            # belonging to some other control.
            raise CannotMove(tr("move.out_of_view",
                                "cannot bring item {index} of {total} into view",
                                index=index + 1, total=total))
        button = _row_button(win, side, row)
    return button.centre(win)


def drag(finder, hwnd: int, rect: Tuple[int, int, int, int],
         source: Tuple[int, int, int], target: Tuple[int, int, int],
         log_path: Optional[str] = None, whole_stack: bool = False) -> None:
    """Drag an item from one list position to another.

    Fallout's inventory moves items by DRAGGING: press on the item, move, and
    release over the destination. That is not a detail -- a press and release in
    the same place picks the item up and puts it straight back down, so it does
    precisely nothing. An earlier version sent exactly that and reported the
    resulting silence as "holding" the item, which was a guess dressed as a fact:
    the aim was landing to the pixel and the clicks were no-ops.

    Both source and target are (side, index, total). The whole drag happens
    inside this call so the game is never left holding something between two
    keypresses -- a state the player cannot see and the mod cannot reliably
    detect.

    **Nothing is clicked between the press and the release, and that was the
    second whole bug.** Bringing a row into view is done by CLICKING a scroll
    arrow, and the destination used to be worked out after the button was
    already down -- so the first of those scroll clicks released the item over
    the arrow and the move became a pick-up-and-put-down with a lot of noise in
    front of it. Every move into or out of an equipment slot went that way,
    because the carried list is nearly always longer than the six rows that fit
    and therefore nearly always needs scrolling.

    It presented as "a burst of clicking and then nothing moved", which is
    exactly what it was: the clicks were real, they were the mod's own, and the
    drag they interrupted was the only thing that would have moved anything.

    So both endpoints are resolved -- scrolled, measured, turned into points --
    while the button is still up. The two lists scroll independently, so
    settling one cannot disturb the other; the one case where it could is two
    positions in the SAME list, which is refused above because it is not a move
    in the first place.
    """
    require_focus(hwnd)

    # Two places in one list is not somewhere to move an item to. Fallout has
    # no order to a list that a player could rearrange, so this was already a
    # drag that did nothing -- but it is refused rather than tolerated now,
    # because resolving both endpoints up front means the second scroll would
    # move the first row out from under the press.
    #
    # The worn slots are exempt: there are three of them, they never scroll,
    # and moving a weapon from one hand to the other is a real thing to want.
    if source[0] == target[0] and source[0] != SIDE_WORN:
        raise CannotMove(tr("move.same_list", "that is the list it is already in"))

    # The fast path: one aim instead of two, when the engine can be trusted to
    # pick the destination. It can when the move is simply "to the other list"
    # -- the two item lists have nowhere else to send something. It cannot when
    # the destination is a particular worn slot, because there are three of
    # those and sfall's own note says items "go to appropriate slots", which is
    # the engine's judgement and not the player's choice. So equipping still
    # drags, and that is the case where the extra seconds buy something.
    modifier = (fast_move_keys(getattr(finder.proc, "directory", None),
                               whole_stack=whole_stack)
                if frozenset((source[0], target[0])) in FAST_PAIRS else None)

    # Whether the keyboard may do the scrolling, and the rule is conservative
    # on purpose. Home and End are the WINDOW's keys: which of its lists they
    # move is not a thing this mod has measured, and the plain inventory -- the
    # only window open when it was measured -- has one list to move. So they are
    # used only where this drag scrolls at most one list, and there is nothing
    # for a wrong guess to disturb.
    #
    # That covers the two cases that matter. Equipping and unequipping scroll
    # the carried list and nothing else, which is the move that was slowest;
    # and a modifier click never resolves a destination at all, which is most of
    # bartering. A drag between two scrollable lists keeps the arrows, and the
    # note to leave behind is that measuring which list the keys move would hand
    # that case the same win.
    keyboard = modifier is not None or SIDE_WORN in (source[0], target[0])

    src = _target(finder, hwnd, rect, source[0], source[1], source[2], log_path,
                  keyboard=keyboard)

    if modifier is not None:
        ok, _where, why = aim_ui(finder.proc, hwnd, *src, log_path=log_path)
        if not ok:
            raise CannotMove(tr("move.item_unreachable",
                                "cannot put the pointer on that item: {why}",
                                why=why))
        # Held across the click and released in a `finally` inside
        # `mouse_click_with`. A Ctrl left down would silently rebind the whole
        # numpad to sfall's game speed controls.
        guarded_click_with(hwnd, modifier, "left")
        time.sleep(0.15)
        return

    # All the scrolling, for both lists, before anything is held down.
    dst = _target(finder, hwnd, rect, target[0], target[1], target[2], log_path,
                  keyboard=keyboard)

    ok, _where, why = aim_ui(finder.proc, hwnd, *src, log_path=log_path)
    if not ok:
        raise CannotMove(tr("move.item_unreachable",
                            "cannot put the pointer on that item: {why}", why=why))

    time.sleep(0.08)
    mouse_down("left")
    try:
        # Stand still until the engine has looked. Without this the pointer is
        # already gone by the time the press is polled and no item is ever
        # lifted -- see GRAB_SETTLE.
        time.sleep(GRAB_SETTLE)
        # **Servoed off memory, and the script is deliberately not asked.**
        # `aim_ui` asks it, and asking means pressing a key: the engine is
        # inside its own pick-up loop here, and a keystroke arriving in the
        # middle of it threw the aim clean off the panel -- measured landing at
        # (346,669), on the interface bar, with the item still on the cursor.
        # Nothing is typed between the press and the release now.
        ok, _where, why = aim_to(finder.proc, hwnd, *dst)
        if not ok:
            # Release back where it came from rather than wherever the pointer
            # got stuck. Dropping an item at an unknown point in the window is
            # the one outcome worse than not moving it.
            aim_to(finder.proc, hwnd, *src)
            time.sleep(DROP_SETTLE)
            raise CannotMove(tr("move.slot_unreachable", "cannot reach that slot: {why}",
                                why=why))
        time.sleep(DROP_SETTLE)
    finally:
        # Always release. A button left down leaves the game holding an item
        # that nothing on screen explains and no later keypress will free.
        mouse_up("left")
    time.sleep(0.15)
