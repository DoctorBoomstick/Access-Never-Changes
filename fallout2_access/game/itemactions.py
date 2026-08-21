"""Doing the things the item menu offers.

The menu itself lives in gl_inven.ssl, because arrows and Enter have to be
swallowed while it is up and only the keypress hook can swallow a key. The
actions live here, because they need the pointer and the script has no pointer.

**Use it** ends in a click on the interface bar's ITEM SLOT. That is the only
route to using a carried item that has been found: no cursor mode means "use an
item", and the inventory window has no Use button -- its only controls are the
list rows, the worn slots, the character figure and Done.

Two things make that click dangerous, and both are checked rather than hoped:

  * the slot acts on the ACTIVE item, and clicking it with a WEAPON live
    ATTACKS. That started a fight and dropped a live charge during development.
  * the item has to be in a hand at all. Using something from the pack is not
    something this route can do.

**Drop it** drags the item onto the character figure. Measured, and measured by
accident: a drag there while trying to "use" an explosive put it on the floor
instead. Worth keeping precisely because dropping had no route either.
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

# The inventory's own panel, and the character figure in the middle of it.
PANEL_WIDTH = 499
PANEL_HEIGHT = 377
FIGURE = 2500

# The interface bar, and the item slot on it. The slot is identified by its
# rectangle within the bar rather than by an event code: its code is -20, which
# names nothing and is shared with no other control worth clicking.
BAR_WIDTH = 800
BAR_HEIGHT = 100
BAR_ITEM_SLOT = (427, 26)

# The middle column of the inventory: armour, then the two hands.
SIDE_WORN = 2
HAND_INDEXES = (1, 2)


def _panel(proc, width, height):
    from . import uiwindow
    for win in uiwindow.live_windows(proc, buttons=True):
        if (win.width, win.height) == (width, height):
            return win
    return None


def click_item_slot(proc, hwnd) -> Tuple[bool, str]:
    """Click the interface bar's item slot: the game's own "use this" control.

    Assumes the caller has already established that the active item is worth
    using. This slot acts on whatever is live, and with a weapon there it
    ATTACKS -- so every caller checks first, and none of them checks here.
    """
    from ..input.send import guarded_tap, mouse_click
    from .pointer import MenuMouse, aim_to

    # The bar is underneath the inventory window, so that has to go first.
    if _panel(proc, PANEL_WIDTH, PANEL_HEIGHT) is not None:
        guarded_tap(hwnd, "escape", settle=0.7)
        time.sleep(1.0)

    bar = _panel(proc, BAR_WIDTH, BAR_HEIGHT)
    if bar is None:
        return False, "Cannot find the interface bar."
    slot = [b for b in bar.buttons if (b.left, b.top) == BAR_ITEM_SLOT]
    if not slot:
        return False, "Cannot find the item slot."

    ok, _where, why = aim_to(proc, hwnd, *slot[0].centre(bar),
                             reader=MenuMouse(proc))
    if not ok:
        return False, "Cannot reach the item slot: {}.".format(why or "no answer")
    mouse_click("left", settle=0.5)
    time.sleep(0.6)
    return True, ""


def use(proc, hwnd, side: int, index: int, active: bool) -> Tuple[bool, str]:
    """Use the chosen item. Returns (done, what to say).

    Refuses clearly rather than clicking hopefully. A refusal that says what to
    do about it is worth more here than an attempt that starts a fight.
    """
    from ..input.send import guarded_tap

    if side != SIDE_WORN or index not in HAND_INDEXES:
        return False, ("Put it in one of your hands first, then use it.")

    if not active:
        # One press, not a loop. `b` swaps which hand is live, and pressing it
        # blind and repeatedly to "fix" an unmeasured state is what started a
        # fight once already.
        guarded_tap(hwnd, "b", settle=0.6)
        time.sleep(0.8)

    return click_item_slot(proc, hwnd)


def drop(finder, proc, hwnd, side: int, index: int, total: int
         ) -> Tuple[bool, str]:
    """Drop the chosen item on the ground, by dragging it onto yourself."""
    from . import itemmove

    win = _panel(proc, PANEL_WIDTH, PANEL_HEIGHT)
    if win is None:
        return False, "The inventory is not open."
    if win.by_press(FIGURE) is None:
        return False, "Cannot find where to drop it."

    from ..input.send import mouse_down, mouse_up
    from .pointer import MenuMouse, aim_to

    rect = (win.left, win.top, win.width, win.height)
    try:
        src = itemmove._target(finder, hwnd, rect, side, index, total, None)
    except itemmove.CannotMove as exc:
        return False, str(exc).capitalize() + "."

    ok, _where, why = aim_to(proc, hwnd, *src, reader=MenuMouse(proc))
    if not ok:
        return False, "Cannot reach it: {}.".format(why or "no answer")
    time.sleep(0.1)
    mouse_down("left")
    try:
        figure = win.by_press(FIGURE)
        ok, _where, why = aim_to(proc, hwnd, *figure.centre(win),
                                 reader=MenuMouse(proc))
        if not ok:
            # Put it back where it came from rather than letting go at whatever
            # point the pointer stalled at.
            aim_to(proc, hwnd, *src, reader=MenuMouse(proc))
            return False, "Cannot reach the drop point: {}.".format(why or "")
        time.sleep(0.1)
    finally:
        mouse_up("left")
    time.sleep(0.4)
    return True, ""
