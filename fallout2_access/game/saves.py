"""Watch the savegame folder, so a save is something you hear.

Fallout 2 already has quick save and quick load on F6 and F7. They need no
pointer, no list and no screen, and nothing in `ddraw.ini` rebinds them -- so
the one thing standing between a blind player and a working test loop is that
pressing F6 produces no sound whatsoever. You cannot tell a save that worked
from a key that did not arrive, which is the same failure that has bitten this
project everywhere else.

**Watched on disk rather than asked of the engine.** There is no sfall hook for
saving, and the engine prints nothing we can rely on. What a save definitely
does is write a file. Watching for that is engine-independent, works for the
quick keys and the save screen alike, and reports a save that *happened* rather
than a key that was *sent* -- which is the distinction this mod keeps insisting
on everywhere else.

Slot descriptions are deliberately not parsed yet. They live inside SAVE.DAT in
a layout nobody here has confirmed against a real file, and a confidently wrong
save description is exactly the kind of statement that gets someone to overwrite
the wrong game. Until it is checked, a slot is named by its number and its time,
both of which are certain. `sample()` dumps the header of a real save so the
format can be settled from data.
"""

from __future__ import annotations

import os
import re
import time
from typing import Dict, List, NamedTuple, Optional

# Where the engine keeps them, relative to the game folder. Slots are 1-indexed
# on disk and in the interface, which is worth stating because sfall's own slot
# functions are 0-indexed and mixing the two silently targets the wrong game.
SAVE_DIR = os.path.join("data", "SAVEGAME")
SLOT_RE = re.compile(r"^SLOT(\d+)$", re.IGNORECASE)
SAVE_FILE = "SAVE.DAT"

# Slots are polled rather than watched with a filesystem notification: this runs
# beside a 20Hz loop that must never block, and ten stat calls twice a second is
# far cheaper than the machinery for the alternative.
POLL_SECONDS = 0.5


class Slot(NamedTuple):
    number: int
    written: float      # mtime, seconds since the epoch
    size: int

    def when(self) -> str:
        """A time a person can act on, not a timestamp."""
        return time.strftime("%H:%M", time.localtime(self.written))

    def announce(self) -> str:
        return "Slot {}, saved {}.".format(self.number, self.when())


class SaveWatcher:
    """Notices saves appearing, and can list what is on disk."""

    def __init__(self, game_dir: str) -> None:
        self.root = os.path.join(game_dir, SAVE_DIR)
        self._known: Dict[int, float] = {}
        self._next_poll = 0.0
        self._primed = False

    # -- reading ---------------------------------------------------------

    def scan(self) -> List[Slot]:
        """Every slot that holds a game, lowest number first."""
        out: List[Slot] = []
        try:
            names = os.listdir(self.root)
        except OSError:
            return out
        for name in names:
            m = SLOT_RE.match(name)
            if not m:
                continue
            path = os.path.join(self.root, name, SAVE_FILE)
            try:
                st = os.stat(path)
            except OSError:
                continue      # an empty slot folder is not a saved game
            out.append(Slot(number=int(m.group(1)), written=st.st_mtime,
                            size=st.st_size))
        out.sort(key=lambda s: s.number)
        return out

    def summary(self) -> str:
        """What is saved, for reading out on the save or load screen."""
        slots = self.scan()
        if not slots:
            return "No saved games."
        return "{} saved {}. {}".format(
            len(slots),
            "game" if len(slots) == 1 else "games",
            " ".join(s.announce() for s in slots),
        )

    # -- watching --------------------------------------------------------

    def poll(self, now: Optional[float] = None) -> List[str]:
        """Anything saved since the last call.

        The first call only takes stock. Saves that were already on disk when
        the mod started are not news, and announcing them would be the same
        mistake as narrating the message buffer's backlog on attach.
        """
        now = time.time() if now is None else now
        if now < self._next_poll:
            return []
        self._next_poll = now + POLL_SECONDS

        current = {s.number: s for s in self.scan()}
        if not self._primed:
            self._primed = True
            self._known = {n: s.written for n, s in current.items()}
            return []

        said: List[str] = []
        for number in sorted(current):
            slot = current[number]
            before = self._known.get(number)
            if before is None:
                said.append("Saved to slot {}.".format(number))
            elif slot.written > before:
                said.append("Slot {} saved over.".format(number))
        self._known = {n: s.written for n, s in current.items()}
        return said

    def reset(self) -> None:
        self._known = {}
        self._primed = False
        self._next_poll = 0.0

    # -- groundwork ------------------------------------------------------

    def sample(self, number: int, length: int = 256) -> bytes:
        """The head of one save file, for working out where the description is.

        Not used in play. This exists so the layout can be derived from a real
        save rather than guessed at, the same way the message ring and the
        invisible-furniture filter were.
        """
        path = os.path.join(self.root, "SLOT{:02d}".format(number), SAVE_FILE)
        try:
            with open(path, "rb") as fh:
                return fh.read(length)
        except OSError:
            return b""
