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
from ..i18n import tr

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
    from .pointer import aim_ui

    # The bar is underneath the inventory window, so that has to go first.
    if _panel(proc, PANEL_WIDTH, PANEL_HEIGHT) is not None:
        guarded_tap(hwnd, "escape", settle=0.7)
        time.sleep(1.0)

    bar = _panel(proc, BAR_WIDTH, BAR_HEIGHT)
    if bar is None:
        return False, tr("items.no_bar", "Cannot find the interface bar.")
    slot = [b for b in bar.buttons if (b.left, b.top) == BAR_ITEM_SLOT]
    if not slot:
        return False, tr("items.no_slot", "Cannot find the item slot.")

    # `aim_ui` tries the memory reader first and falls back to the script when
    # it cannot converge, so a caller with no log path still gets the fast
    # attempt and a caller with one still gets the reliable second try.
    ok, _where, why = aim_ui(proc, hwnd, *slot[0].centre(bar),
                             log_path=log_path)
    if not ok:
        return False, tr("items.slot_unreachable", "Cannot reach the item slot: {why}.",
                         why=why or tr("items.no_answer", "no answer"))
    mouse_click("left", settle=0.5)
    time.sleep(0.6)
    return True, ""
