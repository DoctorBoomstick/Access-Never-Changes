"""The pause menu -- Escape or O on the map -- and its "are you sure" box.

It was announced as the bare words "escape menu" and nothing else, which is a
menu nobody can see with no way of knowing what is on it. The engine's own
loop (0x0048FC48) answers letters as well as clicks, so it was never
unreachable, only unsaid:

    S        save game                  (or button 500)
    L        load game                  (501)
    P        preferences                (502)
    E        exit to the main menu      (503) -- asks first
    D, O, Enter or Escape               done  (504)
    plus and minus                      brightness

Exit asks "are you sure?" through the engine's general dialog box
(0x0041CF20, from 0x004440B8), which takes Y or Enter for yes and N or Escape
for no. The box's words are message 0 of the list at 0x0058E940; the box
itself is a window that appears over the menu and stores its text nowhere, so
it is noticed as a new window rather than read.
"""

from __future__ import annotations

from typing import Optional, Set

from . import uiwindow
from ..i18n import tr

WINDOW_ID = 0x00663900      # the pause menu's GNW id
QUIT_MESSAGES = 0x0058E940  # the list the quit question comes from
QUIT_QUESTION = 0


def window_id(proc) -> Optional[int]:
    wid = proc.read_i32(WINDOW_ID)
    return wid if wid is not None and wid >= 0 else None


def live_ids(proc) -> Set[int]:
    try:
        return {w.id for w in uiwindow.live_windows(proc)}
    except Exception:
        return set()


def showing(proc) -> bool:
    """Is the pause menu open? Its id among the OPEN windows.

    Only ever asked while the game mode says the escape menu is up -- an id is
    reused once its window is gone, so on its own it proves nothing.
    """
    wid = window_id(proc)
    return wid is not None and wid in live_ids(proc)


def quit_question(proc) -> str:
    """"Are you sure you want to quit?", in the game's words when it has them."""
    try:
        from ..msg.memlist import read_message_list
        got = read_message_list(proc, QUIT_MESSAGES)
    except Exception:
        got = None
    if got is not None:
        for e in got.entries:
            if e.num == QUIT_QUESTION and e.text:
                return e.text
    return tr("pausemenu.quit", "Are you sure you want to quit?")
