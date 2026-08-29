"""A short tick, for the things speech is the wrong shape for.

Fallout moves you one hex at a time and takes its own time about it. A walk
across a room is several seconds during which the mod, correctly, says nothing:
the arrival is announced when it happens, and narrating each hex would be
twelve interruptions for one journey. That was the right call about *speech*
and it left a real gap, because silence is also what a mod that has stopped
working sounds like. Players reported the mod not responding, or the game being
sluggish, when what was happening was a character walking exactly as fast as
Fallout walks.

A sound is the answer speech could not give. It is not an announcement, so it
does not interrupt, does not queue, and does not have to be listened to -- it
is a pulse that says the game is moving, in the same way the footstep sounds a
sighted player already hears do. One per hex, so its rhythm IS the pace.

**Synthesised rather than shipped.** The tone is generated into memory as a WAV
and handed to the sound API as bytes, so there is no asset in the repository, no
file written anywhere at runtime, and nothing to find at a path that might not
exist. It is about a kilobyte of arithmetic.

**Played on a thread, and it has to be.** Windows will play a sound from memory
or play one asynchronously, and refuses to do both at once -- `PlaySound` with
`SND_MEMORY | SND_ASYNC` answers "Cannot play asynchronously from memory". The
alternatives were writing a temporary file just to be allowed to name it, or
blocking the poll loop for the length of the tone, which is most of the 50ms
that loop has to read the game in. So the play is synchronous on a thread of its
own, one at a time, and the loop never waits for it.

**Windows only, and silent everywhere else.** `winsound` is in the standard
library on the platform this mod runs on, and asking for a cross-platform audio
dependency to play forty milliseconds of sine wave would be a poor trade. Every
failure here is swallowed: a mod that stops working because a sound card is
busy would be a worse mod than one that goes quiet.
"""

from __future__ import annotations

import math
import struct
import threading
import time
from typing import Optional

# What it sounds like. A short, soft, quickly-decaying tone -- close to a knuckle
# on wood, and deliberately nothing like an alert. It plays as often as you take
# a step, so anything with a sharp attack or a long tail becomes unbearable by
# the second room.
RATE = 22050
FREQUENCY = 660.0
DURATION = 0.035
AMPLITUDE = 0.18
# The tail, as a fraction of the whole. A tone that stops dead clicks; one that
# fades over its last third does not.
DECAY_FROM = 0.6

# Steps cannot arrive faster than this, whatever the log says. Running in
# Fallout is about five hexes a second, which is a perfectly good rhythm -- but
# a log catching up after a stall can deliver a dozen at once, and a dozen ticks
# in one breath is a noise nobody can interpret.
MIN_GAP = 0.06


def wave_bytes(frequency: float = FREQUENCY, duration: float = DURATION,
               amplitude: float = AMPLITUDE, rate: int = RATE) -> bytes:
    """A complete mono 16-bit WAV file, as bytes.

    Written out by hand rather than through the `wave` module, which wants a
    file or a file-like object and gives nothing back for the trouble: a RIFF
    header is eleven fields and they are all known here.
    """
    count = max(1, int(rate * duration))
    frames = bytearray()
    for i in range(count):
        # Linear fade over the tail. Exponential decay sounds better on a longer
        # tone; over thirty-five milliseconds nobody can tell, and this cannot
        # underflow to a click at the end.
        position = i / count
        envelope = 1.0
        if position > DECAY_FROM:
            envelope = 1.0 - (position - DECAY_FROM) / (1.0 - DECAY_FROM)
        value = amplitude * envelope * math.sin(2.0 * math.pi * frequency * i / rate)
        frames += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767))

    data = bytes(frames)
    block_align = 2               # one channel, two bytes a sample
    return b"".join((
        b"RIFF",
        struct.pack("<I", 36 + len(data)),
        b"WAVEfmt ",
        struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * block_align,
                    block_align, 16),
        b"data",
        struct.pack("<I", len(data)),
        data,
    ))


class Ticker:
    """Plays the step tick, or does nothing at all if it cannot.

    Built lazily. Generating the tone costs a few milliseconds and there is no
    reason to spend them in a session where nobody ever walks -- and no reason
    to fail at import time on a machine where `winsound` is missing.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._wav: Optional[bytes] = None
        self._play = None
        self._flags = 0
        self._looked = False
        self._last = 0.0
        self._busy = False

    def _load(self) -> bool:
        if self._looked:
            return self._play is not None
        self._looked = True
        try:
            import winsound
        except ImportError:
            print("[sound] winsound not available; step sounds off", flush=True)
            return False
        self._play = winsound.PlaySound
        # SND_MEMORY plays the bytes where they sit, so nothing is written to
        # disk. No SND_ASYNC beside it: Windows refuses the pair outright, which
        # is why this runs on a thread instead.
        self._flags = winsound.SND_MEMORY
        self._wav = wave_bytes()
        return True

    def _run(self) -> None:
        try:
            self._play(self._wav, self._flags)
        except Exception as exc:
            # A sound card that will not play is not a reason to stop reading
            # the game out. Said once, then switched off for the session.
            print("[sound] step tick failed, switching it off: {}".format(exc),
                  flush=True)
            self.enabled = False
        finally:
            self._busy = False

    def step(self) -> None:
        """One hex. Never raises, never blocks, never queues.

        Two guards, and they answer different questions. `MIN_GAP` is about the
        rhythm: a log catching up after a stall delivers a dozen steps at once,
        and a dozen ticks in one breath is a noise nobody can interpret.
        `_busy` is about the device: one tone at a time, because starting a
        second while the first is playing cuts the first off on Windows, so a
        fast walk would produce a stutter rather than a beat.
        """
        if not self.enabled or self._busy:
            return
        now = time.time()
        if now - self._last < MIN_GAP:
            return
        if not self._load():
            self.enabled = False        # asked once, answered once
            return
        self._last = now
        self._busy = True
        thread = threading.Thread(target=self._run)
        thread.daemon = True            # never hold the mod open for a tick
        thread.start()
