"""Read the interface bar's display window -- the game's own words.

The strip along the bottom of the screen is where Fallout tells the player
everything in prose: "You see: a door", "It's locked", who hit whom for how
much, what a skill achieved. Nothing in sfall can read it back, so the mod reads
it out of the game's memory.

This matters more than any single feature. Everything else the mod says about
the world it assembles itself, in English, out of hook arguments -- which is a
reconstruction of what the game already said, and useless in any other language.
These are the real sentences, already written, already translated.

**Layout**, established by planting a known string and looking at where it
landed. Records are 256 bytes; the text starts at +8 and runs to a NUL; a
leading byte with the high bit set is a colour code and not part of the message.
Messages append forward, one record at a time.

**Finding it.** The buffer is heap-allocated and moves every launch, and there
is no static pointer to it anywhere in the executable -- 18 static pointers
reach into that region and not one of them points here. Searching for the shape
does not work either: zeroed heap is indistinguishable from an empty record, and
a structural scan turns up hundreds of candidates.

So the script plants a beacon. `gl_world.ssl` prints one known line at session
start, we search for exactly that, and the record it lands in anchors
everything. One scan, one hit, no shortlist -- and it stays correct on any build
of the game, which an address never would.
"""

from __future__ import annotations

from typing import List, Optional

RECORD = 0x100      # bytes per message record
TEXT_OFFSET = 8     # message text begins here

BEACON = b"Access Never Changes ready."

# How far ahead of the anchor to watch. Messages append one record at a time, so
# this only has to cover what can arrive between two polls -- but it is cheap,
# and a wide window means a burst of combat text cannot outrun us.
WINDOW = 256


def _record_text(record: bytes) -> str:
    """The message in one record, or "" if it holds none."""
    if len(record) < TEXT_OFFSET + 1:
        return ""
    body = record[TEXT_OFFSET:]
    # A leading high-bit byte is a colour code the engine prefixes to some
    # lines. It is formatting, not something anyone said.
    if body and body[0] >= 0x80:
        body = body[1:]
    end = body.find(b"\x00")
    if end >= 0:
        body = body[:end]
    if not body:
        return ""
    try:
        text = body.decode("cp1252")
    except Exception:
        return ""
    return text.strip()


class DisplayWindow:
    """Tails the game's message buffer and reports lines as they appear."""

    def __init__(self, proc) -> None:
        self.proc = proc
        self.anchor: Optional[int] = None
        self._next = 0          # index of the next record we have not read

    # -- locating -------------------------------------------------------

    def locate(self) -> bool:
        """Find the beacon and anchor on it. False if it is not there yet.

        Not an error to fail: the beacon is printed when a game loads, so
        before that there is genuinely nothing to find.
        """
        wanted = BEACON.decode("cp1252")
        for region in self.proc.regions():
            if region.size > 64 * 1024 * 1024:
                continue
            data = self.proc.read_chunked(region.base, region.size)
            if not data:
                continue
            # EVERY occurrence, not just the first. The text also appears in the
            # compiled script's own string table, which is not a message record,
            # and stopping at the first hit finds only that.
            at = data.find(BEACON)
            while at >= 0:
                addr = region.base + at
                # Step back to the true start of the record. A colour byte may
                # sit in front of the text, and BOTH candidate offsets parse the
                # beacon correctly -- so the choice cannot be made by trying
                # each and seeing which reads back. Look at the byte before the
                # text instead: high bit set means a colour code is there and
                # the record begins one earlier. Getting this wrong shifts every
                # subsequent record by a byte, which goes unnoticed until a line
                # arrives without a colour code and loses its first letter.
                lead = TEXT_OFFSET
                before = self.proc.read_chunked(addr - 1, 1) or b"\x00"
                if before[0] >= 0x80:
                    lead = TEXT_OFFSET + 1
                start = addr - lead
                probe = self.proc.read_chunked(start, RECORD) or b""
                if _record_text(probe) == wanted:
                    self.anchor = start
                    self._next = 1  # the beacon itself needs no announcing
                    return True
                at = data.find(BEACON, at + 1)
        return False

    @property
    def located(self) -> bool:
        return self.anchor is not None

    def reset(self) -> None:
        self.anchor = None
        self._next = 0

    # -- reading --------------------------------------------------------

    def poll(self) -> List[str]:
        """Every message written since the last call."""
        if self.anchor is None:
            return []
        base = self.anchor + self._next * RECORD
        data = self.proc.read_chunked(base, WINDOW * RECORD)
        if not data:
            return []

        out: List[str] = []
        consumed = 0
        for i in range(len(data) // RECORD):
            text = _record_text(data[i * RECORD:(i + 1) * RECORD])
            if not text:
                # An empty record is the end of what has been written. Stop
                # rather than skipping it: the engine fills these in order, and
                # reading past the end would swallow a message that is about to
                # land in that very slot.
                break
            out.append(text)
            consumed = i + 1
        self._next += consumed
        return out
