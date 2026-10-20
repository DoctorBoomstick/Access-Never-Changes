"""The preferences screen: every setting as a list, changed with the arrows.

The game's preferences are knobs and sliders, and the only way to move any of
them is to drag it with the mouse. Nothing on the screen has a key. So the
mod does not drive the controls -- it sets what they set.

**Read out of the engine at 0x00490798.** While the screen is open it works
on a copy of every setting, one global each, and its own Done and Cancel
decide what becomes of them:

    0x00493054   on opening, copies each value aside, for Cancel to restore
    0x00492870   Done: if the changed flag at 0x006639A8 is set, saves the
                 values to fallout2.cfg (0x00492CB0) and applies them
                 (0x004931F8) -- volumes, brightness, text speed, all of it
    Escape       0x00493128, puts the copies back

Done is Enter (or P), Cancel is Escape: both the game's own keys, so the mod
leaves them alone and the screen behaves exactly as it does for anyone. What
the mod adds is the list, and writing the working value -- with the changed
flag, without which Done would quietly save nothing.

**Which global is which** was not guessed. The routine that writes them to
fallout2.cfg (0x00492CB4) pairs each one with its config key by name, and the
screen's own description table at 0x005197F8 -- 76 bytes a setting -- gives
each its labels (options.msg numbers) and range. The three settings kept as
doubles have no pointer in that table; their addresses come from the same
save routine.

The screen's picture is not redrawn when a value is written here: the knobs
stay where they were drawn until something else redraws them. Nothing reads
the picture, and Done saves the values, not the knobs.
"""

from __future__ import annotations

import struct
from typing import List, NamedTuple, Optional, Tuple

from . import uiwindow
from ..i18n import tr
from .. import words

WINDOW_ID = 0x00663904      # the preferences window's GNW id
CHANGED = 0x006639A8        # Done saves only when this is non-zero
MESSAGES = 0x006637E8       # options.msg, while the options code has it loaded

WIDTH = 640
HEIGHT = 480


class Setting(NamedTuple):
    title: int                 # options.msg number of its name
    addr: int
    labels: Tuple[int, ...]    # options.msg numbers of its positions
    lo: float = 0.0
    hi: float = 0.0            # equal to lo for a knob: the labels are the values
    double: bool = False
    # Text delay is stored as a delay and drawn as a speed: the slider's left
    # end says Slow and holds the longest delay.
    inverted: bool = False

    @property
    def slider(self) -> bool:
        return self.hi != self.lo


ON_OFF = (202, 201)
VOLUME = (202, 221, 209, 222)

SETTINGS: List[Setting] = [
    Setting(101, 0x006639BC, (203, 204, 205)),            # game difficulty
    Setting(102, 0x006639B4, (206, 204, 208)),            # combat difficulty
    Setting(103, 0x006639B8, (214, 215, 204, 216)),       # violence level
    Setting(104, 0x006639B0, (202, 201, 213)),            # target highlight
    Setting(105, 0x006639C0, ON_OFF),                     # combat looks
    Setting(106, 0x006639AC, (211, 212)),                 # combat messages
    Setting(107, 0x00663988, ON_OFF),                     # combat taunts
    Setting(108, 0x00663978, ON_OFF),                     # language filter
    Setting(109, 0x00663998, (209, 219)),                 # running
    Setting(110, 0x00663974, ON_OFF),                     # subtitles
    Setting(111, 0x006639A4, ON_OFF),                     # item highlight
    Setting(112, 0x0066399C, (207, 210), 0.0, 50.0),      # combat speed
    Setting(122, 0x00663984, ON_OFF),                     # affect player speed
    Setting(113, 0x006638E0, (217, 209, 218), 1.0, 6.0, double=True,
            inverted=True),                               # text delay
    Setting(114, 0x00663980, VOLUME, 0.0, 32767.0),       # master volume
    Setting(115, 0x00663990, VOLUME, 0.0, 32767.0),       # music
    Setting(116, 0x00663970, VOLUME, 0.0, 32767.0),       # sound effects
    Setting(117, 0x0066397C, VOLUME, 0.0, 32767.0),       # speech
    Setting(118, 0x006638D0, (207, 223), 1.0, 1.17999267578125,
            double=True),                                 # brightness
    Setting(119, 0x006638E8, (207, 218), 1.0, 2.5, double=True),  # mouse
]

# options.msg, as shipped, for when the game does not have it loaded -- the
# preferences screen opened from the main menu, before the options code has
# run. Only the numbers SETTINGS uses.
ENGLISH = {
    101: "GAME DIFFICULTY", 102: "COMBAT DIFFICULTY", 103: "VIOLENCE LEVEL",
    104: "TARGET HIGHLIGHT", 105: "COMBAT LOOKS", 106: "COMBAT MESSAGES",
    107: "COMBAT TAUNTS", 108: "LANGUAGE FILTER", 109: "RUNNING",
    110: "SUBTITLES", 111: "ITEM HIGHLIGHT", 112: "COMBAT SPEED",
    113: "TEXT DELAY", 114: "MASTER AUDIO VOLUME", 115: "MUSIC/MOVIE VOLUME",
    116: "SOUND EFFECTS VOLUME", 117: "SPEECH VOLUME", 118: "BRIGHTNESS LEVEL",
    119: "MOUSE SENSITIVITY", 122: "Affect player speed",
    201: "On", 202: "Off", 203: "Easy", 204: "Normal", 205: "Hard",
    206: "Wimpy", 207: "Normal", 208: "Rough", 209: "Normal", 210: "Fastest",
    211: "Verbose", 212: "Brief", 213: "Targeting Only", 214: "None",
    215: "Minimal", 216: "Maximum Blood", 217: "Slow", 218: "Faster",
    219: "Always", 221: "Quiet", 222: "Loud", 223: "Brighter",
}

