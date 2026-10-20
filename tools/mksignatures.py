#!/usr/bin/env python3
"""Derive AoB signatures for every address the mod hardcodes.

An address is a fact about one build. The Restoration Project Unofficial proved
that the cheap way: it rewrote fallout2.exe in place -- same 1,189,888 bytes, a
different SHA256 -- the character editor's window handle moved eight bytes, and
the mod went quiet on that screen. **Not one read failed.** Every read succeeded
and returned -1, which legitimately means "no editor open", so nothing anywhere
could tell a moved variable from a closed window.

A signature is a fact about the CODE, which is far more stable. Instead of
recording "EDITOR_WINDOW is at 0x006ADDA8", record the bytes of an instruction
that references it -- `mov eax, [0x006ADDA8]` is `A1 A8 DD 6A 00` -- wildcard
the four operand bytes, and find it again at startup. The variable may then move
wherever the next patch puts it.

**Nothing here is hand-written.** The addresses in REGISTRY are known-good on the
build this is run against, so the tool searches the code for each one, takes the
bytes around it, and widens the window until exactly one match remains. Then it
verifies by pulling the operand back OUT of the match and checking it against
the address it started from: a pattern that is unique but points elsewhere is
worse than none.

**Some addresses no instruction names.** They are entries inside arrays, reached
by index, so no `mov` ever spells them out. Measured: EDITOR_WINDOW and the stat
table both come back with zero references. Those fall back to an anchor -- a
signatured neighbour a fixed distance away -- because the distance is a fact
about the engine's layout while the base is a fact about the build.

Screen state does not matter. All of .text is mapped whatever is on screen, and
slot-screen and dialogue addresses have references while sitting in the
character editor. Run this wherever you like.

    python tools/mksignatures.py                    report against the live game
    python tools/mksignatures.py --write            and save the result
    python tools/mksignatures.py --exe PATH         read an executable instead

`--exe` is how a second build gets checked without installing it: point it at
another fallout2.exe and see whether the patterns still resolve, and to what.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fallout2_access.memory import scan                       # noqa: E402
from fallout2_access.memory.process import (                  # noqa: E402
    FALLOUT_EXE_NAMES, Process, ProcessNotFound, Region,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "fallout2_access", "offsets", "signatures.json")

# name -> (address, [(module, attribute), ...])
#
# Module paths are relative to fallout2_access.memory, which is where the
# resolver imports them from. An attribute written as NAME[0] is an entry in a
# tuple rather than a bare int; the resolver rebuilds the tuple.
#
# Names are canonical, not per-module: seven of these are one address read by
# both the editor and the premade screen, and one signature serves both.
REGISTRY = {
    # -- which screen is up (pre-game; in a session the script answers) -------
    "EDITOR_WINDOW":     (0x006ADDA8, [("..game.screens", "EDITOR_WINDOW")]),
    "MENU_FLAG":         (0x00519504, [("..game.screens", "MENU_FLAG")]),
    "EDITOR_FLAG":       (0x00518490, [("..game.screens", "EDITOR_FLAG")]),
    # -- the GNW window list, which is how any panel is found to click in ----
    "WINDOW_LIST":       (0x006ADE58, [("..game.uiwindow", "WINDOW_LIST")]),
    "WINDOW_COUNT":      (0x006ADF24, [("..game.uiwindow", "WINDOW_COUNT")]),
    # -- character creation, and the premade screen that shares its tables ---
    # The row the keys are on, the folder the box shows, and the info card --
    # three different things, and the card was read as the row for a long time.
    "CHARGEN_SELECTED":  (0x005707D0, [("..game.chargen", "SEL_ADDR")]),
    "CHARGEN_FOLDER":    (0x005707D4, [("..game.chargen", "FOLDER_ADDR")]),
    "CHARGEN_CARD":      (0x005709EC, [("..game.chargen", "CARD_ADDR")]),
    # The Pick a Perk window: its options, scroll and lit line, and perk.msg.
    "PERK_OPTIONS":      (0x0056FCB0, [("..game.perkpick", "OPTIONS")]),
    "PERK_TOP":          (0x005707A8, [("..game.perkpick", "TOP_ADDR")]),
    "PERK_LINE":         (0x005707DC, [("..game.perkpick", "LINE_ADDR")]),
    "MSG_PERK":          (0x006642D4, [("..game.perkpick", "MSG_PERK")]),
    "STAT_TABLE":        (0x0051C394, [("..game.chargen", "SPECIAL_ADDR"),
                                       ("..game.premade", "SPECIAL_ADDR")]),
    "CHAR_POINTS":       (0x00518538, [("..game.chargen", "CHAR_POINTS_ADDR")]),
    "CHAR_NAME":         (0x0056D75C, [("..game.chargen", "NAME_ADDR"),
                                       ("..game.premade", "NAME_ADDR")]),
    "TAG_SKILLS":        (0x00668070, [("..game.chargen", "TAGS_ADDR"),
                                       ("..game.premade", "TAGS_ADDR")]),
    "TRAITS":            (0x0066BE40, [("..game.chargen", "TRAITS_ADDR"),
                                       ("..game.premade", "TRAITS_ADDR")]),
    "COND_NAME_PTR":     (0x005700F4, [("..game.chargen", "COND_NAME_PTR")]),
    "TRAIT_NAME_PTR":    (0x005705B8, [("..game.chargen", "TRAIT_NAME_PTR")]),
    "TRAIT_DESC_PTR":    (0x005705CC, [("..game.chargen", "TRAIT_DESC_PTR")]),
    "MSG_EDITOR":        (0x0056FCA8, [("..game.chargen", "MSG_EDITOR")]),
    "MSG_STAT":          (0x0066817C, [("..game.chargen", "MSG_STAT"),
                                       ("..game.premade", "MSG_STAT")]),
    "MSG_SKILL":         (0x00668080, [("..game.chargen", "MSG_SKILL"),
                                       ("..game.premade", "MSG_SKILL")]),
    "MSG_TRAIT":         (0x0066BE38, [("..game.chargen", "MSG_TRAIT"),
                                       ("..game.premade", "MSG_TRAIT")]),
    "PREMADE_COUNTER":   (0x0051E2E0, [("..game.premade", "COUNTER_ADDR")]),
    # -- the dialogue screen, read straight out of static memory -------------
    "DLG_REPLY_TEXT":    (0x0058F4E4, [("..game.dialogue", "REPLY_TEXT")]),
    "DLG_REPLY_MSGLIST": (0x0058F4D8, [("..game.dialogue", "REPLY_MSGLIST")]),
    "DLG_REPLY_MSGID":   (0x0058F4DC, [("..game.dialogue", "REPLY_MSGID")]),
    "DLG_OPTIONS":       (0x0058FF70, [("..game.dialogue", "OPTIONS")]),
    "DLG_OPTION_COUNT":  (0x005186D8, [("..game.dialogue", "OPTION_COUNT")]),
    "DLG_WINDOW":        (0x00518744, [("..game.dialogue", "WINDOW")]),
    # -- the save and load slot list -----------------------------------------
    "MSG_LSGAME":        (0x00613D28, [("..game.slotscreen", "MSG_LSGAME")]),
    "SLOT_SELECTION":    (0x005193B8, [("..game.slotscreen", "SELECTION")]),
    "SLOT_OCCUPIED":     (0x00614280, [("..game.slotscreen", "OCCUPIED")]),
    "SLOT_HEADERS":      (0x00613D30, [("..game.slotscreen", "SLOT_HEADERS")]),
    # -- the Pip-Boy ---------------------------------------------------------
    #
    # Two, and only two: everything else about that panel is read off GNW's own
    # button list, which is found through WINDOW_LIST above. GAME_TIME is the
    # one this most needs to survive a patch -- resting until morning is a
    # decision made on the clock, and a clock that reads out of the wrong place
    # would be confidently wrong rather than missing.
    "MSG_PIPBOY":        (0x00664348, [("..game.pipboy", "MSG_PIPBOY")]),
    "GAME_TIME":         (0x0051C720, [("..game.pipboy", "GAME_TIME")]),
    # -- and what its pages are lists of -------------------------------------
    #
    # The tables the engine parses out of quests.txt and holodisk.txt, the
    # global variables they are gated on, and the counters the engine keeps of
    # what it drew. Everything the Status and Archives pages say comes through
    # these, so a build that moved one of them would take the quest list with
    # it -- which is exactly the failure signatures exist to turn from silence
    # into a spoken complaint.
    "MSG_QUESTS":        (0x00664410, [("..game.pipboy", "MSG_QUESTS")]),
    # map.msg is shared: the Pip-Boy names quest locations out of it and the
    # world map names areas and entrances out of it. Found independently by
    # both, which is a cross-check worth having on the one list two screens
    # depend on.
    "MSG_MAP":           (0x00631D48, [("..game.pipboy", "MSG_MAP"),
                                       ("..game.worldmap", "MSG_MAP")]),
    "QUEST_TABLE":       (0x0051C128, [("..game.pipboy", "QUEST_TABLE")]),
    "QUEST_COUNT":       (0x0051C12C, [("..game.pipboy", "QUEST_COUNT")]),
    "HOLODISK_TABLE":    (0x0051C130, [("..game.pipboy", "HOLODISK_TABLE")]),
    "HOLODISK_COUNT":    (0x0051C134, [("..game.pipboy", "HOLODISK_COUNT")]),
    "REST_OPTION_COUNT": (0x0051C138, [("..game.pipboy", "REST_OPTION_COUNT")]),
    "GAME_GLOBALS":      (0x005186C0, [("..game.pipboy", "GAME_GLOBALS")]),
    "MOVIES_SEEN":       (0x00596C78, [("..game.pipboy", "MOVIES_SEEN")]),
    "LINES_QUEST_LOCATIONS": (0x00664418,
                              [("..game.pipboy", "LINES_QUEST_LOCATIONS")]),
    "LINES_STATUS_HOLODISKS": (0x0066444C,
                               [("..game.pipboy", "LINES_STATUS_HOLODISKS")]),
    "LINES_ARCHIVES":    (0x00664520, [("..game.pipboy", "LINES_ARCHIVES")]),
    "LINES_AUTOMAPS":    (0x0066450C, [("..game.pipboy", "LINES_AUTOMAPS")]),
    # -- the engine's own action menu ----------------------------------------
    "ACTION_LIST":       (0x00596C3C, [("..game.actions", "ACTION_LIST")]),
    "ACTION_MENU_COUNT": (0x00518D14, [("..game.actions", "MENU_COUNT")]),
    "ACTION_MENU_INDEX": (0x00518D1C, [("..game.actions", "MENU_INDEX")]),
    # -- the world map -------------------------------------------------------
    #
    # Two clusters, and the split is the engine's own. 0x00672Exx is the world
    # map's live state -- where the player is, where they are going, whether
    # they are moving -- and 0x0051DDxx is what was parsed out of city.txt and
    # worldmap.txt when the game loaded. sfall reads the first pair itself, for
    # its worldmap_xpos and worldmap_ypos metarules, which is how they were
    # found: its ddraw.dll names the address where the engine only indexes it.
    "WM_WORLD_X":        (0x00672E0C, [("..game.worldmap", "WORLD_X")]),
    "WM_WORLD_Y":        (0x00672E10, [("..game.worldmap", "WORLD_Y")]),
    "WM_DEST_X":         (0x00672E5C, [("..game.worldmap", "DEST_X")]),
    "WM_DEST_Y":         (0x00672E60, [("..game.worldmap", "DEST_Y")]),
    "WM_CURRENT_AREA":   (0x00672E08, [("..game.worldmap", "CURRENT_AREA")]),
    "WM_TRAVELLING":     (0x00672E1C, [("..game.worldmap", "TRAVELLING")]),
    "WM_SCROLL_X":       (0x0051DE2C, [("..game.worldmap", "SCROLL_X")]),
    "WM_SCROLL_Y":       (0x0051DE30, [("..game.worldmap", "SCROLL_Y")]),
    "WM_TILE_LIST":      (0x0051DDEC, [("..game.worldmap", "TILE_LIST")]),
    "WM_TILE_COUNT":     (0x0051DDF0, [("..game.worldmap", "TILE_COUNT")]),
    "WM_TILES_ACROSS":   (0x0051DDF4, [("..game.worldmap", "TILES_ACROSS")]),
    "WM_AREA_LIST":      (0x0051DDF8, [("..game.worldmap", "AREA_LIST")]),
    "WM_AREA_COUNT":     (0x0051DDFC, [("..game.worldmap", "AREA_COUNT")]),
    "WM_TOWN_ROWS":      (0x0051DE94, [("..game.worldmap", "TOWN_ROWS")]),
    "WM_TOWN_ROW_COUNT": (0x0051DE98, [("..game.worldmap", "TOWN_ROW_COUNT")]),
    "WM_TOWN_SCROLL":    (0x00672F10, [("..game.worldmap", "TOWN_SCROLL")]),
    "MSG_WORLDMAP":      (0x00672FB0, [("..game.worldmap", "MSG_WORLDMAP")]),
    "WM_ENCOUNTER_ODDS": (0x00672FB8, [("..game.worldmap", "ENCOUNTER_CHANCE")]),
    # -- where the pointer really is -----------------------------------------
    "MOUSE_X":           (0x006AC750, [("..game.pointer", "MOUSE_X")]),
    "MENU_MOUSE_X":      (0x006AC794, [("..game.pointer", "MENU_MOUSE_X")]),
    "MENU_MOUSE_Y":      (0x006AC79C, [("..game.pointer", "MENU_MOUSE_Y")]),
    "MOUSE_MIRROR":      (0x006ABD74, [("..game.pointer", "MOUSE_MIRRORS[0]")]),
}

# Addresses that must NEVER be signatured on their own, however many references
# they have, because they are computed from another one and have to keep step
# with it. chargen.py builds these at import time as SPECIAL_ADDR + 4 * index;
# signaturing them separately would let the pair disagree on a build where the
# table moved, and disagreeing is worse than either answer alone.
FORCED_ANCHOR = {
    "STAT_AGE": ("STAT_TABLE", 4 * 33, [("..game.chargen", "AGE_ADDR")]),
    "STAT_SEX": ("STAT_TABLE", 4 * 34, [("..game.chargen", "SEX_ADDR")]),
}

# Context to try around the operand, smallest first. Small patterns match too
# much; large ones are likelier to span something a patch touched. The first
# width that is unique wins, so no signature is more specific than it must be.
WIDTHS = [(4, 4), (6, 6), (8, 8), (10, 10), (14, 14), (20, 20)]

# How far to look for an anchor when nothing references the address itself.
ANCHOR_RANGE = 0x40


class FileImage:
    """An executable on disk, read as if it were mapped.

    Enough of Process's shape for scan.py: read(), read_chunked(), and the
    executable sections at their virtual addresses. This is what lets a second
    build be checked without installing it -- the patterns are about code, and
    the code is in the file.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.exe_path = path
        with open(path, "rb") as fh:
            self._data = fh.read()
        self._sections: List[Tuple[int, int, int, bool]] = []
        self._parse()

    def _parse(self) -> None:
        d = self._data
        if d[:2] != b"MZ":
            raise ValueError("not a PE file: {}".format(self.path))
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        if d[pe:pe + 4] != b"PE\0\0":
            raise ValueError("not a PE file: {}".format(self.path))
        n_sections = struct.unpack_from("<H", d, pe + 6)[0]
        opt_size = struct.unpack_from("<H", d, pe + 20)[0]
        self.base = struct.unpack_from("<I", d, pe + 24 + 28)[0]
        table = pe + 24 + opt_size
        for i in range(n_sections):
            off = table + i * 40
            vsize, va, rawsize, rawoff = struct.unpack_from("<IIII", d, off + 8)
            flags = struct.unpack_from("<I", d, off + 36)[0]
            executable = bool(flags & 0x20000000)  # IMAGE_SCN_MEM_EXECUTE
            size = min(vsize or rawsize, rawsize)
            self._sections.append((self.base + va, size, rawoff, executable))

    def code_regions(self) -> List[Region]:
        return [Region(va, size, 0x20)
                for va, size, _off, x in self._sections if x and size]

    def read(self, addr: int, size: int) -> Optional[bytes]:
        for va, vsize, rawoff, _x in self._sections:
            if va <= addr and addr + size <= va + vsize:
                start = rawoff + (addr - va)
                return self._data[start:start + size]
        return None

    def read_chunked(self, addr: int, size: int, chunk: int = 0) -> bytes:
        return self.read(addr, size) or b""


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def as_pattern(blob: bytes, operand_at: int) -> str:
    parts = []
    for i, b in enumerate(blob):
        parts.append("??" if operand_at <= i < operand_at + 4
                     else "{:02X}".format(b))
    return " ".join(parts)


