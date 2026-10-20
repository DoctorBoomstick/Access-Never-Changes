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

**The header is read, now that there were real saves to read it from.** SAVE.DAT
opens with the signature "FALLOUT SAVE FILE", then the character name at offset
29 and the save's own description at offset 61, both NUL-terminated. Confirmed
identical across five separate saves rather than inferred from one.

That matters more here than anywhere else in this project. A save slot is the
one thing a player can destroy by acting on a wrong description, so the rule is
strict: a header that does not start with the signature is not described at all,
and a slot whose text cannot be read falls back to its number and its time,
which are certain because they come from the filesystem rather than from parsing
anything.
"""

from __future__ import annotations

import os
import re
import time
from typing import Dict, List, NamedTuple, Optional
from ..i18n import tr

# Where the engine keeps them, relative to the game folder. Slots are 1-indexed
# on disk and in the interface, which is worth stating because sfall's own slot
# functions are 0-indexed and mixing the two silently targets the wrong game.
SAVE_DIR = os.path.join("data", "SAVEGAME")
SLOT_RE = re.compile(r"^SLOT(\d+)$", re.IGNORECASE)
SAVE_FILE = "SAVE.DAT"

# The header, confirmed identical across five real saves. Anything that does not
# open with the signature is not a save file we understand, and is described by
# its number and time alone rather than by bytes we guessed the meaning of.
SIGNATURE = b"FALLOUT SAVE FILE"
OFF_CHARACTER = 29      # the character's name, NUL terminated
OFF_DESCRIPTION = 61    # what the save calls itself, NUL terminated
HEADER = 256

# Slots are polled rather than watched with a filesystem notification: this runs
# beside a 20Hz loop that must never block, and ten stat calls twice a second is
# far cheaper than the machinery for the alternative.
POLL_SECONDS = 0.5


def _text_at(header: bytes, offset: int, limit: int = 32) -> str:
    """A NUL-terminated string out of the header, or "" if it is not there."""
    if len(header) < offset + 1:
        return ""
    raw = header[offset:offset + limit]
    end = raw.find(b"\x00")
    if end >= 0:
        raw = raw[:end]
    try:
        text = raw.decode("cp1252")
    except Exception:
        return ""
    # Anything unprintable means the offset is wrong for this build, and a
    # mangled description on a save slot is worse than no description at all.
    if any(ord(c) < 32 for c in text):
        return ""
    return text.strip()


class Slot(NamedTuple):
    number: int
    written: float      # mtime, seconds since the epoch
    size: int
    character: str = ""
    description: str = ""

    def when(self) -> str:
        """A time a person can act on, not a timestamp."""
        return time.strftime("%H:%M", time.localtime(self.written))

    def announce(self) -> str:
        """What the slot is, leading with whatever the save calls itself.

        The description is the game's own text -- what was typed when saving, or
        what quick save wrote -- so it is preferred over anything assembled
        here. The time is kept as well, because two saves can carry the same
        description and the clock is what tells them apart.
        """
        if self.description:
            return tr("slots.named", "Slot {slot}, {name}.", slot=self.number,
                      name=self.description)
        return tr("saves.saved_at", "Slot {slot}, saved {time}.",
                  slot=self.number, time=self.when())


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
            character, description = self._header(path)
            out.append(Slot(number=int(m.group(1)), written=st.st_mtime,
                            size=st.st_size, character=character,
                            description=description))
        out.sort(key=lambda s: s.number)
        return out

    def _header(self, path: str):
        """(character, description) from a save's header, or ("", "")."""
        try:
            with open(path, "rb") as fh:
                head = fh.read(HEADER)
        except OSError:
            return "", ""
        if not head.startswith(SIGNATURE):
            return "", ""
        return (_text_at(head, OFF_CHARACTER),
                _text_at(head, OFF_DESCRIPTION))

    def slot(self, number: int):
        """One slot by number, or None if nothing is saved there."""
        for s in self.scan():
            if s.number == number:
                return s
        return None

    def summary(self) -> str:
        """What is saved, for reading out on the save or load screen."""
        slots = self.scan()
        if not slots:
            return tr("saves.none", "No saved games.")
        if len(slots) == 1:
            head = tr("saves.one", "1 saved game.")
        else:
            head = tr("saves.many", "{count} saved games.", count=len(slots))
        return "{} {}".format(head, " ".join(s.announce() for s in slots))

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
                said.append(tr("saves.saved", "Saved to slot {slot}.", slot=number))
            elif slot.written > before:
                said.append(tr("saves.overwritten", "Slot {slot} saved over.",
                               slot=number))
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
