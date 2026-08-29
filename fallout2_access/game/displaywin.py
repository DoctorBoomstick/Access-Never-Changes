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

**Capacity: exactly 100 records**, measured against the live process. The beacon
anchored at 0x7BCFC0 and the zeroed run ended at 0x7C33C0, which is anchor +
100 * 256, with a heap block header immediately after it. So this is a *ring*,
not an ever-growing list.

That distinction was a silent, session-ending bug. An earlier version walked
forward from the anchor with an index that only ever increased, which is correct
for the first 100 messages and wrong for every one after: the index marched off
the end of the array into the next heap block, and the game's own words went
quiet for the rest of the session. Worse, `App.pump_display` switches the mod's
own combat narration *off* once this buffer is found, so past message 100 a
blow was narrated by nobody at all.

**Continuation lines.** The engine word-wraps one message across consecutive
records, and only the first carries the colour byte. Checked against six samples
in a live buffer: "For destroying your enemies without taking a" (colour byte)
followed by "scratch,  you earn 25 exp. points." (none). So a record with the
colour byte starts a message and a record without one continues the record
before it, and the two are spoken as one sentence.

**Finding it.** The buffer is heap-allocated and moves every launch, and there
is no static pointer to it anywhere in the executable -- 18 static pointers
reach into that region and not one of them points here. Searching for the shape
does not work either: zeroed heap is indistinguishable from an empty record, and
a structural scan turns up hundreds of candidates.

So the script plants a beacon. `gl_world.ssl` prints one known line at session
start, we search for exactly that, and the record it lands in anchors
everything. One scan, one hit, no shortlist -- and it stays correct on any build
of the game, which an address never would.

Note the beacon is *transient*: it is one record in a 100-record ring, so it is
overwritten once the session has printed 100 messages. Locating therefore has to
succeed early in a session, which it does -- the beacon is printed the moment a
game loads, and `App.pump_display` starts looking as soon as the script reports
a live session.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

RECORD = 0x100      # bytes per message record
TEXT_OFFSET = 8     # message text begins here

BEACON = b"Access Never Changes ready."

# Records in the ring. Measured, not assumed -- see the module docstring.
CAPACITY = 100

# How many messages can arrive between two polls and still be ordered correctly
# if the engine turns out to scroll. At 20Hz, more than a handful in 50ms is
# already implausible; this only bounds the search, and anything beyond it falls
# through to the change-detection path below.
MAX_SHIFT = 16


def _record_parts(record: bytes) -> Tuple[bool, str]:
    """(starts_a_message, text) for one record.

    The bool is the colour byte's presence, which is what distinguishes the
    first line of a wrapped message from its continuations.
    """
    if len(record) < TEXT_OFFSET + 1:
        return False, ""
    body = record[TEXT_OFFSET:]
    # A leading high-bit byte is a colour code the engine prefixes to the first
    # line of each message. It is formatting, not something anyone said -- but
    # its *presence* is meaningful, so it is reported rather than just dropped.
    head = bool(body and body[0] >= 0x80)
    if head:
        body = body[1:]
    end = body.find(b"\x00")
    if end >= 0:
        body = body[:end]
    if not body:
        return head, ""
    try:
        text = body.decode("cp1252")
    except Exception:
        return head, ""
    text = text.strip()
    # **A record that is not text is not a message.** cp1252 decodes very
    # nearly any byte, so this used to hand whatever it found straight to the
    # speaker: heap noise arrived as "D<?>" and "pE<?>" and was read out, over
    # and over, on top of everything the mod had to say.
    #
    # This is a guard, not a cure. The cause is upstream -- the anchor this
    # window is read from goes stale when the engine moves the ring, and every
    # read after that is of something else's memory. The right fix is to notice
    # that and go looking again. Until then, refusing to speak what cannot be a
    # sentence is strictly better than speaking it, and costs nothing: the
    # engine's own lines are ordinary printable text.
    if not _readable(text):
        return head, ""
    return head, text


# What the engine actually writes here is prose, sometimes with an accented
# character in a translated game. Control characters are not prose, and a run of
# them is the signature of reading the wrong place.
def _readable(text: str) -> bool:
    if not text:
        return True
    if any(ord(c) < 32 for c in text):
        return False
    # Two or three stray bytes decode to plausible letters often enough to slip
    # through a per-character test, so the length is a test too: the engine does
    # not write one-character messages, and every real line this mod has seen
    # runs to several words.
    printable = sum(1 for c in text if 32 <= ord(c) < 127)
    return printable >= max(3, len(text) * 0.8)


def _record_text(record: bytes) -> str:
    """The message in one record, or "" if it holds none."""
    return _record_parts(record)[1]


def _shifted_by(prev: List[Tuple[bool, str]], now: List[Tuple[bool, str]],
                limit: int = MAX_SHIFT) -> int:
    """How far the ring scrolled, or 0 if it did not.

    A scroll moves every record up by `s` and writes `s` new ones at the end.
    """
    for s in range(1, limit + 1):
        if all(prev[i + s] == now[i] for i in range(CAPACITY - s)):
            return s
    return 0


