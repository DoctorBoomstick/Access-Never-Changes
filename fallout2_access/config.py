"""The player's settings, from access.ini beside the program.

Every setting has a default here, so a missing file, a missing line or a value
that makes no sense all mean the same thing: the default. A settings file is
the one thing in the mod a player edits by hand, and a typo in it must not be
the reason the mod says nothing. What was wrong goes to the log.

Command-line switches still work, and win over the file.
"""

from __future__ import annotations

import configparser
from typing import List, NamedTuple, Optional

from . import paths

SPEECH_BACKENDS = ("auto", "nvda", "accessible_output2", "sapi")

_TRUE = {"1", "yes", "true", "on"}
_FALSE = {"0", "no", "false", "off"}


class Settings(NamedTuple):
    speech: str = "auto"
    language: str = "auto"
    speak_without_focus: bool = False
    step_sound: bool = True
    hotkeys: bool = True
    game_folder: str = ""
    exit_with_game: bool = False


def defaults() -> Settings:
    # Installed, the mod is started by a shortcut and has no window to close,
    # so it goes when the game goes. From the repo it waits for the next run,
    # which is what a developer restarting the game over and over wants.
    return Settings(exit_with_game=paths.frozen())


def load(path: Optional[str] = None, problems: Optional[List[str]] = None) -> Settings:
    """Read the file at `path` (access.ini beside the program by default)."""
    path = path or paths.config_path()
    problems = problems if problems is not None else []
    base = defaults()
    cfg = configparser.ConfigParser(interpolation=None,
                                    inline_comment_prefixes=(";", "#"))
    try:
        with open(path, encoding="utf-8-sig") as fh:
            cfg.read_file(fh)
    except FileNotFoundError:
        return base
    except (OSError, configparser.Error, UnicodeDecodeError) as exc:
        problems.append("{}: {}".format(path, exc))
        return base

    def text(section: str, key: str, default: str) -> str:
        return cfg.get(section, key, fallback=default).strip()

    def flag(section: str, key: str, default: bool) -> bool:
        raw = text(section, key, "").lower()
        if not raw:
            return default
        if raw in _TRUE:
            return True
        if raw in _FALSE:
            return False
        problems.append("[{}] {} = {}: not yes or no, using {}".format(
            section, key, raw, "yes" if default else "no"))
        return default

    speech = text("speech", "backend", base.speech).lower() or base.speech
    if speech not in SPEECH_BACKENDS:
        problems.append("[speech] backend = {}: not one of {}, using auto".format(
            speech, ", ".join(SPEECH_BACKENDS)))
        speech = "auto"

    return Settings(
        speech=speech,
        language=text("general", "language", base.language).lower() or "auto",
        speak_without_focus=flag("general", "speak_without_focus",
                                 base.speak_without_focus),
        step_sound=flag("general", "step_sound", base.step_sound),
        hotkeys=flag("general", "hotkeys", base.hotkeys),
        game_folder=text("game", "folder", base.game_folder).strip('"'),
        exit_with_game=flag("game", "exit_with_game", base.exit_with_game),
    )
