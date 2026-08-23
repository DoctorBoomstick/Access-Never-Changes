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


def click_item_slot(proc, hwnd, log_path: Optional[str] = None
                    ) -> Tuple[bool, str]:
    """Click the interface bar's item slot, which ARMS the active item.

    Not "uses" -- arms. The engine switches to cursor mode 3, the use
    crosshair, and waits to be told what to use the item on. That second step
    is the player's, and it is what makes one key serve a stimpak, a lockpick
    and a brick of plastic explosive: the target decides what the item does.

    Bypassing it was tried, through sfall's `use_item_on_dude`, and it was a
    mistake twice over -- it skips the action point cost, and it applies the
    item to the PLAYER whatever the item is, which points explosives at the
    person holding them. See the note in gl_world.ssl's report_active.

    **Aimed through the script, not through MenuMouse.** MenuMouse reads the
    cursor pair the engine keeps for the main menu, and in a loaded game it
    still moves -- which is what made it look serviceable -- but it does not
    agree with the real pointer, and the gap grows towards the bottom of the
    screen. Measured against this slot, whose rectangle is y 694 to 761:

        target (632,727) -- MenuMouse says it arrived at (632,727)
                            the pointer was really at (648,767)

    Six pixels below the button's bottom edge, so the click landed on the bar
    and hit nothing while the servo reported success. Reading through the
    script instead lands it at (632,728), on the slot.
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

    # The interface bar only exists in a loaded game, so the script is always
    # there to ask. MenuMouse stays only as a fallback for a caller with no log
    # path, and it is the wrong answer whenever the real one is available.
    ok, _where, why = aim_to(proc, hwnd, *slot[0].centre(bar),
                             log_path=log_path,
                             reader=None if log_path else MenuMouse(proc))
    if not ok:
        return False, "Cannot reach the item slot: {}.".format(why or "no answer")
    mouse_click("left", settle=0.5)
    time.sleep(0.6)
    return True, ""


def use(proc, hwnd, side: int, index: int, active: bool,
        log_path: Optional[str] = None) -> Tuple[bool, str]:
    """Arm the chosen item. Returns (done, what to say).

    Refuses clearly rather than clicking hopefully. A refusal that says what to
    do about it is worth more here than an attempt that starts a fight.
    """
    if side != SIDE_WORN or index not in HAND_INDEXES:
        return False, "Put it in one of your hands first, then use it."

    if not active:
        # No blind key-pressing to "fix" this. Which hand is live is something
        # the mod can read and the player can change, and an unmeasured guess at
        # swapping it is what started a fight once already.
        return False, "Make it the active item first, then use it."

    return click_item_slot(proc, hwnd, log_path=log_path)


def drop(finder, proc, hwnd, side: int, index: int, total: int,
         log_path: Optional[str] = None) -> Tuple[bool, str]:
    """Drop the chosen item on the ground, by dragging it onto yourself.

    Aimed through the script for the same reason `click_item_slot` is: the
    inventory only exists in a loaded game, and in one MenuMouse does not agree
    with the real pointer. The error is smaller here than down on the interface
    bar, which is worse rather than better -- it is the size that lands on the
    row above the one you chose while reporting that it arrived.
    """
    from . import itemmove

    win = _panel(proc, PANEL_WIDTH, PANEL_HEIGHT)
    if win is None:
        return False, "The inventory is not open."
    if win.by_press(FIGURE) is None:
        return False, "Cannot find where to drop it."

    from ..input.send import mouse_down, mouse_up
    from .pointer import MenuMouse, aim_to

    reader = None if log_path else MenuMouse(proc)

    def go(x, y):
        return aim_to(proc, hwnd, x, y, log_path=log_path, reader=reader)

    rect = (win.left, win.top, win.width, win.height)
    try:
        src = itemmove._target(finder, hwnd, rect, side, index, total, None)
    except itemmove.CannotMove as exc:
        return False, str(exc).capitalize() + "."

    ok, _where, why = go(*src)
    if not ok:
        return False, "Cannot reach it: {}.".format(why or "no answer")
    time.sleep(0.1)
    mouse_down("left")
    try:
        figure = win.by_press(FIGURE)
        ok, _where, why = go(*figure.centre(win))
        if not ok:
            # Put it back where it came from rather than letting go at whatever
            # point the pointer stalled at.
            go(*src)
            return False, "Cannot reach the drop point: {}.".format(why or "")
        time.sleep(0.1)
    finally:
        mouse_up("left")
    time.sleep(0.4)
    return True, ""
