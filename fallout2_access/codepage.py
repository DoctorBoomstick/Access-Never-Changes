"""Which single-byte codepage the game's text is in.

The engine has no Unicode. A translation is drawn in whatever codepage its
fonts were made for, and every byte of the game's text -- in memory, in save
headers, in what the scripts write to debug.log -- is in that codepage too.
Read as Western European, Russian arrives as "Íîæ" and, read as UTF-8, as
nothing but replacement marks.

`set_language` is called once the game's folder is known; until then, and for
any language not listed, the text is Western European, which is what the game
shipped in.
"""

from __future__ import annotations

from typing import Optional

WESTERN = "cp1252"

CODECS = {
    "russian": "cp1251",
    "polish": "cp1250",
    "czech": "cp1250",
    "hungarian": "cp1250",
}

_codec = WESTERN


def for_language(language: str) -> str:
    return CODECS.get((language or "").strip().lower(), WESTERN)


def set_language(language: str) -> str:
    """Decode the game's text as `language` is written. Returns the codec."""
    global _codec
    _codec = for_language(language)
    return _codec


def game() -> str:
    """The codec the running game's text is in."""
    return _codec


def text_char(c: str, letters: Optional[bool] = None) -> bool:
    """Printable ASCII, or a letter of the game's alphabet.

    Letters above 127 count when `letters` says so, and by default only in a
    game whose codepage is not Western: there a real line is nearly all of
    them, while in a Western game a run of high bytes is what noise looks like.
    """
    if 32 <= ord(c) < 127:
        return True
    if letters is None:
        letters = _codec != WESTERN
    return letters and c.isalpha()
