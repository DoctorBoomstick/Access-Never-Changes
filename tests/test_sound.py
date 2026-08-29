"""The step tick.

Speech was the wrong shape for this. A walk is several seconds of the mod
correctly saying nothing, and nothing is also what a mod that has stopped
working sounds like -- which is how players read it, reporting the mod as
broken or the game as sluggish when a character was walking at exactly the
speed Fallout walks.

Nothing here plays a sound. What is checked is that the bytes handed to Windows
are a WAV, that a tick cannot be produced faster than a human can interpret one,
and that a sound device which refuses to co-operate cannot take the rest of the
mod down with it.
"""

import struct
import unittest

from fallout2_access import sound


class TestTheTone(unittest.TestCase):
    def test_it_is_a_riff_wave(self):
        w = sound.wave_bytes()
        self.assertEqual(w[:4], b"RIFF")
        self.assertEqual(w[8:12], b"WAVE")

    def test_the_declared_lengths_match_the_bytes(self):
        """A WAV whose header disagrees with its payload plays as a burst of
        noise, which is a poor thing to hear once per hex."""
        w = sound.wave_bytes()
        self.assertEqual(struct.unpack("<I", w[4:8])[0], len(w) - 8)
        self.assertEqual(struct.unpack("<I", w[40:44])[0], len(w) - 44)

    def test_it_is_short(self):
        """It plays as often as you take a step. Anything with a tail becomes
        unbearable by the second room."""
        self.assertLess(sound.DURATION, 0.1)

    def test_it_ends_at_silence(self):
        """A tone that stops dead clicks. The last sample should be near zero
        because the envelope has faded, not because the sine happens to be
        crossing there."""
        w = sound.wave_bytes()
        last = struct.unpack("<h", w[-2:])[0]
        self.assertLess(abs(last), 400)


class _Recording(sound.Ticker):
    """A Ticker that records instead of playing, on this thread."""

    def __init__(self, **kw):
        sound.Ticker.__init__(self, **kw)
        self.played = 0
        self._looked = True
        self._play = lambda *a: None
        self._wav = b""

    def _run(self):
        self.played += 1
        self._busy = False


class TestTheTicker(unittest.TestCase):
    def test_a_step_plays_once(self):
        t = _Recording()
        t.step()
        self.assertEqual(t.played, 1)

    def test_disabled_plays_nothing(self):
        t = _Recording(enabled=False)
        t.step()
        self.assertEqual(t.played, 0)

    def test_a_burst_is_thinned(self):
        """A log catching up after a stall delivers a dozen steps at once, and
        a dozen ticks in one breath is a noise nobody can interpret."""
        t = _Recording()
        for _ in range(12):
            t.step()
        self.assertEqual(t.played, 1)

    def test_the_gap_leaves_room_for_a_run(self):
        """Running in Fallout is about five hexes a second, and that rhythm is
        the whole point -- a limit that swallowed it would report a walk as a
        stroll."""
        self.assertLess(sound.MIN_GAP, 1.0 / 5)

    def test_a_refusing_sound_device_switches_itself_off(self):
        """And takes nothing with it. A mod that stops reading the game out
        because a sound card is busy would be a worse mod than a quiet one."""
        t = sound.Ticker()
        t._looked = True
        t._wav = b""
        t._play = lambda *a: (_ for _ in ()).throw(RuntimeError("no device"))
        t.step()
        for _ in range(200):          # it plays on a thread; let it finish
            if not t._busy:
                break
            import time
            time.sleep(0.01)
        self.assertFalse(t.enabled)

    def test_without_winsound_it_goes_quiet_rather_than_failing(self):
        t = sound.Ticker()
        t._load = lambda: False
        t.step()
        self.assertFalse(t.enabled)


if __name__ == "__main__":
    unittest.main()
