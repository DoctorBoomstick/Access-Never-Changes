"""Read the in-game script's output.

gl_world.ssl runs inside Fallout 2 and writes "WORLD:" lines to debug.log --
hex readouts, game-mode changes, calibration. This tails that file so the
Python side can speak them.

Why a log file rather than shared memory: sfall scripts can write strings with
debug_msg and little else, and the engine's own object names are only reachable
from inside the game. The file is the one channel that carries text out. It is
polled at the same 20Hz as everything else, which is well inside the reaction
time that matters here.

The game truncates debug.log on launch, so a shrinking file means a new session
and all remembered state is dropped.
"""

from __future__ import annotations

import os
import re
from typing import List, NamedTuple, Optional

PREFIX = "WORLD:"
# gl_combat.ssl writes on the same channel. Two scripts, one log file: they are
# kept as separate scripts so a bug in one cannot crash the other, but there is
# only one way for either to get text out of the engine.
COMBAT_PREFIX = "COMBAT:"

# "WORLD:hex 17488 dist 0 : you, Tree|"
# Contents stop at the terminating bar. The engine appends its own debug output
# to our lines without a newline, and without the bar that noise was read as
# part of the object list and spoken aloud.
_HEX_RE = re.compile(r"WORLD:hex\s+(\d+)\s+dist\s+(\d+)\s*:\s*([^|]*)")
_MODE_RE = re.compile(r"WORLD:gamemode\s+(-?\d+)")
# Both forms report the current cursor mode: "cursormode" when it changed,
# "cursorok" when a press found it already correct. Parsing only the first left
# the mode unknown exactly when nothing had changed, which is the common case.
_CURSOR_RE = re.compile(r"WORLD:cursor(?:mode|ok)\s+(-?\d+)")


class HexReading(NamedTuple):
    tile: int
    distance: int
    contents: str

    def announce(self) -> str:
        """What to say when the cursor lands here."""
        what = self.contents.strip() or "empty"
        if self.distance == 0:
            return what
        return "{}, {} hex{}".format(what, self.distance, "" if self.distance == 1 else "es")


class WorldLog:
    def __init__(self, path: str) -> None:
        self.path = path
        self._pos = 0
        self.game_mode: Optional[int] = None
        self.cursor_mode: Optional[int] = None
        self.last_hex: Optional[HexReading] = None
        self.session_live = False

    def reset(self) -> None:
        self._pos = 0
        self.game_mode = None
        self.cursor_mode = None
        self.last_hex = None
        self.session_live = False

    def poll(self) -> List[str]:
        """Return new WORLD: lines, updating cached state."""
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return []

        if size < self._pos:
            # Truncated: the game relaunched.
            self.reset()

        out: List[str] = []
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._pos)
                chunk = fh.read()
                self._pos = fh.tell()
        except OSError:
            return []

        for line in chunk.splitlines():
            if COMBAT_PREFIX in line:
                combat = line[line.index(COMBAT_PREFIX):].strip()
                out.append(combat)
                if combat.startswith("COMBAT:ready"):
                    self.session_live = True
                continue
            if PREFIX not in line:
                continue
            line = line[line.index(PREFIX):].strip()
            out.append(line)

            if line.startswith("WORLD:ready"):
                self.session_live = True
                continue

            m = _MODE_RE.match(line)
            if m:
                self.game_mode = int(m.group(1))
                self.session_live = True
                continue

            m = _CURSOR_RE.match(line)
            if m:
                self.cursor_mode = int(m.group(1))
                self.session_live = True
                continue

            m = _HEX_RE.match(line)
            if m:
                self.last_hex = HexReading(
                    tile=int(m.group(1)),
                    distance=int(m.group(2)),
                    contents=m.group(3).strip(),
                )
        return out