# A slider moves a tenth of its length a press.
SLIDER_STEPS = 10


def showing(proc) -> bool:
    """Is the preferences window open? By its id, among the OPEN windows.

    The id alone is not enough -- GNW reuses ids, and this one stays in its
    global after the window closes -- so the window must also be the screen's
    size.
    """
    wid = proc.read_i32(WINDOW_ID)
    if wid is None or wid < 0:
        return False
    try:
        windows = uiwindow.live_windows(proc)
    except Exception:
        return False
    return any(w.id == wid and (w.width, w.height) == (WIDTH, HEIGHT)
               for w in windows)


def _title_case(text: str) -> str:
    """"GAME DIFFICULTY" is shouted by a screen reader letter by letter in
    some voices; "Game difficulty" is a phrase."""
    if text.isupper():
        return text[:1] + text[1:].lower()
    return text


class Prefs:
    """The list, the cursor on it, and reading and writing the values."""

    def __init__(self, proc) -> None:
        self.proc = proc
        self.index = 0
        self._words = None

    def reset(self) -> None:
        self.index = 0
        self._words = None

    # -- words --------------------------------------------------------------

    def word(self, num: int) -> str:
        if self._words is None:
            self._words = {}
            try:
                from ..msg.memlist import read_message_list
                got = read_message_list(self.proc, MESSAGES)
            except Exception:
                got = None
            if got is not None:
                self._words = {e.num: e.text for e in got.entries if e.text}
        return self._words.get(num) or ENGLISH.get(num, "")

    # -- values -------------------------------------------------------------

    def value(self, s: Setting) -> Optional[float]:
        if s.double:
            raw = self.proc.read(s.addr, 8)
            return struct.unpack("<d", raw)[0] if raw and len(raw) == 8 else None
        return self.proc.read_i32(s.addr)

    def position(self, s: Setting) -> Optional[float]:
        """Where the control is, 0.0 at the left to 1.0 at the right."""
        v = self.value(s)
        if v is None:
            return None
        if not s.slider:
            return v / max(1, len(s.labels) - 1)
        p = (v - s.lo) / (s.hi - s.lo)
        p = max(0.0, min(1.0, p))
        return 1.0 - p if s.inverted else p

    def set_position(self, s: Setting, p: float) -> bool:
        p = max(0.0, min(1.0, p))
        if not s.slider:
            n = len(s.labels) - 1
            data = struct.pack("<i", int(round(p * n)))
        else:
            q = 1.0 - p if s.inverted else p
            v = s.lo + q * (s.hi - s.lo)
            data = (struct.pack("<d", v) if s.double
                    else struct.pack("<i", int(round(v))))
        if not self.proc.write(s.addr, data):
            return False
        # Without this, Done closes the screen and saves nothing.
        return self.proc.write(CHANGED, struct.pack("<i", 1))

    # -- what is said -------------------------------------------------------

    def setting_words(self, s: Setting) -> str:
        p = self.position(s)
        if p is None:
            return tr("prefs.unknown", "unknown")
        if not s.slider:
            i = int(round(p * (len(s.labels) - 1)))
            return self.word(s.labels[max(0, min(i, len(s.labels) - 1))])
        # A slider: its percentage, and the label printed at that point on
        # the scale when it is sitting on one -- "Normal" in the middle of the
        # text delay, "Off" at the bottom of a volume.
        pct = int(round(p * 100))
        n = len(s.labels) - 1
        for i, num in enumerate(s.labels):
            if abs(p - i / n) < 0.02:
                return "{}%, {}".format(pct, self.word(num))
        return "{}%".format(pct)

    def say(self, i: Optional[int] = None) -> str:
        i = self.index if i is None else i
        s = SETTINGS[i]
        return "{}: {}. {}.".format(_title_case(self.word(s.title)),
                                   self.setting_words(s),
                                   words.of(i + 1, len(SETTINGS)))

    # -- keys ---------------------------------------------------------------

    def step(self, delta: int) -> str:
        self.index = max(0, min(len(SETTINGS) - 1, self.index + delta))
        return self.say()

    def change(self, delta: int) -> str:
        """Left and Right: one position of a knob, a tenth of a slider."""
        s = SETTINGS[self.index]
        p = self.position(s)
        if p is None:
            return tr("prefs.unreadable", "Cannot read that setting.")
        if s.slider:
            want = p + delta / SLIDER_STEPS
        else:
            want = p + delta / max(1, len(s.labels) - 1)
        if not self.set_position(s, want):
            return tr("prefs.unchanged", "Could not change it.")
        return self.setting_words(s) + "."

    def extreme(self, top: bool) -> str:
        s = SETTINGS[self.index]
        if not self.set_position(s, 1.0 if top else 0.0):
            return tr("prefs.unchanged", "Could not change it.")
        return self.setting_words(s) + "."
