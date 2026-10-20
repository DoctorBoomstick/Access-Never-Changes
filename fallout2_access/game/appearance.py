"""sfall's hero appearance mod: which race and style, and what they are called.

The Race and Style rows on the character editor are sfall's, not the engine's,
and nothing about them is kept where the engine keeps its text. The mod read
them as two bare words for that reason -- "Race", "Style" -- and Left and Right
changed something nobody could hear.

Which one is chosen
-------------------
sfall keeps the numbers in its own DLL, at addresses that move with every sfall
build. But it ALSO has to make the game draw the hero from the chosen art, and
the way it does that is to push the chosen pack onto the front of the engine's
list of places to look for files -- the same list master.dat and the mods
folder are on. That list is the engine's, at an address the engine owns:

    0x006B24D0   head of the search path list
    node +0x00   char *path         "Appearance\\hmR01S00.dat", or a folder
    node +0x0C   node *next

read out of the engine's own walk of it (0x004DF911), which steps +0x0C and
hands +0x00 to its callback. sfall's key handler (0x11052500 in 4.4.9) reloads
the pack on every Left and Right, so the head of the list IS the choice, sex
letter and all, and survives sfall moving its own variables about.

With a style other than 0, sfall pushes the style's pack in front of the race's
-- hmR00S01 in front of hmR00S00 -- so the first appearance pack found is the
style and carries the race number too.

What it is called
-----------------
Each pack carries its own text\\<language>\\game\\AppRace.msg and AppStyle.msg,
in eleven languages: entry 100 is the title ("Race (Black)") and 101 the
paragraph sfall shows on the card. A style pack has no AppRace.msg of its own;
sfall finds the race pack's behind it on the search list, and so does this.
"""

from __future__ import annotations

import os
import re
import struct
from typing import Dict, NamedTuple, Optional, Tuple

from .floattext import (CODECS, _MSG_ENTRY, _dat_index, _dat_read, _find_ci,
                        _language)

PATHS_HEAD = 0x006B24D0
NODE_PATH = 0x00
NODE_NEXT = 0x0C

# The appearance packs sit at the front, and the list behind them is the game's
# own handful of archives. Anything past this is a loop or garbage.
MAX_NODES = 32

MSG_TITLE = 100
MSG_DESC = 101

_PACK = re.compile(r"(?:^|\\)appearance\\h([mf])r(\d\d)s(\d\d)(?:\.dat)?$", re.I)
# "Race (Black)": the row's own word, and the choice in brackets.
_TITLE = re.compile(r"^\s*(.*?)\s*\((.*)\)\s*$")


class Choice(NamedTuple):
    sex: str      # "m" or "f", as sfall spells the pack
    race: int
    style: int

    def pack(self, style: Optional[int] = None) -> str:
        return "h{}r{:02d}s{:02d}".format(
            self.sex, self.race, self.style if style is None else style)


# sfall's own name for the pack it is loading, and the instruction that loads
# the variable holding the hero's node before the name is printed into it:
#
#     11051115  mov eax, [110E2878]       A1 78 28 0E 11   the hero's node
#     ...
#     11051131  push 110C1254             68 54 12 0C 11   this format string
#     1105113A  call sprintf              into [eax]'s path buffer
#
# (sfall 4.4.9, preferred base.) Found by searching rather than by address, so
# a relocated DLL or a rebuilt sfall still lands on it.
SFALL_FORMAT = b"Appearance\\h%cR%02dS%02d%s\x00"
LOOKBACK = 64


def find_hero_var(proc) -> Optional[int]:
    """Where sfall keeps the pointer to the hero's appearance node, or None.

    **Not on the engine's search list.** sfall 4.4.9 builds its appearance
    folders into a chain of its own and hands that chain only to the lookups
    for the hero's art (0x11051310 picks it or the engine's list per call), so
    walking the engine's list -- this file's first idea -- found nothing and
    every Race and Style row said only its name. The node's path buffer is
    rewritten on every Left and Right, whether or not the pack exists.

    Slow -- it reads the whole DLL -- so the caller keeps the answer.
    """
    directory = getattr(proc, "directory", "")
    mod = proc.module_at("ddraw.dll", directory) if directory else None
    if mod is None or not mod.base or not mod.size:
        return None
    blob = proc.read_chunked(mod.base, mod.size)
    if not blob:
        return None
    at = blob.find(SFALL_FORMAT)
    if at < 0:
        return None
    push = b"\x68" + struct.pack("<I", mod.base + at)
    site = blob.find(push)
    if site < 0:
        return None
    window = blob[max(0, site - LOOKBACK):site]
    i = len(window)
    while True:
        i = window.rfind(b"\xA1", 0, i)
        if i < 0 or i + 5 > len(window):
            return None
        var = struct.unpack_from("<I", window, i + 1)[0]
        if mod.base <= var < mod.base + mod.size and var % 4 == 0:
            return var


