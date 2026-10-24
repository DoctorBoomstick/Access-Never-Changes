"""Floating text: the lines characters say over their heads.

Torr is why this exists. Talking to him ran his script, his reaction sums went
into debug.log, and then nothing -- no conversation, no message in the display
window, silence. He had answered. He answers everyone that way: a line of text
floating over his head for a few seconds, and the mod had no idea floating text
was a thing. A character with nothing to say and a mod that failed to talk to
him sounded exactly alike.

**The words are not kept.** text_object_create (0x4B036C) takes the string,
word-wraps it, draws it into a bitmap and lets the string go. The 48-byte
record it keeps holds the owner, the size and the pixels, and that is all there
is to read. sfall has no hook for it either. So the bitmap is read back into
letters, with the game's own font.

That is a lookup, not OCR. The interface fonts are AAF bitmaps with no scaling:
a glyph is drawn as the same pixels every time, a fixed gap apart, bottom-
aligned on the line. Matching the ink against the font's own glyph masks
reproduces the string, in whatever alphabet the installed font was drawn for.

Measured on Torr, eleven times: two lines, 196 by 24, background 0, outline
228, ink in several shades of one colour (the AAF intensity levels).

**Except where two letters are drawn alike.** font1.aaf draws a and o with the
same pixels, and D and O, and I and l. Read on shape alone, Torr said "Bugs
dead. Maa-maas safe. Tarr thank-yau." A sighted player settles that from
context, and so does this: nearly every floating line is a line from one of the
game's .msg files, so the shapes are looked up among those and the line the
game actually holds is what gets said. A line built on the fly, which matches
nothing whole, is settled word by word by which spelling the game's text uses.

The .msg files are read from disk, not from memory. The engine's table of
script message lists (0x6649D4) was read live, standing beside Torr, and every
one of its 1450 slots was empty: script messages are loaded to be used and
freed again, so by the time a line could be checked against them they are gone.
"""

from __future__ import annotations

import configparser
import os
import re
import struct
import threading
import zlib
from collections import Counter
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

# The engine's list of live text objects: a count, and an array of pointers.
# Found in text_object_create, which appends with
#     mov [eax*4+006681BCh], esi   where eax is the count AFTER incrementing
# so the array itself starts one slot further on.
COUNT = 0x0051D944
ARRAY = 0x006681C0
MAX_OBJECTS = 20

# Fields of a text object, as text_object_create fills them in.
OFF_OWNER = 0x04
OFF_TIME = 0x08
OFF_LINES = 0x0C
OFF_WIDTH = 0x24
RECORD = 0x30

# A floating line is a sentence or two wrapped to a couple of hundred pixels.
# Anything larger is not a text object and is not read.
MAX_PIXELS = 200_000

# Font 101 is what float_msg and the combat taunts draw with; 103 is what
# FLOAT_MSG_WARNING draws with. Both are AAF fonts, numbered from 100.
FONT_FILES = {101: "font1.aaf", 103: "font3.aaf"}

# Which single-byte codepage each translation's text and fonts are drawn in.
from ..codepage import CODECS  # noqa: F401  (appearance imports it from here)


# -- the font ------------------------------------------------------------------

