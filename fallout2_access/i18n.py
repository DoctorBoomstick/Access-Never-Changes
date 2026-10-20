"""The mod's own words, and the files that translate them.

Only the words the MOD makes up are here. Everything the game itself says --
item names, dialogue, skill names, the character editor's labels -- is read out
of the game's own text and is already in whatever language the game is in.

In the code, every one of the mod's sentences is written where it is used, in
English, with a key:

    tr("chargen.points_left", "{points} points left", points=3)

The English in the code is the last word: a translation that lacks a line, a
file that will not open, a translator's typo in a blank -- each of those says
the English rather than nothing. Silence is this project's worst failure, and
a translation is not allowed to cause it.

A language file, lang\\<language>.ini, is UTF-8 and looks like this:

    [chargen]
    points_left = Noch {points} Punkte

`[chargen]` and `points_left` together are the key. Words in braces are filled
in by the mod and must be kept, spelt as they are, but may move anywhere in the
line. lang\\english.ini is made from the code by tools/mklang.py and is the
file to copy when starting a translation.
"""

from __future__ import annotations

import configparser
import os
import re
from typing import Dict, List, Optional

from . import paths

FALLBACK = "english"

_strings: Dict[str, str] = {}
_language = FALLBACK

# The in-game scripts' English, phrase -> key. See `say_script`.
_script_keys: Dict[str, str] = {}


def load_file(path: str, problems: Optional[List[str]] = None) -> Dict[str, str]:
    cfg = configparser.ConfigParser(interpolation=None, delimiters=("=",),
                                    comment_prefixes=(";", "#"),
                                    inline_comment_prefixes=None,
                                    strict=False)
    cfg.optionxform = str  # keys keep their case
    try:
        with open(path, encoding="utf-8-sig") as fh:
            cfg.read_file(fh)
    except FileNotFoundError:
        return {}
    except (OSError, configparser.Error, UnicodeDecodeError) as exc:
        if problems is not None:
            problems.append("{}: {}".format(path, exc))
        return {}
    out: Dict[str, str] = {}
    for section in cfg.sections():
        for key, value in cfg.items(section):
            value = value.strip()
            if value:
                out["{}.{}".format(section, key)] = value
    return out


def game_language(game_dir: Optional[str]) -> str:
    """The game's own language setting, as fallout2.cfg spells it."""
    if not game_dir:
        return FALLBACK
    from .game.floattext import _language

    return _language(game_dir) or FALLBACK


def choose(setting: str, game_dir: Optional[str]) -> str:
    setting = (setting or "auto").strip().lower()
    return game_language(game_dir) if setting == "auto" else setting


def init(language: str = FALLBACK, folder: Optional[str] = None,
         problems: Optional[List[str]] = None) -> str:
    """Speak from lang\\<language>.ini. Returns the language in use.

    English needs no file -- it is in the code -- but english.ini is read like
    any other if it is there, so a player can reword a line without a build.
    """
    global _strings, _language
    folder = folder or paths.lang_dir()
    language = (language or FALLBACK).strip().lower()
    path = os.path.join(folder, language + ".ini")
    _strings = {}
    _language = FALLBACK
    if os.path.exists(path):
        _strings = load_file(path, problems)
        _language = language
    elif language != FALLBACK and problems is not None:
        problems.append("no {} in {}; speaking English".format(
            language + ".ini", folder))
    return _language


def language() -> str:
    return _language


def tr(key: str, english: str, /, **fields: object) -> str:
    """`english`, or its translation, with the blanks filled in."""
    template = _strings.get(key, english)
    if not fields:
        return template
    try:
        return template.format(**fields)
    except (KeyError, IndexError, ValueError):
        # A translation with a misspelt blank says the English instead of
        # half a sentence, or nothing.
        if template is not english:
            try:
                return english.format(**fields)
            except (KeyError, IndexError, ValueError):
                pass
        return english


def slug(english: str) -> str:
    """A key made from the English itself: "Up and Down" -> "up_and_down".

    For text that lives in tables -- the F1 key lists -- where giving each of
    ninety entries a key by hand would only be a second copy of the words.
    tools/mklang.py makes the same keys from the same tables.
    """
    return re.sub(r"[^a-z0-9]+", "_", english.lower()).strip("_")[:60] or "blank"


def tr_text(section: str, english: str) -> str:
    """`english` from a table, translated under a key made from itself."""
    return tr("{}.{}".format(section, slug(english)), english)


def script_words(table: Dict[str, str]) -> None:
    """Register phrases the in-game scripts send, as {key: English}."""
    for key, english in table.items():
        _script_keys[english] = key


def say_script(text: str) -> str:
    """A phrase from an in-game script, in the player's language.

    The scripts cannot read these files -- they run inside the game, in a
    language with no dictionaries and no UTF-8 -- and the Python side parses
    some of what they send ("empty", "you", "locked" each mean something to the
    hex readout). So they go on writing English, which stays the protocol all
    the way through, and a phrase is translated only here, on its way out to be
    spoken. Anything that is not a known phrase -- an object's name, which is
    the game's own and already in the game's language -- passes through.
    """
    key = _script_keys.get(text)
    return tr(key, text) if key else text


def say_script_fields(text: str) -> str:
    """`say_script` for each comma-separated field of a readout."""
    if not _script_keys:
        return text
    return ", ".join(say_script(f.strip()) for f in text.split(","))