def from_sfall(proc, hero_var: int) -> Optional[Choice]:
    node = proc.read_ptr(hero_var)
    buf = proc.read_ptr(node + NODE_PATH) if node else None
    path = proc.read_cstring(buf, 260) if buf else None
    m = _PACK.search(path.replace("/", "\\").strip()) if path else None
    if not m:
        return None
    return Choice(m.group(1).lower(), int(m.group(2)), int(m.group(3)))


def current(proc, hero_var: Optional[int] = None) -> Optional[Choice]:
    """The race and style the hero is drawn with, or None with the mod off."""
    if hero_var:
        got = from_sfall(proc, hero_var)
        if got is not None:
            return got
    # Older sfall builds put the pack on the engine's own list.
    node = proc.read_ptr(PATHS_HEAD)
    seen = set()
    while node and node not in seen and len(seen) < MAX_NODES:
        seen.add(node)
        ptr = proc.read_ptr(node + NODE_PATH)
        path = proc.read_cstring(ptr, 260) if ptr else None
        if path:
            m = _PACK.search(path.replace("/", "\\").strip())
            if m:
                return Choice(m.group(1).lower(), int(m.group(2)),
                              int(m.group(3)))
        node = proc.read_ptr(node + NODE_NEXT)
    return None


def split_title(title: str) -> Tuple[str, Optional[str]]:
    """'Race (Black)' -> ('Race', 'Black'). A title without brackets is all label."""
    m = _TITLE.match(title)
    if m and m.group(1) and m.group(2):
        return m.group(1), m.group(2)
    return title.strip(), None


class Texts:
    """The packs' own titles and descriptions, in the game's language."""

    def __init__(self, game_dir: str) -> None:
        self.game_dir = game_dir
        self.language = _language(game_dir)
        self.codec = CODECS.get(self.language, "cp1252")
        self._cache: Dict[Tuple[str, str], Dict[int, str]] = {}

    def entry(self, choice: Choice, which: str) -> Tuple[Optional[str], Optional[str]]:
        """(title, description) for "race" or "style"."""
        msg = self._find(choice, which)
        return msg.get(MSG_TITLE), msg.get(MSG_DESC)

    def _find(self, choice: Choice, which: str) -> Dict[int, str]:
        # Searched the way the game's list has them: the style's pack first,
        # then the race's. The race title only ever lives in the second.
        packs = [choice.pack()]
        if choice.style != 0:
            packs.append(choice.pack(0))
        for pack in packs:
            msg = self._msg(pack, "app{}.msg".format(which))
            if msg:
                return msg
        return {}

    def _msg(self, pack: str, name: str) -> Dict[int, str]:
        key = (pack, name)
        if key not in self._cache:
            self._cache[key] = self._load(pack, name)
        return self._cache[key]

    def _load(self, pack: str, name: str) -> Dict[int, str]:
        for language in dict.fromkeys((self.language, "english")):
            rel = "text\\{}\\game\\{}".format(language, name)
            data = self._read(pack, rel)
            if data:
                codec = CODECS.get(language, "cp1252")
                return {int(m.group(1)): m.group(2).decode(codec, "replace").strip()
                        for m in _MSG_ENTRY.finditer(data)}
        return {}

    def _read(self, pack: str, rel: str) -> Optional[bytes]:
        # A pack is a folder or an archive; sfall takes either.
        folder = _find_ci(self.game_dir, "appearance\\" + pack)
        if folder and os.path.isdir(folder):
            path = _find_ci(folder, rel)
            if path:
                try:
                    with open(path, "rb") as f:
                        return f.read()
                except OSError:
                    return None
        dat = _find_ci(self.game_dir, "appearance\\{}.dat".format(pack))
        if dat and os.path.isfile(dat):
            try:
                hit = _dat_index(dat).get(rel.lower())
            except (OSError, struct.error, UnicodeDecodeError):
                return None
            return _dat_read(dat, hit) if hit else None
        return None