class Font:
    """An AAF font: a glyph mask per character, and the spacing it is set in."""

    def __init__(self, data: bytes, codec: str = "cp1252") -> None:
        if data[:4] != b"AAFF":
            raise ValueError("not an AAF font")
        self.codec = codec
        self.height, self.gap, self.space, self.vgap = struct.unpack(
            ">4H", data[4:12])
        base = 12 + 256 * 8
        # code -> (width, rows): rows bottom-aligned to the full font height,
        # stored as tuples of bools so that two glyphs compare by shape.
        self.glyphs: Dict[int, Tuple[int, Tuple[Tuple[bool, ...], ...]]] = {}
        for code in range(256):
            w, h, off = struct.unpack(">HHI", data[12 + code * 8:20 + code * 8])
            if w == 0 or h == 0 or h > self.height:
                continue
            pix = data[base + off:base + off + w * h]
            if len(pix) < w * h or not any(pix):
                continue
            rows = [tuple([False] * w) for _ in range(self.height - h)]
            rows += [tuple(pix[y * w + x] != 0 for x in range(w))
                     for y in range(h)]
            self.glyphs[code] = (w, tuple(rows))
        # Widest first, so a glyph whose shape is the left part of a wider one
        # never wins over it; among same-shaped glyphs, the likeliest letter.
        self._order = sorted(self.glyphs, key=lambda c: (-self.glyphs[c][0],
                                                         _rank(c)))
        # Every code, mapped to one representative of the codes drawn exactly
        # like it -- a and o both become a. Two strings with the same key are
        # indistinguishable on screen.
        first: Dict[tuple, int] = {}
        self._same: Dict[int, int] = {}
        for code in sorted(self.glyphs):
            self._same[code] = first.setdefault(self.glyphs[code], code)
        # The same mapping as a str.translate table, over every character this
        # codepage can hold: drawable ones to their representative, whitespace
        # to a space, and everything else -- control codes, characters the
        # font has no glyph for -- removed.
        self._table: Dict[int, Optional[str]] = {}
        for code in range(256):
            ch = self.char(code)
            if ch.isspace():
                self._table[ord(ch)] = " "
            elif code in self._same:
                self._table[ord(ch)] = chr(self._same[code])
            else:
                self._table[ord(ch)] = None

    @property
    def line_pitch(self) -> int:
        # What text_object_create steps down by: line height plus one.
        return self.height + self.vgap + 1

    def char(self, code: int) -> str:
        return bytes([code]).decode(self.codec, errors="replace")

    def key(self, text: str) -> str:
        """What `text` looks like in this font, as a string to look it up by.

        Whitespace of any kind and length is one space, because word wrap turns
        line breaks and runs of spaces into whatever it likes. A character the
        font cannot draw leaves no ink, so it leaves no trace here either.

        A translation table rather than a loop over characters: the whole of
        the game's text goes through here once, and per character in Python
        that took six seconds.
        """
        return " ".join(text.translate(self._table).split())

    def read_line(self, ink: List[List[bool]], top: int, width: int) -> str:
        """The characters set on one line of the bitmap, `top` its first row."""
        rows = [tuple(r) for r in ink[top:top + self.height]]
        if len(rows) < self.height:
            return ""
        cols = [any(r[x] for r in rows) for x in range(width)]
        out: List[str] = []
        x = 0
        blank = 0
        while x < width:
            if not cols[x]:
                blank += 1
                x += 1
                continue
            code = self._match(rows, x, width)
            if code is None:
                # Something the font does not draw. Skip the column rather than
                # invent a letter; the rest of the line still reads.
                x += 1
                blank = 0
                continue
            # Letters sit `gap` apart; a space is `space` wide on top of that.
            if out and blank >= self.space:
                out.append(" ")
            out.append(self.char(code))
            x += self.glyphs[code][0]
            blank = 0
        return "".join(out)

    def _match(self, rows, x: int, width: int) -> Optional[int]:
        for code in self._order:
            w, shape = self.glyphs[code]
            if x + w > width:
                continue
            if all(rows[y][x:x + w] == shape[y] for y in range(self.height)):
                return code
        return None


def _rank(code: int) -> int:
    """Which of several identically drawn glyphs to prefer, failing context."""
    ch = chr(code)
    if ch.islower():
        return 0
    if ch.isupper():
        return 1
    if ch.isdigit():
        return 2
    if code < 128:
        return 3
    return 4


def ink_mask(pixels: bytes, width: int, height: int) -> List[List[bool]]:
    """Which pixels are letter, rather than background or outline.

    The outline is one colour, drawn around the ink after the text, and the top
    row of an outlined bitmap holds nothing else -- the text starts a row down
    to leave it room. So the outline colour is read from there rather than
    assumed: a combat taunt's outline comes from the critter's AI packet.
    """
    counts = Counter(b for b in pixels[:width] if b)
    outline = counts.most_common(1)[0][0] if counts else None
    return [[pixels[y * width + x] not in (0, outline) for x in range(width)]
            for y in range(height)]


def decode(pixels: bytes, width: int, height: int, lines: int,
           font: Font) -> str:
    """The sentence a text object was drawn from, as far as shape can tell."""
    if width <= 0 or height <= 0 or len(pixels) < width * height:
        return ""
    ink = ink_mask(pixels, width, height)
    # An outlined object is two pixels taller than its lines and starts a row
    # down; one without an outline is exactly as tall as its lines.
    first = 1 if height >= lines * font.line_pitch + 2 else 0
    said = []
    for i in range(max(1, lines)):
        text = font.read_line(ink, first + i * font.line_pitch, width).strip()
        if text:
            said.append(text)
    return " ".join(said)


# -- the game's files -------------------------------------------------------------

def _dat_index(path: str) -> Dict[str, Tuple[bool, int, int]]:
    """name -> (compressed, packed size, offset) for a DAT2 archive."""
    out: Dict[str, Tuple[bool, int, int]] = {}
    with open(path, "rb") as f:
        f.seek(-8, 2)
        tree, size = struct.unpack("<II", f.read(8))
        f.seek(size - tree - 8)
        count = struct.unpack("<I", f.read(4))[0]
        for _ in range(count):
            n = struct.unpack("<I", f.read(4))[0]
            name = f.read(n).decode("latin-1").replace("/", "\\").lower()
            packed_flag, _unpacked, packed, offset = struct.unpack(
                "<BIII", f.read(13))
            out[name] = (bool(packed_flag), packed, offset)
    return out