def _contiguous_run(changed: List[int]) -> Optional[List[int]]:
    """Order changed indices as one run, allowing for a wrap past the end.

    Returns None if they are not one run, which means we cannot say what order
    they were written in.
    """
    marked = set(changed)
    if not marked:
        return []
    if len(marked) == CAPACITY:
        return sorted(marked)
    # A run starts at the one index whose predecessor was left alone.
    starts = [i for i in marked if (i - 1) % CAPACITY not in marked]
    if len(starts) != 1:
        return None
    run: List[int] = []
    i = starts[0]
    while i in marked:
        run.append(i)
        i = (i + 1) % CAPACITY
    return run if len(run) == len(marked) else None


class DisplayWindow:
    """Tails the game's message ring and reports lines as they appear."""

    def __init__(self, proc) -> None:
        self.proc = proc
        self.anchor: Optional[int] = None
        # The whole ring as it looked last poll. Comparing snapshots is what
        # lets this work without knowing whether the engine appends, scrolls or
        # wraps -- the behaviour is *discovered* each poll rather than assumed,
        # which is the same reason the rest of the mod re-reads state instead of
        # remembering it.
        self._prev: Optional[List[Tuple[bool, str]]] = None
        # A message whose continuation lines may not have landed yet.
        self._pending: Optional[List[str]] = None

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
                    self.anchor = self._ring_start(start)
                    # Whatever is in the ring right now predates us listening.
                    # The first poll adopts it silently: announcing it would
                    # narrate the past as though it had just happened, which is
                    # exactly the kind of confident wrong statement the rest of
                    # this mod refuses to make.
                    self._prev = None
                    self._pending = None
                    return True
                at = data.find(BEACON, at + 1)
        return False

    def _ring_start(self, beacon: int) -> int:
        """Walk back from the beacon's record to the first record of the ring.

        The beacon is normally the ring's first message -- the script prints it
        the instant a game loads, into a buffer that has just been allocated --
        and every measurement so far shows it at index 0 with empty records in
        front of it.

        But that is an assumption about timing, not a fact about the layout, and
        if it is ever wrong the consequences are the bug this file was rewritten
        to fix: anchoring `k` records into a 100-record ring makes every read
        run `k` records past the end and into the next heap block.

        So it is checked rather than assumed. Records before the beacon that
        still hold text are earlier messages, and each one moves the true start
        back by one.
        """
        start = beacon
        for _ in range(CAPACITY - 1):
            probe = self.proc.read_chunked(start - RECORD, RECORD) or b""
            if len(probe) < RECORD or not _record_text(probe):
                break
            start -= RECORD
        return start

    @property
    def located(self) -> bool:
        return self.anchor is not None

    def reset(self) -> None:
        """Forget the buffer. Called when a new session reprints the beacon.

        The ring is reallocated when a game is loaded, so an anchor from the
        previous session points at freed heap and would report nothing for ever.
        """
        self.anchor = None
        self._prev = None
        self._pending = None

    # -- reading --------------------------------------------------------

    def _snapshot(self) -> Optional[List[Tuple[bool, str]]]:
        if self.anchor is None:
            return None
        data = self.proc.read_chunked(self.anchor, CAPACITY * RECORD)
        if not data or len(data) < CAPACITY * RECORD:
            return None
        return [_record_parts(data[i * RECORD:(i + 1) * RECORD])
                for i in range(CAPACITY)]

    def _arrived(self, prev, now) -> Optional[List[int]]:
        """Indices of records written since the last poll, in writing order."""
        if prev == now:
            return []
        shift = _shifted_by(prev, now)
        if shift:
            return list(range(CAPACITY - shift, CAPACITY))
        changed = [i for i in range(CAPACITY) if prev[i] != now[i]]
        return _contiguous_run(changed)

    def _absorb(self, indices: List[int], now) -> List[str]:
        """Group new records into whole messages.

        A record carrying the colour byte begins a message; one without it
        continues the record before it. The last group is held back for one poll
        so that a continuation landing a frame later still joins its own
        sentence rather than being spoken as a fragment.
        """
        out: List[str] = []
        for i in indices:
            head, text = now[i]
            if not text:
                continue     # a cleared slot is not a message
            if head or self._pending is None:
                if self._pending is not None:
                    out.append(" ".join(self._pending))
                self._pending = [text]
            else:
                self._pending.append(text)
        return out

    def _flush(self) -> List[str]:
        """Nothing new arrived, so the held message is finished."""
        if self._pending is None:
            return []
        text = " ".join(self._pending)
        self._pending = None
        return [text] if text else []

    def poll(self) -> List[str]:
        """Every message written since the last call."""
        now = self._snapshot()
        if now is None:
            return []
        prev, self._prev = self._prev, now
        if prev is None:
            return []       # first look: adopt, do not narrate the past

        arrived = self._arrived(prev, now)
        if arrived is None:
            # Records changed in a pattern we cannot put in order -- several
            # polls' worth at once, most likely. Say them in ring order rather
            # than dropping them: a slightly wrong order in a rare resync is a
            # smaller harm than a death message that is never spoken, which is
            # the failure this whole file exists to fix.
            print("[display] out-of-order resync", flush=True)
            arrived = [i for i in range(CAPACITY) if prev[i] != now[i]]
        if not arrived:
            return self._flush()
        return self._absorb(arrived, now)
