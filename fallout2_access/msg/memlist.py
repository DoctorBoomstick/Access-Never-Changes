"""Enumerate Fallout 2 message lists directly out of the running game.

The engine parses each .msg file into an array of fixed-size records:

    struct MessageListItem {   // 16 bytes
        int   num;             // +0   message number
        int   flags;           // +4
        char* audio;           // +8
        char* text;            // +12
    };

Layout confirmed empirically against the live process: message numbers 305
'Damage Res.' through 318 'Crippled Left Leg' run consecutively at a 16-byte
stride, with the 400-block holding the matching descriptions.

Reading text this way rather than from .msg files on disk means we need no DAT2
archive reader, and -- more importantly -- we get whatever the game actually
loaded. Translations and text-replacing content mods come along for free, and
we never hardcode an English string.
"""

from __future__ import annotations

import struct
from typing import Dict, Iterator, List, NamedTuple, Optional, Sequence

from ..memory.process import Process, Region

ITEM_SIZE = 16
OFF_NUM = 0
OFF_FLAGS = 4
OFF_AUDIO = 8
OFF_TEXT = 12

# A record's text pointer must land in this range to be worth dereferencing.
_PTR_MIN = 0x00010000
_PTR_MAX = 0x7FFF0000


class MessageEntry(NamedTuple):
    num: int
    text: str
    addr: int


class MessageList(NamedTuple):
    base: int
    entries: List[MessageEntry]

    @property
    def count(self) -> int:
        return len(self.entries)

    def by_num(self) -> Dict[int, str]:
        return {e.num: e.text for e in self.entries}

    def get(self, num: int) -> Optional[str]:
        for entry in self.entries:
            if entry.num == num:
                return entry.text
        return None

    def numbers(self) -> str:
        """Compact description of the message-number span, for identification."""
        if not self.entries:
            return "(empty)"
        nums = sorted(e.num for e in self.entries)
        return "{}-{}".format(nums[0], nums[-1])


def _printable(s: Optional[str]) -> bool:
    """Printable, or legitimately empty.

    An empty message text is valid and common -- .msg files carry blank
    entries. Treating "" as invalid made the array walk stop at the first one,
    which truncated stat.msg to 39 of its 97 entries and left skill.msg with a
    wrong base address that matched no static global.
    """
    if s is None:
        return False
    return all(32 <= ord(c) < 127 or c in "\t" for c in s)


class _Peek:
    """Cached reads so walking an array doesn't issue thousands of syscalls."""

    def __init__(self, proc: Process) -> None:
        self.proc = proc
        self._strings: Dict[int, Optional[str]] = {}

    def u32(self, addr: int) -> Optional[int]:
        return self.proc.read_u32(addr)

    def text(self, ptr: int, limit: int = 512) -> Optional[str]:
        if ptr in self._strings:
            return self._strings[ptr]
        s: Optional[str] = None
        if _PTR_MIN < ptr < _PTR_MAX:
            raw = self.proc.read_cstring(ptr, limit)
            if _printable(raw):
                s = raw
        self._strings[ptr] = s
        return s


def _read_entry(peek: _Peek, base: int) -> Optional[MessageEntry]:
    num = peek.u32(base + OFF_NUM)
    text_ptr = peek.u32(base + OFF_TEXT)
    if num is None or text_ptr is None:
        return None
    if num > 0xFFFFFF:
        return None
    text = peek.text(text_ptr)
    if text is None:
        return None
    return MessageEntry(num=num, text=text, addr=base)


def _walk(peek: _Peek, seed: int, limit: int = 20000) -> Optional[MessageList]:
    """Expand from a seed record to the whole contiguous array."""
    if _read_entry(peek, seed) is None:
        return None

    start = seed
    steps = 0
    while steps < limit:
        prev = start - ITEM_SIZE
        entry = _read_entry(peek, prev)
        if entry is None:
            break
        start = prev
        steps += 1

    entries: List[MessageEntry] = []
    addr = start
    while len(entries) < limit:
        entry = _read_entry(peek, addr)
        if entry is None:
            break
        entries.append(entry)
        addr += ITEM_SIZE

    if len(entries) < 4:
        return None
    return MessageList(base=start, entries=entries)


