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
    "CHARGEN_SELECTED":  (0x005709EC, [("..game.chargen", "SEL_ADDR")]),
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
    # -- the engine's own action menu ----------------------------------------
    "ACTION_LIST":       (0x00596C3C, [("..game.actions", "ACTION_LIST")]),
    "ACTION_MENU_COUNT": (0x00518D14, [("..game.actions", "MENU_COUNT")]),
    "ACTION_MENU_INDEX": (0x00518D1C, [("..game.actions", "MENU_INDEX")]),
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
