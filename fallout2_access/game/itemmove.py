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

from ..input.send import guarded_click, mouse_down, mouse_up, require_focus
from . import uiwindow
from .inventory import SIDE_MINE, SIDE_THEIRS, SIDE_WORN
from .pointer import aim_to

# Event codes the engine gives each visible row, by side.
ROW_CODE = {SIDE_MINE: 1000, SIDE_THEIRS: 2000}

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

# How many rows a list shows at once. Read off the button table rather than
# assumed -- there are exactly six of each -- but kept here as the fallback for
# arithmetic when the table has not been read yet.
VISIBLE_ROWS = 6

# The scroll-up buttons, one per list, identified by their event codes. Measured
# from the live loot window: the left list's arrows raise 328 and 336, the right
# list's 397 and 401, with the upper rectangle of each pair being "up".
SCROLL_UP = {SIDE_MINE: 328, SIDE_THEIRS: 397}
SCROLL_DOWN = {SIDE_MINE: 336, SIDE_THEIRS: 401}


class CannotMove(RuntimeError):
    """The move was not attempted, and nothing was clicked."""


def _window(finder, rect: Tuple[int, int, int, int]) -> uiwindow.Window:
    """The live item window, through the caching finder.

    Always the finder, never a bare search: the search reads a quarter of a
    gigabyte and takes two seconds, and doing that between a keypress and its
    answer is exactly the dead air this is meant to avoid.
    """
    win = finder.at(*rect)
    if win is None:
        raise CannotMove("cannot find the item window in memory")
    if not win.buttons:
        raise CannotMove("the item window has no buttons to click")
    return win


def _row_button(win: uiwindow.Window, side: int, row: int):
    base = ROW_CODE.get(side)
    if base is None:
        raise CannotMove("that list has no rows to click")
    button = win.by_press(base + row)
    if button is None:
        raise CannotMove("the engine is not drawing a row {}".format(row + 1))
    return button


def scroll_to_top(finder, hwnd: int, win: uiwindow.Window, side: int,
                  count: int, log_path=None) -> None:
    """Put the list at the top, by pressing up more times than it can scroll.

    Deliberately not clever. Pressing the up arrow `count` times cannot leave a
    list of `count` items anywhere but the top, whatever the arrow's step size
    turns out to be, and it needs nothing read from memory to be sure of it.
    """
    if count <= VISIBLE_ROWS:
        return          # a list that fits cannot be scrolled
    code = SCROLL_UP.get(side)
    if code is None:
        return
    button = win.by_press(code)
    if button is None:
        raise CannotMove("cannot find the scroll control")
    ok, _where, why = aim_to(finder.proc, hwnd, *button.centre(win), log_path=log_path)
    if not ok:
        raise CannotMove("cannot reach the scroll control: {}".format(why))
    # Aim once, then click repeatedly -- the arrow does not move.
    for _ in range(count):
        guarded_click(hwnd, "left", settle=0.05)


def _target(finder, hwnd, rect, side, index, total, log_path):
    """The screen point for one list position, having scrolled it into view."""
    win = _window(finder, rect)

    if side == SIDE_WORN:
        # A fixed slot: nothing to scroll, and the index IS the slot. This is
        # the destination half of equipping something -- picking an item up puts
        # it on the cursor, and the slot is where it goes down.
        code = WORN_CODE.get(index)
        button = code is not None and win.by_press(code) or None
        if button is None:
            raise CannotMove("cannot find that equipment slot")
    else:
        scroll_to_top(finder, hwnd, win, side, total, log_path)
        row = index
        if row >= VISIBLE_ROWS:
            # The list is at the top and the item is still off screen, so it
            # needs scrolling down by a known amount -- the next piece of work.
            # Refusing is the honest answer; clicking the wrong row is not.
            raise CannotMove(
                "that item is item {} and only {} fit on screen"
                .format(index + 1, VISIBLE_ROWS))
        button = _row_button(win, side, row)
    return button.centre(win)


def drag(finder, hwnd: int, rect: Tuple[int, int, int, int],
         source: Tuple[int, int, int], target: Tuple[int, int, int],
         log_path: Optional[str] = None) -> None:
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
    """
    require_focus(hwnd)
    src = _target(finder, hwnd, rect, source[0], source[1], source[2], log_path)
    ok, _where, why = aim_to(finder.proc, hwnd, *src, log_path=log_path)
    if not ok:
        raise CannotMove("cannot put the pointer on that item: {}".format(why))

    time.sleep(0.08)
    mouse_down("left")
    try:
        dst = _target(finder, hwnd, rect, target[0], target[1], target[2],
                      log_path)
        ok, _where, why = aim_to(finder.proc, hwnd, *dst, log_path=log_path)
        if not ok:
            # Release back where it came from rather than wherever the pointer
            # got stuck. Dropping an item at an unknown point in the window is
            # the one outcome worse than not moving it.
            aim_to(finder.proc, hwnd, *src, log_path=log_path)
            raise CannotMove("cannot reach that slot: {}".format(why))
        time.sleep(0.08)
    finally:
        # Always release. A button left down leaves the game holding an item
        # that nothing on screen explains and no later keypress will free.
        mouse_up("left")
    time.sleep(0.15)