class GameFiles:
    """The game's data, searched in the order the game searches it.

    Loose files in data\\ first, then the archives in mods\\mods_order.txt, then
    master.dat -- the order sfall documents in ddraw.ini, with the patch slots
    in between left out because nothing here is known to use them. Exact
    precedence among mods matters less than it sounds: what is read here is
    fonts and text, and two mods replacing the same line differently would have
    to differ only in letters the font draws alike to be confused.
    """

    def __init__(self, game_dir: str) -> None:
        self.game_dir = game_dir
        self.language = _language(game_dir)
        self.codec = CODECS.get(self.language, "cp1252")
        self._sources: List[Tuple[str, object]] = []
        loose = os.path.join(game_dir, "data")
        if os.path.isdir(loose):
            self._sources.append(("dir", loose))
        for mod in reversed(_mods_order(game_dir)):
            path = os.path.join(game_dir, "mods", mod)
            if os.path.isdir(path):
                self._sources.append(("dir", path))
            elif os.path.isfile(path):
                self._add_dat(path)
        self._add_dat(os.path.join(game_dir, "master.dat"))

    def _add_dat(self, path: str) -> None:
        try:
            self._sources.append(("dat", (path, _dat_index(path))))
        except (OSError, struct.error, UnicodeDecodeError):
            pass

    def read(self, name: str) -> Optional[bytes]:
        """One file, by its path inside the game's data ("fonts" optional)."""
        name = name.replace("/", "\\").lower()
        for kind, src in self._sources:
            data = self._read_from(kind, src, name)
            if data is not None:
                return data
        return None

    def _read_from(self, kind, src, name) -> Optional[bytes]:
        if kind == "dir":
            for rel in (name, os.path.join("fonts", name)):
                path = _find_ci(src, rel)
                if path:
                    try:
                        with open(path, "rb") as f:
                            return f.read()
                    except OSError:
                        return None
            return None
        path, index = src
        hit = index.get(name) or index.get("fonts\\" + name)
        return _dat_read(path, hit) if hit else None

    def texts(self) -> Iterator[bytes]:
        """Every .msg file under text\\<language>\\, each once, highest first."""
        prefix = "text\\{}\\".format(self.language)
        seen = set()
        for kind, src in self._sources:
            if kind == "dir":
                root = _find_ci(src, prefix.rstrip("\\"))
                if not root:
                    continue
                for folder, _dirs, files in os.walk(root):
                    for fn in files:
                        if not fn.lower().endswith(".msg"):
                            continue
                        full = os.path.join(folder, fn)
                        rel = (prefix + os.path.relpath(full, root)).lower()
                        if rel in seen:
                            continue
                        seen.add(rel)
                        try:
                            with open(full, "rb") as f:
                                yield f.read()
                        except OSError:
                            pass
                continue
            path, index = src
            for name, hit in index.items():
                if not name.startswith(prefix) or not name.endswith(".msg"):
                    continue
                if name in seen:
                    continue
                seen.add(name)
                data = _dat_read(path, hit)
                if data:
                    yield data


def load_font(files: GameFiles, number: int = 101) -> Optional[Font]:
    """The font the game draws floating text in, found the way the game finds it.

    A translation that swaps the font for its own alphabet has to be read with
    that font or every letter would come out wrong, so this goes through the
    same search order as everything else, mods first.
    """
    name = FONT_FILES.get(number)
    data = files.read(name) if name else None
    if not data:
        return None
    try:
        return Font(data, files.codec)
    except ValueError:
        return None


def _dat_read(path: str, hit) -> Optional[bytes]:
    packed_flag, packed, offset = hit
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            raw = f.read(packed)
        return zlib.decompress(raw) if packed_flag else raw
    except (OSError, zlib.error):
        return None


def _find_ci(root: str, rel: str) -> Optional[str]:
    """`rel` under `root`, matching each part without regard to case."""
    here = root
    for part in rel.replace("/", "\\").split("\\"):
        if not part:
            continue
        try:
            entries = os.listdir(here)
        except OSError:
            return None
        match = next((e for e in entries if e.lower() == part.lower()), None)
        if match is None:
            return None
        here = os.path.join(here, match)
    return here


def _language(game_dir: str) -> str:
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        cfg.read(os.path.join(game_dir, "fallout2.cfg"), encoding="latin-1")
        return cfg.get("system", "language", fallback="english").strip().lower()
    except (configparser.Error, OSError):
        return "english"