def read_message_list(proc: Process, global_addr: int, limit: int = 20000) -> Optional[MessageList]:
    """Read a MessageList from its static global.

    Preferred over walking the array: the global states the entry count
    explicitly, so entries with null text pointers -- which do occur, and which
    silently truncated an earlier heuristic walk of stat.msg to 39 of its 97
    entries -- are read correctly instead of ending the list.
    """
    count = proc.read_i32(global_addr)
    entries_ptr = proc.read_u32(global_addr + 4)
    if count is None or entries_ptr is None:
        return None
    if not (0 < count <= limit) or not (_PTR_MIN < entries_ptr < _PTR_MAX):
        return None

    raw = proc.read_chunked(entries_ptr, count * ITEM_SIZE)
    if len(raw) < count * ITEM_SIZE:
        return None

    peek = _Peek(proc)
    entries: List[MessageEntry] = []
    for i in range(count):
        off = i * ITEM_SIZE
        num = struct.unpack_from("<I", raw, off + OFF_NUM)[0]
        text_ptr = struct.unpack_from("<I", raw, off + OFF_TEXT)[0]
        text = peek.text(text_ptr) if _PTR_MIN < text_ptr < _PTR_MAX else ""
        entries.append(
            MessageEntry(num=num, text=text or "", addr=entries_ptr + off)
        )
    return MessageList(base=entries_ptr, entries=entries)


def find_message_list_globals(
    proc: Process, min_entries: int = 8, limit: int = 20000
) -> Dict[int, MessageList]:
    """Find every `MessageList { int count; item* entries }` in the exe's data.

    Returns {global_address: MessageList}. These globals are statically
    allocated, so unlike the heap arrays they point at, they are stable across
    runs and are what the shipped mod resolves.
    """
    out: Dict[int, MessageList] = {}
    for region in proc.module_regions():
        data = proc.read_chunked(region.base, region.size)
        for off in range(0, len(data) - 8, 4):
            count = struct.unpack_from("<I", data, off)[0]
            if not (min_entries <= count <= limit):
                continue
            entries_ptr = struct.unpack_from("<I", data, off + 4)[0]
            if not (_PTR_MIN < entries_ptr < _PTR_MAX):
                continue
            # Cheap plausibility test on the first two records before commiting
            # to reading the whole array.
            head = proc.read(entries_ptr, ITEM_SIZE * 2)
            if head is None or len(head) < ITEM_SIZE * 2:
                continue
            n0 = struct.unpack_from("<I", head, OFF_NUM)[0]
            n1 = struct.unpack_from("<I", head, ITEM_SIZE + OFF_NUM)[0]
            t0 = struct.unpack_from("<I", head, OFF_TEXT)[0]
            if n0 > 0xFFFFFF or n1 <= n0 or n1 > 0xFFFFFF:
                continue
            if not (_PTR_MIN < t0 < _PTR_MAX):
                continue

            lst = read_message_list(proc, region.base + off, limit)
            if lst and lst.count >= min_entries:
                texts = [e.text for e in lst.entries if e.text]
                if len(texts) >= min_entries // 2:
                    out[region.base + off] = lst
    return out


def find_message_lists(
    proc: Process,
    regions: Optional[Sequence[Region]] = None,
    min_entries: int = 8,
) -> List[MessageList]:
    """Locate every message list currently loaded in the process.

    Scans for a run of records whose text pointers dereference to printable
    strings and whose message numbers increase -- a shape that essentially does
    not occur by accident.
    """
    if regions is None:
        regions = [r for r in proc.regions(writable_only=True)]

    peek = _Peek(proc)
    found: List[MessageList] = []
    claimed: List[range] = []

    def already_claimed(addr: int) -> bool:
        return any(addr in r for r in claimed)

    for region in regions:
        data = proc.read_chunked(region.base, region.size)
        # Candidate seeds. Step by 4, not by ITEM_SIZE: an array is only
        # guaranteed pointer-aligned, and the char editor's own message list
        # turned out to sit at 8 mod 16 -- a 16-byte stride walked straight
        # past it.
        #
        # The cheap struct tests run before the claimed-range check, which is
        # linear in the number of lists found so far; at this stride almost
        # every offset is rejected by the first two comparisons.
        for off in range(0, len(data) - ITEM_SIZE * 3, 4):
            num = struct.unpack_from("<I", data, off + OFF_NUM)[0]
            if num > 0xFFFFFF:
                continue
            text_ptr = struct.unpack_from("<I", data, off + OFF_TEXT)[0]
            if not (_PTR_MIN < text_ptr < _PTR_MAX):
                continue
            nxt = struct.unpack_from("<I", data, off + ITEM_SIZE + OFF_NUM)[0]
            if nxt <= num or nxt > 0xFFFFFF:
                continue
            addr = region.base + off
            if already_claimed(addr):
                continue
            if peek.text(text_ptr) is None:
                continue

            lst = _walk(peek, addr)
            if lst and lst.count >= min_entries:
                found.append(lst)
                claimed.append(
                    range(lst.base, lst.base + lst.count * ITEM_SIZE + ITEM_SIZE)
                )

    found.sort(key=lambda l: l.base)
    return found
