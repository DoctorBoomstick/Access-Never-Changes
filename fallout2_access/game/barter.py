"""Make the offer.

The barter screen's two decisions live on two small buttons at the bottom of
the panel below the conversation: **OFFER** on the left, under your side, and
**TALK** on the right, under theirs. Between them they end a trade -- one by
doing it and one by walking away.

**Finding OFFER took a sighted person, and that is worth writing down.** Every
button GNW reports on that screen was read live: twelve item rows, eight scroll
arrows, two container-drill buttons, and these two. The two small ones carry
event codes 109 and 116, which are below 256 and therefore keyboard codes -- and
`uiwindow` says exactly what that means and what it does not:

    Read it as a hint to test, never as a route to assume.

Tested, and the hint was wrong. Pressing `m` does nothing at all; pressing `t`
closes the barter. So 116 really is bound to the key and 109 really is not, and
the only way to press OFFER is to click it. Every other candidate was tried
against a staged trade -- `o`, Enter, space, `b` -- and the engine did nothing
and printed nothing. The button was found in the end by someone reading the
screen aloud: "text near the bottom of this panel: OFFER".

The lesson is the one the loot window's TAKE ALL taught in the opposite
direction: a code below 256 means the engine *might* answer the key, and only
trying it settles which.

**What happened is read from the engine, not assumed from the click.** sfall's
barter-price hook fires again the moment an offer is made, with a flag saying
that is what caused it, and the totals as they stood. The tables clearing
afterwards is what says the trade went through; the prices staying put is what
says it did not. See `InventoryWatcher._price`.
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

from ..input.send import guarded_click
from ..memory.process import Process
from . import uiwindow
from ..i18n import tr

# The panel below the conversation, and the two buttons on it. Sized rather
# than positioned, because the high-resolution patch moves windows and does not
# resize this one.
PANEL_WIDTH = 640
PANEL_HEIGHT = 191

# The codes the two buttons raise. OFFER is a click and only a click; TALK is
# also on the `t` key, which the engine really does answer.
OFFER_CODE = 109
TALK_CODE = 116


def panel(proc: Process) -> Optional[uiwindow.Window]:
    """The barter panel, identified by having both of its buttons.

    Both, not either: the dialogue screen puts up a panel of this size without
    a barter on it, and clicking where OFFER would be is not something to do on
    a guess.
    """
    win = uiwindow.live_window_with(proc, PANEL_WIDTH, PANEL_HEIGHT,
                                    release=OFFER_CODE)
    if win is None:
        return None
    return win if win.by_code(TALK_CODE) is not None else None


def offering(proc: Process) -> bool:
    """Is there a barter on screen with an offer to make?"""
    return panel(proc) is not None


def offer(proc: Process, hwnd: int,
          log_path: Optional[str] = None) -> Tuple[bool, str]:
    """Press OFFER. Returns whether the click was sent, and why not if not.

    Deliberately says nothing about the outcome. What the shopkeeper did with
    the offer arrives a moment later through the price hook, and reporting a
    trade because a click was sent would be exactly the kind of claim this
    project refuses everywhere else.
    """
    from .pointer import aim_ui

    win = panel(proc)
    if win is None:
        return False, tr("barter.not_bartering", "You are not bartering.")
    button = win.by_code(OFFER_CODE)
    if button is None:
        return False, tr("barter.no_offer", "Cannot find the offer button.")
    ok, _where, why = aim_ui(proc, hwnd, *button.centre(win), log_path=log_path)
    if not ok:
        return False, why or tr("barter.offer_unreachable", "Cannot reach the offer button.")
    guarded_click(hwnd, "left")
    time.sleep(0.2)
    return True, ""
