"""Which screen is showing.

Without this the mod cannot tell character selection from the editor: the
editor's selection index and SPECIAL array both still read plausibly on the
selection screen (the array holds the premade's stats), so a content-based
guess says "character creation" and narrates the wrong thing entirely.

Three globals, and the order they are tested in matters.

    screen              0x006ADDA8   0x00519504   0x00518490
    character editor        >= 0          0            0
    main menu                -1           1            1
    character selection      -1           0            1

The editor is identified *positively*, by its window handle being live, rather
than by "neither of the other two flags is set". That distinction was a real
bug: sampling at 50Hz through a transition shows the flag pair flapping
(0,0) -> (0,1) -> (0,0) -> (1,1) across a single screen change, so a fallback
"must be the editor then" fired a spurious "Character creation" every time the
player moved between screens. The window handle goes 6 -> -1 cleanly with no
intermediate states.

Anything unrecognised reports UNKNOWN, and an unknown screen stays silent.
Guessing is worse than saying nothing: a wrong announcement actively misleads
someone who cannot check it against the screen.
"""

from __future__ import annotations

from typing import Optional

from ..memory.process import Process

EDITOR_WINDOW = 0x006ADDA8  # >= 0 only while the character editor window exists
MENU_FLAG = 0x00519504      # 1 on the main menu
EDITOR_FLAG = 0x00518490    # 0 in the character editor

MAIN_MENU = "main_menu"
SELECT = "select"
CHARGEN = "chargen"
WORLD = "world"
UNKNOWN = "unknown"

# Sub-modes reported by the in-game script's get_game_mode bitmask.
MODE_WORLDMAP = 0x1
MODE_DIALOG = 0x4
MODE_COMBAT = 0x40
MODE_CHARSCREEN = 0x200
MODE_PIPBOY = 0x400
MODE_INVENTORY = 0x1000
MODE_SKILLDEX = 0x4000
MODE_BARTER = 0x20000

MODE_NAMES = [
    (MODE_DIALOG, "dialogue"),
    (MODE_BARTER, "barter"),
    (MODE_INVENTORY, "inventory"),
    (MODE_PIPBOY, "pipboy"),
    (MODE_SKILLDEX, "skilldex"),
    (MODE_CHARSCREEN, "character screen"),
    (MODE_WORLDMAP, "world map"),
    (MODE_COMBAT, "combat"),
]


# get_game_mode returns a BITMASK, and several bits can be set at once. These
# three do not hide the map, so hexes still mean something while they are set.
MODE_LOCALMAP = 0x2
MODE_PCOMBAT = 0x800  # player's own combat; set alongside COMBAT, not instead
MAP_MODES = MODE_LOCALMAP | MODE_COMBAT | MODE_PCOMBAT


def is_map_mode(mode: Optional[int]) -> bool:
    """True where the world exists in hexes, so aiming at one is meaningful.

    Tested as a MASK, and that detail has now cost three separate debugging
    sessions. The first version asked `mode == 0`, which excluded combat and so
    silently stopped the click from aiming during every fight. The second asked
    `mode in (0, MODE_COMBAT)`, which looked right and was not: in the player's
    own turn the engine reports 0x840, COMBAT *and* PCOMBAT together, so
    equality against a single value fails just as completely. The symptom both
    times was a click landing wherever the pointer had last been left, which
    reads as the character walking off in a direction nobody chose.

    So: anything outside the known-harmless set counts as a panel over the view,
    including bits we have never seen. Failing that way round is the safe one --
    an unrecognised mode means we decline to aim, rather than aiming into a
    dialogue box.
    """
    if mode is None:
        return False
    return (mode & ~MAP_MODES) == 0


def mode_name(mode: Optional[int]) -> str:
    """Human name for a get_game_mode bitmask. 0 means the normal map view."""
    if mode is None:
        return "unknown"
    if mode == 0:
        return "exploring"
    names = [name for bit, name in MODE_NAMES if mode & bit]
    return ", ".join(names) if names else "mode {}".format(mode)


