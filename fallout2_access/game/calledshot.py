"""The called-shot window: where on the target an aimed attack goes.

An attack in an aimed mode -- N cycles to it on any weapon that allows one --
puts up a picture of the target with eight body parts down its two sides, each
with its chance to hit beside it. Choose one and the attack goes; Escape and
there is no attack. It is mouse-only and nothing in it was readable: the
labels and the numbers are drawn into the window and stored nowhere.

**Read out of the engine, at 0x00426218.** One function builds the window
(504x309), draws the parts and runs its own modal loop:

    buttons     release code 0 to 7, four down each side; the code is an
                index into two tables of hit locations, 0x0051803C for the
                left column and 0x0051804C for the right -- CODE_TO_LOC below
    Cancel      release code 27, which is also the Escape key
    the loop    ends on 27 or on any code from 0 to 7, and nothing else

So Escape is the game's own key here and works already. Choosing a part
needs its button clicked: codes 0 to 7 are not keys anyone can type.

**The chances come from the to-hit hook.** The window works each one out as it
draws it, through the same function sfall's HOOK_TOHIT sits inside, so
gl_combat.ssl hears all eight -- with combat.msg's name for each part -- and
`CombatWatcher.aims` keeps them. They are the numbers on the screen because
they are the same calls.

The mod's own action menu does not come here. Its "attack it" asks for the
body part in its own list and calls the engine's attack directly, because
opening this window from a script would run the engine's modal loop
underneath that script. This window is for the attacks the engine starts
itself: a click with the targeting cursor, and the opening attack of a fight
the menu started, which the engine runs at the start of the player's turn.
"""

from __future__ import annotations

from typing import Optional

from ..input.send import FocusLost, guarded_click, guarded_tap
from . import uiwindow
from ..i18n import tr
from .. import words

WIDTH = 504
HEIGHT = 309
CANCEL = 27

# Button code -> the engine's hit location: the left column's table then the
# right's, read out of the executable.
CODE_TO_LOC = (0, 6, 2, 4, 3, 7, 1, 5)
LOC_TO_CODE = {loc: code for code, loc in enumerate(CODE_TO_LOC)}

# The order the list is read in: head first and down the body, the same order
# the action menu's body-part list uses.
ORDER = (0, 6, 3, 7, 1, 2, 5, 4)

# Only for a part whose chance never arrived, which would mean the hook did not
# fire. The game's own names come with the chances.
def fallback_name(loc: int) -> str:
    return {
        0: tr("calledshot.head", "Head"),
        1: tr("calledshot.left_arm", "Left Arm"),
        2: tr("calledshot.right_arm", "Right Arm"),
        3: tr("calledshot.torso", "Torso"),
        4: tr("calledshot.right_leg", "Right Leg"),
        5: tr("calledshot.left_leg", "Left Leg"),
        6: tr("calledshot.eyes", "Eyes"),
        7: tr("calledshot.groin", "Groin"),
    }[loc]


def window(proc) -> Optional[uiwindow.Window]:
    """The open called-shot window, or None. Asked of the OPEN window list."""
    return uiwindow.live_window_with(proc, WIDTH, HEIGHT, release=CANCEL)


def showing(proc) -> bool:
    return window(proc) is not None


class CalledShot:
    """Steps the eight parts and clicks the one chosen."""

    def __init__(self, proc, hwnd, combat, log_path: Optional[str] = None) -> None:
        self.proc = proc
        self.hwnd = hwnd
        self.combat = combat
        self.log_path = log_path
        self.index = 0

    def reset(self) -> None:
        self.index = 0

    def label(self, i: Optional[int] = None) -> str:
        loc = ORDER[self.index if i is None else i]
        got = self.combat.aims.get(loc) if self.combat is not None else None
        if got is None:
            return fallback_name(loc)
        chance, name = got
        # "Error" is what the game hands back for a number its file does not
        # have -- the answer every part got while the lookup was wrong.
        if not name or name == "Error":
            name = fallback_name(loc)
        return "{}, {}%".format(name[:1].upper() + name[1:], chance)

    def say(self) -> str:
        return "{}, {}.".format(self.label(), words.of(self.index + 1, len(ORDER)))

    def step(self, delta: int) -> str:
        """Clamped, like every list in the mod: this one ends in an attack."""
        self.index = max(0, min(len(ORDER) - 1, self.index + delta))
        return self.say()

    def choose(self) -> bool:
        """Click the button for the part under the list cursor."""
        from .pointer import aim_ui

        win = window(self.proc)
        if win is None or self.hwnd is None:
            return False
        button = win.by_code(LOC_TO_CODE[ORDER[self.index]])
        if button is None:
            return False
        ok, _where, _why = aim_ui(self.proc, self.hwnd, *button.centre(win),
                                  log_path=self.log_path)
        if not ok:
            return False
        try:
            guarded_click(self.hwnd, "left", settle=0.1)
        except (FocusLost, OSError):
            return False
        return True

    def cancel(self) -> bool:
        """Escape: the window's own key, so nothing is aimed at."""
        if self.hwnd is None or not showing(self.proc):
            return False
        try:
            guarded_tap(self.hwnd, "escape", settle=0.2)
        except (FocusLost, OSError):
            return False
        return True