def sites_for(addr: int, blobs) -> List[int]:
    """Every place in the code where this address appears as a dword."""
    needle = struct.pack("<I", addr)
    out: List[int] = []
    for base, data in blobs:
        start = 0
        while True:
            i = data.find(needle, start)
            if i < 0:
                break
            out.append(base + i)
            start = i + 1
    return out


def signature_for(image, addr: int, regions, blobs) -> Optional[dict]:
    """A unique pattern around some instruction that references `addr`."""
    for site in sites_for(addr, blobs):
        for before, after in WIDTHS:
            blob = image.read(site - before, before + 4 + after)
            if not blob or len(blob) != before + 4 + after:
                continue
            pattern = as_pattern(blob, before)
            hits = scan.find_pattern_all(image, pattern, regions, limit=2)
            if len(hits) != 1:
                continue
            got = image.read(hits[0] + before, 4)
            if not got or struct.unpack("<I", got)[0] != addr:
                continue
            return {"pattern": pattern, "operand_offset": before}
    return None


def anchor_for(image, addr: int, regions, blobs):
    """A signatured neighbour, and the distance from it back to `addr`.

    Nearest first: a close neighbour is likelier to be in the same block, and
    the block is what moves together.
    """
    for step in range(4, ANCHOR_RANGE + 4, 4):
        for delta in (-step, step):
            near = addr + delta
            sig = signature_for(image, near, regions, blobs)
            if sig:
                return near, -delta, sig
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="write offsets/signatures.json")
    ap.add_argument("--exe", default="",
                    help="scan this executable instead of the running game")
    args = ap.parse_args()

    if args.exe:
        image = FileImage(args.exe)
        regions = image.code_regions()
        exe_path = args.exe
        print("reading {}".format(exe_path))
    else:
        try:
            image = Process.attach(FALLOUT_EXE_NAMES)
        except (ProcessNotFound, OSError):
            print("Fallout 2 is not running. Start it, or pass --exe PATH.")
            return 1
        regions = scan.code_regions(image)
        exe_path = image.exe_path
        print("attached to pid {}".format(image.pid))
        print("exe {}".format(exe_path))

    digest = sha256_file(exe_path)
    print("sha256 {}".format(digest))
    total = sum(r.size for r in regions)
    print("scanning {:,} bytes of code in {} region(s)\n".format(
        total, len(regions)))

    blobs = [(r.base, image.read_chunked(r.base, r.size)) for r in regions]

    signatures: Dict[str, dict] = {}
    derived: Dict[str, dict] = {}
    unresolved: List[str] = []
    anchored: List[str] = []

    for name in sorted(REGISTRY):
        addr, owners = REGISTRY[name]
        sig = signature_for(image, addr, regions, blobs)
        if sig:
            sig["address"] = addr
            sig["owners"] = [list(o) for o in owners]
            signatures[name] = sig
            print("  {:18} 0x{:08X}  signatured".format(name, addr))
            continue
        found = anchor_for(image, addr, regions, blobs)
        if not found:
            unresolved.append(name)
            print("  {:18} 0x{:08X}  NO SIGNATURE AND NO ANCHOR".format(
                name, addr))
            continue
        anchor_addr, delta, anchor_sig = found
        anchor_name = "{}_ANCHOR".format(name)
        anchor_sig["address"] = anchor_addr
        anchor_sig["owners"] = []
        signatures[anchor_name] = anchor_sig
        derived[name] = {"anchor": anchor_name, "delta": delta,
                         "address": anchor_addr + delta,
                         "owners": [list(o) for o in owners]}
        anchored.append(name)
        print("  {:18} 0x{:08X}  via {} {:+#x}".format(
            name, addr, anchor_name, delta))

    for name in sorted(FORCED_ANCHOR):
        anchor_name, delta, owners = FORCED_ANCHOR[name]
        source = signatures.get(anchor_name) or derived.get(anchor_name)
        if source is None:
            unresolved.append(name)
            print("  {:18} anchor {} unavailable".format(name, anchor_name))
            continue
        derived[name] = {"anchor": anchor_name, "delta": delta,
                         "address": source["address"] + delta,
                         "owners": [list(o) for o in owners]}
        print("  {:18} 0x{:08X}  = {} {:+#x} (forced)".format(
            name, source["address"] + delta, anchor_name, delta))

    print("\n{} signatured, {} derived, {} unresolved".format(
        len(signatures), len(derived), len(unresolved)))
    if anchored:
        print("needed an anchor: {}".format(", ".join(anchored)))
    if unresolved:
        print("UNRESOLVED: {}".format(", ".join(unresolved)))

    if not args.write:
        print("(report only -- pass --write to save)")
        return 0
    if unresolved:
        print("refusing to write with unresolved names")
        return 2

    doc = {
        "_comment": (
            "Generated by tools/mksignatures.py against the executable named "
            "below. Each address is what its pattern resolved to ON THAT BUILD "
            "and is kept only so the resolver can skip scanning when the hash "
            "matches. On any other build the address is meaningless and the "
            "pattern is the answer."
        ),
        "exe_sha256": digest,
        "signatures": signatures,
        "derived": derived,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote {}".format(OUT))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
