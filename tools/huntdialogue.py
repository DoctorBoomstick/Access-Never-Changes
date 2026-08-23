#!/usr/bin/env python3
"""Prove -- or disprove -- where Fallout 2 keeps the dialogue screen's text.

Dialogue is the last big thing the mod cannot read. The engine keeps the whole
screen in static globals: the line the NPC just said, and an array of the
replies offered back. If those addresses are real on this build, the in-game
script can read them with sfall's `read_string` and the mod never has to invent
an English word of it -- the text is the game's own, already translated.

The candidates below come from fallout2-ce, a faithful reimplementation which
annotates every global with its address in the original executable. That makes
them a *hypothesis*, which is all an address from someone else's source ever is.
This tool is how the hypothesis gets tested against the running game, in the
same spirit as every other address in `found.json`: read it, watch it change
when the screen changes, and only then write it down.

    python tools/huntdialogue.py              read the candidates once
    python tools/huntdialogue.py --watch      print them whenever they change
    python tools/huntdialogue.py --find TEXT  where does this string live?

`--find` is the fallback. If the candidates read as rubbish, type a phrase that
is on screen right now and this finds it, which is the same search `f2mem.py`
does but shaped for one question.

Read-only, like everything in here.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time
from typing import List, NamedTuple, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fallout2_access.memory import FALLOUT_EXE_NAMES, Process, ProcessNotFound  # noqa: E402

# -- the hypothesis ----------------------------------------------------------
#
# gDialogReplyText        char[900]   what the NPC just said
# gDialogReplyMessageId   int         which line of which .msg file that is,
#                                     which is a far better "has it changed?"
#                                     test than comparing 900 bytes of prose
# gDialogOptionEntries    entry[30]   the replies offered back
# gGameDialogOptionEntriesLength      how many of those 30 are real
#
# The count matters more than it looks. The action menu taught this the hard
# way: the engine's arrays are never cleared, only overwritten, so entry 4 of a
# five-option conversation is still sitting there during the next two-option
# one. Anything that walks the array without believing the count is reading a
# confident list about a conversation that has ended.
REPLY_TEXT = 0x0058F4E4
REPLY_MSGLIST = 0x0058F4D8
REPLY_MSGID = 0x0058F4DC

OPTIONS = 0x0058FF70
OPTION_COUNT = 0x005186D8

# Entry layout: five ints, one more int, char[900], one int.
#   0x00 messageListId  0x04 messageId  0x08 reaction
#   0x0C proc           0x10 btn        0x14 top
#   0x18 text[900]                      0x39C bottom
OPTION_TEXT_OFF = 0x18
OPTION_STRIDE = 0x3A0        # 928
OPTION_MAX = 30

# Window handles, read only as a cross-check: all three should be -1 with no
# dialogue on screen and >= 0 with one up. If they behave that way the rest of
# the neighbourhood is very likely the dialogue's too.
WIN_REPLY = 0x005186E4
WIN_OPTIONS = 0x005186E8
WIN_DIALOG = 0x00518744


class Option(NamedTuple):
    index: int
    msglist: int
    msgid: int
    reaction: int
    proc: int
    btn: int
    top: int
    bottom: int
    text: str


class Reading(NamedTuple):
    count: int
    reply_msglist: int
    reply_msgid: int
    reply: str
    options: List[Option]
    windows: Tuple[int, int, int]

    def key(self) -> tuple:
        """What "it changed" means. Ids and text, not the raw array."""
        return (self.count, self.reply_msgid, self.reply,
                tuple(o.text for o in self.options), self.windows)


def _text(proc: Process, addr: int, limit: int = 900) -> str:
    return (proc.read_cstring(addr, max_len=limit) or "").strip()


def read_all(proc: Process, force: int = 0) -> Optional[Reading]:
    """One snapshot of the dialogue globals.

    `force` reads that many option entries regardless of the count, which is
    how the "never cleared" question gets answered: if entries beyond the count
    still hold last conversation's replies, that is the proof the count is
    load-bearing rather than a convenience.
    """
    count = proc.read_i32(OPTION_COUNT)
    if count is None:
        return None
    wanted = force if force else count
    wanted = max(0, min(wanted, OPTION_MAX))

    options: List[Option] = []
    for i in range(wanted):
        base = OPTIONS + i * OPTION_STRIDE
        head = proc.read(base, 0x18)
        if head is None or len(head) < 0x18:
            break
        msglist, msgid, reaction, proc_, btn, top = struct.unpack("<6i", head)
        bottom = proc.read_i32(base + 0x39C)
        options.append(Option(
            index=i, msglist=msglist, msgid=msgid, reaction=reaction,
            proc=proc_, btn=btn, top=top, bottom=bottom if bottom is not None else 0,
            text=_text(proc, base + OPTION_TEXT_OFF),
        ))

    windows = tuple((proc.read_i32(a) if proc.read_i32(a) is not None else -99)
                    for a in (WIN_DIALOG, WIN_REPLY, WIN_OPTIONS))
    return Reading(
        count=count,
        reply_msglist=proc.read_i32(REPLY_MSGLIST) or 0,
        reply_msgid=proc.read_i32(REPLY_MSGID) or 0,
        reply=_text(proc, REPLY_TEXT),
        options=options,
        windows=windows,  # type: ignore[arg-type]
    )


def show(reading: Reading, verbose: bool = False) -> None:
    print("  windows: dialog={} reply={} options={}".format(*reading.windows))
    print("  reply [{}:{}]: {!r}".format(
        reading.reply_msglist, reading.reply_msgid, reading.reply[:300]))
    print("  options: count={}".format(reading.count))
    for o in reading.options:
        mark = " " if o.index < reading.count else "*"   # * = past the count
        print("   {}{:>2}. [{}:{}] react={} btn={} y={}..{} {!r}".format(
            mark, o.index + 1, o.msglist, o.msgid, o.reaction, o.btn,
            o.top, o.bottom, o.text[:200]))
    if verbose:
        print("  (* marks entries past the count -- stale, if they hold text)")


def find(proc: Process, needle: str) -> None:
    """Where does this exact text live? The fallback when a candidate misses."""
    raw = needle.encode("cp1252")
    hits = 0
    for region in proc.regions():
        data = proc.read_chunked(region.base, region.size)
        at = data.find(raw)
        while at >= 0:
            addr = region.base + at
            note = ""
            # Is it inside the option array we expect? Say where, since an
            # offset that is a clean multiple of the stride is itself evidence.
            if OPTIONS <= addr < OPTIONS + OPTION_MAX * OPTION_STRIDE:
                rel = addr - OPTIONS
                note = "  <- options[{}] + 0x{:X}".format(
                    rel // OPTION_STRIDE, rel % OPTION_STRIDE)
            elif REPLY_TEXT <= addr < REPLY_TEXT + 900:
                note = "  <- reply text + 0x{:X}".format(addr - REPLY_TEXT)
            print("  0x{:08X}{}".format(addr, note))
            hits += 1
            if hits >= 40:
                print("  ... stopping at 40")
                return
            at = data.find(raw, at + 1)
    if not hits:
        print("  not found -- is that text exactly as it appears on screen?")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true",
                    help="poll and print whenever the dialogue state changes")
    ap.add_argument("--find", metavar="TEXT",
                    help="search memory for a string that is on screen now")
    ap.add_argument("--force", type=int, default=0, metavar="N",
                    help="read N option entries regardless of the count")
    ap.add_argument("--hz", type=float, default=8.0)
    args = ap.parse_args()

    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except ProcessNotFound as exc:
        print("not attached: {}".format(exc))
        return 2
    print("attached to pid {}".format(proc.pid))

    if args.find:
        print("searching for {!r} ...".format(args.find))
        find(proc, args.find)
        return 0

    if not args.watch:
        reading = read_all(proc, force=args.force)
        if reading is None:
            print("could not read the candidates at all")
            return 1
        show(reading, verbose=True)
        return 0

    print("watching -- talk to someone. Ctrl+C to stop.")
    last = None
    try:
        while True:
            reading = read_all(proc, force=args.force)
            if reading is not None and reading.key() != last:
                last = reading.key()
                print("\n[{}]".format(time.strftime("%H:%M:%S")))
                show(reading)
            time.sleep(1.0 / args.hz)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