def _mods_order(game_dir: str) -> List[str]:
    path = os.path.join(game_dir, "mods", "mods_order.txt")
    try:
        with open(path, encoding="latin-1") as f:
            lines = [ln.strip() for ln in f]
    except OSError:
        return []
    return [ln for ln in lines if ln and ln[0] not in ";#"]


# -- what the game's text says -------------------------------------------------------

_MSG_ENTRY = re.compile(rb"\{(\d+)\}\{[^}]*\}\{([^}]*)\}", re.S)
_WORD = re.compile(r"\S+")


def msg_lines(data: bytes, codec: str) -> List[str]:
    """The text of every entry in one .msg file."""
    return [m.group(2).decode(codec, errors="replace")
            for m in _MSG_ENTRY.finditer(data)]


class Corpus:
    """Everything the game has to say, indexed by what it looks like."""

    def __init__(self, lines: Sequence[str], font: Font) -> None:
        self.whole: Dict[str, str] = {}
        self.words: Dict[str, Counter] = {}
        for text in lines:
            text = " ".join(text.split())
            if not text:
                continue
            self.whole.setdefault(font.key(text), text)
            for word in _WORD.findall(text):
                self.words.setdefault(font.key(word), Counter())[word] += 1

    def resolve(self, shape: str, font: Font) -> str:
        """The real text behind a string decoded on shape alone."""
        whole = self.whole.get(font.key(shape))
        if whole is not None:
            return whole
        out = []
        for word in shape.split(" "):
            seen = self.words.get(font.key(word))
            out.append(seen.most_common(1)[0][0] if seen else word)
        return " ".join(out)


# -- reading it out of the game -------------------------------------------------------

def live_objects(proc) -> Sequence[int]:
    count = proc.read_i32(COUNT)
    if not count or not (0 < count <= MAX_OBJECTS):
        return ()
    blob = proc.read_chunked(ARRAY, 4 * count)
    if not blob or len(blob) < 4 * count:
        return ()
    return struct.unpack("<%dI" % count, blob)


class FloatReader:
    """Turns a WORLD:float line from the script into the sentence it was.

    The font and the text index come from disk and take a moment, so they are
    built on a thread the first time this is made. A line that arrives before
    they are ready is read on shape alone -- right apart from the letters the
    font draws alike -- rather than held back or dropped.
    """

    def __init__(self, proc, game_dir: str) -> None:
        self.proc = proc
        self.game_dir = game_dir
        self.font: Optional[Font] = None
        self.corpus: Optional[Corpus] = None
        self._ready = threading.Event()
        threading.Thread(target=self._load, daemon=True,
                         name="floattext").start()

    def _load(self) -> None:
        try:
            files = GameFiles(self.game_dir)
            self.font = load_font(files, 101)
            if self.font is not None:
                lines: List[str] = []
                for data in files.texts():
                    lines.extend(msg_lines(data, files.codec))
                self.corpus = Corpus(lines, self.font)
        except Exception as exc:  # never let this take the mod down
            print("[floattext] could not load: {}".format(exc), flush=True)
        finally:
            self._ready.set()

    def read(self, ptr: int, created: int) -> Optional[str]:
        """The sentence on the text object at `ptr`, or None.

        `created` is the creation time the script logged. The pointer came
        from a log line written a moment ago, and the record is checked against
        both before anything is read: a text object that has expired since is
        freed memory, and the next one is often allocated at the same address.
        """
        self._ready.wait(timeout=0.5)
        font = self.font
        if font is None or ptr not in live_objects(self.proc):
            return None
        raw = self.proc.read(ptr, RECORD)
        if not raw or len(raw) < RECORD:
            return None
        _owner, when, lines = struct.unpack_from("<Iii", raw, OFF_OWNER)
        width, height, data = struct.unpack_from("<iiI", raw, OFF_WIDTH)
        if when != created:
            return None
        if not (0 < width * height <= MAX_PIXELS) or not (0 < lines < 20):
            return None
        pixels = self.proc.read_chunked(data, width * height)
        if not pixels or len(pixels) < width * height:
            return None
        shape = decode(pixels, width, height, lines, font)
        if not shape:
            return None
        return self.corpus.resolve(shape, font) if self.corpus else shape


def float_line(line: str) -> Optional[Tuple[int, int, bool, str]]:
    """Parse WORLD:float <ptr>|<created>|<is you>|<owner name>|."""
    body = line[len("WORLD:float"):].strip()
    parts = body.split("|")
    if len(parts) < 4:
        return None
    try:
        ptr = int(parts[0]) & 0xFFFFFFFF
        created = int(parts[1])
    except ValueError:
        return None
    return ptr, created, parts[2].strip() == "1", parts[3].strip()