# Cursor modes reported by the script's get_cursor_mode. These decide what a
# left click does, which is information a sighted player reads off the cursor
# art at a glance and a blind player otherwise has no access to at all.
#
# Only 0, 1 and 2 are named here, because only those three are actually known.
# sfall's docs say modes 4-10 are Skilldex skill cursors, and this file used to
# announce them that way -- wrongly. Live logs show the value tracking the
# DIRECTION the view was just scrolled (W gives 8, E gives 5, SE 7, NW 9), which
# is nothing to do with skills; they are almost certainly the engine's
# directional map-scroll cursors. "Almost certainly" is not good enough to put
# a name to, so an unknown mode is reported as a number plus the one thing that
# is definitely true about it: it is not the movement cursor, and there is a key
# that fixes that.
CURSOR_MOVEMENT = 0
CURSOR_COMMAND = 1
CURSOR_TARGETING = 2

CURSOR_NAMES = {
    CURSOR_MOVEMENT: "movement cursor. A click walks you there",
    CURSOR_COMMAND: "command cursor. A click interacts instead of walking",
    CURSOR_TARGETING: "targeting cursor. A click attacks",
}


def cursor_name(mode: Optional[int]) -> Optional[str]:
    """What a left click will do right now, or None if we cannot say."""
    if mode is None:
        return None
    if mode in CURSOR_NAMES:
        return CURSOR_NAMES[mode]
    return (
        "cursor mode {}. Not the movement cursor. Press numpad 0 to "
        "walk".format(mode)
    )


def detect(proc: Process, in_game: bool = False) -> str:
    """Which screen is showing.

    `in_game` comes from the in-game script having reported a game mode. It
    takes priority because memory alone cannot distinguish a loaded game from
    the premade-character screen -- both leave the same flags set, which had
    the mod cheerfully announcing "character selection" while the player was
    standing on a map. The script only runs inside a live session, so its word
    is decisive.
    """
    if in_game:
        # The character editor is reachable mid-game (the F1 screen), so still
        # let a live editor window win.
        window = proc.read_i32(EDITOR_WINDOW)
        if window is not None and window >= 0:
            return CHARGEN
        return WORLD
    return _detect_pregame(proc)


def _detect_pregame(proc: Process) -> str:
    # Positive test first: the editor's window handle is unambiguous and does
    # not flicker, unlike the flag pair below.
    window = proc.read_i32(EDITOR_WINDOW)
    if window is not None and window >= 0:
        return CHARGEN

    menu = proc.read_i32(MENU_FLAG)
    editor = proc.read_i32(EDITOR_FLAG)
    if menu is None or editor is None:
        return UNKNOWN
    if menu == 1:
        return MAIN_MENU
    if editor == 1:
        return SELECT
    # Mid-transition the flags briefly agree on nothing meaningful. Say so
    # rather than picking a screen.
    return UNKNOWN


# -- safe navigation for the dev tools ---------------------------------------
#
# Sending a key without first checking the screen has cost two game sessions.
# Escape means "back" in the editor but "quit" at the main menu; N means "new
# game" at the menu but "edit name" in the editor, which opens a text field
# that silently swallows every following keystroke.
#
# So tools must never assume a starting screen. Navigate through this table,
# which only ever presses a key whose meaning on the *currently detected*
# screen is known.

class WrongScreen(RuntimeError):
    """The game is not on the screen an operation requires."""


SAFE_MOVES = {
    (MAIN_MENU, SELECT): "n",
    (SELECT, CHARGEN): "c",
    (CHARGEN, SELECT): "escape",
    (SELECT, MAIN_MENU): "b",
}

# Shortest safe route between any two screens.
_ROUTES = {
    (MAIN_MENU, CHARGEN): [SELECT, CHARGEN],
    (CHARGEN, MAIN_MENU): [SELECT, MAIN_MENU],
}


def require(proc: Process, expected: str) -> None:
    """Raise unless the game is on `expected` right now."""
    actual = detect(proc)
    if actual != expected:
        raise WrongScreen(
            "expected to be on {!r} but the game is on {!r}; refusing to send "
            "keys, since the same key means different things on different "
            "screens".format(expected, actual)
        )


def navigate(proc: Process, hwnd: int, target: str, settle: float = 1.6) -> bool:
    """Walk to `target` using only known-safe transitions.

    Returns False rather than guessing if the current screen is unrecognised.
    """
    from ..input.send import guarded_tap  # local import: avoids a cycle

    for _ in range(6):
        current = detect(proc)
        if current == target:
            return True
        if current == UNKNOWN:
            return False
        hops = _ROUTES.get((current, target), [target])
        key = SAFE_MOVES.get((current, hops[0]))
        if key is None:
            return False
        guarded_tap(hwnd, key, settle=settle)
    return detect(proc) == target
