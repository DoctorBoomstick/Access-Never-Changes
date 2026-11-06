"""The subtitles: movies, and the narration over the ending slides.

The game ships them as text -- text\\<language>\\cuts\\*.sve for the movies,
nar_*.txt for the endings -- and loads them only with `subtitles=1` in
fallout2.cfg, which the installer sets. Both are read out of the engine at the
moment it draws them rather than timed from the files here, so a line is said
when the voice says it and a skipped movie says nothing more.

Movies
------
The engine parses the .sve into a list when the movie opens (0x00487380):

    0x00638E74   head of the list: the next line not yet drawn
    node +0x00   char *text
    node +0x04   int   frame it is drawn on
    node +0x08   node *next
    0x00638E78   the movie's flags; 0x10 is "subtitles on"

Every frame (0x0048755C) it draws each node whose frame has come, then frees
the text and the node and moves the head on. **So the line on screen is
already freed memory.** Its text has to be read while it is still the head --
the line coming up -- and kept, and it is said when the head moves past it.

Closing the movie (0x004870B4) walks the same list freeing it, one node at a
time exactly as drawing does, and only then clears the flags. So a node that
leaves the list is not proof it was drawn: it is held for a tick, and dropped
if the flags went with it. That is the difference between a line the movie
reached and the rest of a movie skipped with Space.

Ending slides
-------------
Each slide's narration is split into lines up front (0x004403F0) and timed
against the length of the speech:

    0x00570BC8   char *lines[50]
    0x00518668   how many there are, 0 between slides
    0x00518670   the one on screen; moved on when its time is up (0x004406A4)
    0x00570BCC   subtitles on

The strings live until the slide ends, so the current one is read where it is.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

MOVIE_HEAD = 0x00638E74
MOVIE_FLAGS = 0x00638E78
MOVIE_SUBTITLES_ON = 0x10
NODE_TEXT = 0x00
NODE_FRAME = 0x04
NODE_NEXT = 0x08

ENDING_LINES = 0x00570BC8
ENDING_COUNT = 0x00518668
ENDING_CURRENT = 0x00518670
ENDING_ON = 0x00570BCC
# The engine stops reading a narration file at 50 lines (0x0044047E).
ENDING_MAX = 50

# Longer than any .sve the game ships; anything past it is a loop or garbage.
MAX_NODES = 1000
MAX_TEXT = 1024


class MovieSubtitles:
    """Says each movie subtitle as the engine draws it."""

    def __init__(self) -> None:
        # The lines still to come, as last read: (node, text), head first.
        self._ahead: List[Tuple[int, str]] = []
        # Lines that left the list last tick, waiting to hear whether the movie
        # is still playing.
        self._left: List[str] = []

    def poll(self, proc) -> List[str]:
        """The lines drawn since the last call, oldest first."""
        flags = proc.read_i32(MOVIE_FLAGS)
        on = flags is not None and bool(flags & MOVIE_SUBTITLES_ON)
        head = proc.read_ptr(MOVIE_HEAD) if on else 0

        # Last tick's leavers were drawn if the movie is still going now.
        drawn = [t for t in self._left if t.strip()] if on else []
        self._left = []

        if not on:
            self._ahead = []
            return drawn

        nodes = [n for n, _ in self._ahead]
        if head in nodes:
            gone = nodes.index(head)
        elif head == 0:
            gone = len(nodes)   # the last line went
        else:
            # A head never seen is a different list, not progress through this
            # one. The list is walked again every tick, so this one's own
            # lines are always in hand before the engine reaches them.
            gone = 0
        self._left = [t for _, t in self._ahead[:gone]]
        self._ahead = self._walk(proc, head, dict(self._ahead))
        return drawn

    @staticmethod
    def _walk(proc, node: int, known: Dict[int, str]) -> List[Tuple[int, str]]:
        out: List[Tuple[int, str]] = []
        seen = set()
        while node and node not in seen and len(out) < MAX_NODES:
            seen.add(node)
            text = known.get(node)
            if text is None:
                ptr = proc.read_ptr(node + NODE_TEXT)
                text = (proc.read_cstring(ptr, MAX_TEXT) if ptr else None) or ""
            out.append((node, text))
            node = proc.read_ptr(node + NODE_NEXT) or 0
        return out


class EndingSubtitles:
    """Says each line of an ending slide's narration as it comes up."""

    def __init__(self) -> None:
        self._last: Optional[Tuple[int, int, int]] = None

    def poll(self, proc) -> List[str]:
        on = proc.read_i32(ENDING_ON)
        count = proc.read_i32(ENDING_COUNT)
        current = proc.read_i32(ENDING_CURRENT)
        lines = proc.read_ptr(ENDING_LINES)
        if (not on or not lines or count is None or current is None
                or not (0 < count <= ENDING_MAX) or not (0 <= current < count)):
            if not count:
                self._last = None
            return []
        ptr = proc.read_ptr(lines + 4 * current)
        if not ptr:
            return []
        key = (lines, current, ptr)
        if key == self._last:
            return []
        self._last = key
        text = proc.read_cstring(ptr, MAX_TEXT)
        return [text] if text and text.strip() else []


class Subtitles:
    """Both kinds, polled on every screen: a movie can start from anywhere."""

    def __init__(self) -> None:
        self.movie = MovieSubtitles()
        self.ending = EndingSubtitles()

    def poll(self, proc) -> List[str]:
        return self.movie.poll(proc) + self.ending.poll(proc)
