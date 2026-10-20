"""The message log: everything the game said, kept so it can be read again.

Two things in Fallout are said once and gone. The strip along the bottom of the
screen scrolls ("You see: a locker", who hit whom, what a skill did), and the
lines over characters' heads fade after a few seconds. A sighted player glances
back at either. A blind player hears each once, often over the top of
something else -- a click, a step, a key pressed a moment too soon -- and had
no way back to it.

Both are already read as they arrive (displaywin.py, floattext.py). This only
keeps them: newest last, browsed with Shift and comma for older and Shift and
period for newer, on every screen.

**Where you are stays put when something new arrives.** Reading back through a
fight while it goes on should not be yanked to the bottom by every blow; the
next press from where you are still means the next line from there. Stepping
past the newest says so, and the first press after that starts again from the
newest -- which is the line you were most likely reaching for.
"""

from __future__ import annotations

from typing import List, Optional
from ..i18n import tr

# A long fight is about this many lines. The game's own strip keeps 100.
CAPACITY = 300

# Said when there is nothing older or newer. The line is said again after it,
# so the press is never silent and never ambiguous.
def empty() -> str:
    return tr("history.empty", "Nothing has been said yet.")


class History:
    def __init__(self, capacity: int = CAPACITY) -> None:
        self.capacity = capacity
        self.lines: List[str] = []
        # Index of the line last read out, or None for "at the live end": the
        # next older press reads the newest line.
        self.pos: Optional[int] = None

    def add(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.lines.append(text)
        over = len(self.lines) - self.capacity
        if over > 0:
            del self.lines[:over]
            if self.pos is not None:
                # The line being read may itself have gone; keep to the oldest.
                self.pos = max(0, self.pos - over)

    def clear(self) -> None:
        self.lines = []
        self.pos = None

    def older(self) -> str:
        if not self.lines:
            return empty()
        if self.pos is None:
            self.pos = len(self.lines) - 1
            return self.lines[self.pos]
        if self.pos == 0:
            return tr("history.oldest", "Oldest. {line}", line=self.lines[0])
        self.pos -= 1
        return self.lines[self.pos]

    def newer(self) -> str:
        if not self.lines:
            return empty()
        if self.pos is None or self.pos >= len(self.lines) - 1:
            # Off the live end. The next older press starts from the newest.
            self.pos = None
            return tr("history.newest", "Newest. {line}", line=self.lines[-1])
        self.pos += 1
        return self.lines[self.pos]
