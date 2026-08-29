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

# **These are absolute into fallout2.exe, and they do not survive a patched one.**
#
# The values below are the retail Steam build. Measured against the Restoration
# Project Unofficial, which rewrites the executable in place -- same 1,189,888
# bytes, a different SHA256 -- the editor's window handle sat eight bytes lower:
#
#     0x006ADDA8   retail Steam
#     0x006ADDA0   under RPU, found by watching it flip sign across four
#                  editor open/closes, which is the only test that separates a
#                  handle from a number that happens to be positive
#
# Recorded rather than adopted. RPU is not the build this mod is developed
# against, and hardcoding its address would only move the breakage to the other
# build.
#
# **The failure was silent, which is the part worth remembering.** Every read
# still succeeded and returned -1 -- the value meaning "no editor open" -- so
# the mod concluded there was nothing to describe and said nothing at all.
# Character creation was mute on a screen it reads perfectly well. Only the
# pre-game screens depend on these: once a game is loaded the screen comes from
# the script's own game mode, so a patched executable leaves play working and
# breaks only the menu, selection and the editor.
#
# An eight-byte shift also moves the neighbours. uiwindow.py's WINDOW_LIST and
# WINDOW_COUNT sit just above this address and would have gone with it, while
# pointer.py's sit below and would not -- which matches what was observed:
# pointing worked, finding a panel to click in did not.
#
# The durable answer is memory/scan.py, which was written for exactly this and
# is still wired to nothing. Signature the instruction that READS the variable
# and the variable may move where it likes.
EDITOR_WINDOW = 0x006ADDA8  # >= 0 only while the character editor window exists
MENU_FLAG = 0x00519504      # 1 on the main menu
EDITOR_FLAG = 0x00518490    # 0 in the character editor

MAIN_MENU = "main_menu"
SELECT = "select"
CHARGEN = "chargen"
WORLD = "world"          # a loaded map, walked in hexes
SLOTS = "slots"          # the save or load screen
TIMER = "timer"          # the explosive countdown
PIPBOY = "pipboy"        # the Pip-Boy 2000
WORLDMAP = "worldmap"    # travelling between places, in subtiles
UNKNOWN = "unknown"

# Sub-modes reported by the in-game script's get_game_mode bitmask, from
# sfall.h. Every one of these is worth naming: an unnamed mode is announced as a
# bare number, and "mode 8" told a player nothing while the escape menu sat open
# over their game and quietly swallowed every click.
MODE_WORLDMAP = 0x1
MODE_LOCALMAP = 0x2
MODE_DIALOG = 0x4
MODE_ESCMENU = 0x8
MODE_SAVEGAME = 0x10
MODE_LOADGAME = 0x20
MODE_COMBAT = 0x40
MODE_OPTIONS = 0x80
MODE_HELP = 0x100
MODE_CHARSCREEN = 0x200
MODE_PIPBOY = 0x400
MODE_PCOMBAT = 0x800   # the player's own combat; set alongside COMBAT
MODE_INVENTORY = 0x1000
MODE_AUTOMAP = 0x2000
MODE_SKILLDEX = 0x4000
MODE_INTFACEUSE = 0x8000
MODE_INTFACELOOT = 0x10000
MODE_BARTER = 0x20000
MODE_HEROWIN = 0x40000
MODE_DIALOGVIEW = 0x80000
MODE_COUNTERWIN = 0x100000
MODE_PAUSEWIN = 0x200000

# Order matters only in that the most informative name should come first when
# several bits are set. LOCALMAP and PCOMBAT are absent on purpose: the first
# means "on a map", which is the ordinary state, and the second only ever
# accompanies COMBAT and would say it twice.
MODE_NAMES = [
    (MODE_DIALOG, "dialogue"),
    (MODE_BARTER, "barter"),
    (MODE_INVENTORY, "inventory"),
    (MODE_INTFACELOOT, "loot"),
    (MODE_INTFACEUSE, "use item on"),
    (MODE_PIPBOY, "pipboy"),
    (MODE_SKILLDEX, "skilldex"),
    (MODE_CHARSCREEN, "character screen"),
    (MODE_AUTOMAP, "automap"),
    (MODE_WORLDMAP, "world map"),
    (MODE_ESCMENU, "escape menu"),
    (MODE_SAVEGAME, "save game"),
    (MODE_LOADGAME, "load game"),
    (MODE_OPTIONS, "options"),
    (MODE_HELP, "help"),
    (MODE_HEROWIN, "party member screen"),
    (MODE_DIALOGVIEW, "dialogue"),
    (MODE_COUNTERWIN, "quantity"),
    (MODE_PAUSEWIN, "paused"),
    (MODE_COMBAT, "combat"),
]


# Several bits can be set at once, and these three do not hide the map, so
# hexes still mean something while they are set.
MAP_MODES = MODE_LOCALMAP | MODE_COMBAT | MODE_PCOMBAT

# The four windows that are one window wearing different hats: sfall gives them
# a single WINTYPE_INVENTORY, they share a layout, and gl_inven.ssl claims the
# keyboard for all of them. Kept together because anything that learns to point
# at a slot in one of them can point at a slot in all four.
ITEM_WINDOW_MODES = (
    MODE_INVENTORY | MODE_INTFACELOOT | MODE_INTFACEUSE | MODE_BARTER
)


def is_item_window(mode: Optional[int]) -> bool:
    """True in the inventory, loot, use-item or barter window."""
    if mode is None:
        return False
    return bool(mode & ITEM_WINDOW_MODES)


# A conversation, and the review screen that shows one's history. Both are
# panels over the map, like the loot window -- not screens of their own. That
# matters structurally: only the active screen's watcher is polled, so making
# dialogue its own screen would leave every combat and inventory line the
# scripts emit sitting unspoken in a queue for as long as the player was
# talking to somebody.
DIALOGUE_MODES = MODE_DIALOG | MODE_DIALOGVIEW


def is_dialogue(mode: Optional[int]) -> bool:
    """True while a conversation is on screen."""
    if mode is None:
        return False
    return bool(mode & DIALOGUE_MODES)


SAVE_SCREEN_MODES = MODE_SAVEGAME | MODE_LOADGAME


def is_save_screen(mode: Optional[int]) -> bool:
    """True on the save or load screen, where the slot list is the question."""
    if mode is None:
        return False
    return bool(mode & SAVE_SCREEN_MODES)


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
    """Human name for a get_game_mode bitmask."""
    if mode is None:
        return "unknown"
    names = [name for bit, name in MODE_NAMES if mode & bit]
    # No panel bits set means the plain map view, whether or not LOCALMAP is on.
    return ", ".join(names) if names else "exploring"


# Cursor modes reported by the script's get_cursor_mode. This decides what a
# left click does, which is something a sighted player reads off the cursor's
# shape without thinking about it.
#
# The skill numbering was measured by arming each Skilldex key in turn against
# the live game, not taken from documentation. Note the gap where Sneak would
# be: Sneak is a toggle rather than something you aim, so it has no cursor of
# its own and the enum skips it.
CURSOR_MOVEMENT = 0
CURSOR_COMMAND = 1
CURSOR_TARGETING = 2
# Mode 3 had no name, and its silence is what made pressing U look like a dead
# key. Clicking the interface bar's item slot does not use the item -- it arms
# it and switches to this cursor, waiting to be told what to use it on. The mod
# said "Using Healing Powder", the engine said mode 3, nothing named mode 3, and
# the player was left holding an armed item with no way to know it.
#
# Its place in the enum is what identifies it: 4 through 10 are the skill
# cursors, measured one at a time off the Skilldex, and 3 sits immediately below
# First Aid where fallout2-ce puts USE_CROSSHAIR.
CURSOR_USE_ITEM = 3

CURSOR_NAMES = {
    CURSOR_MOVEMENT: "movement cursor. A click walks you there",
    CURSOR_COMMAND: "command cursor. A click interacts instead of walking",
    CURSOR_TARGETING: "targeting cursor. A click attacks",
    CURSOR_USE_ITEM: "item ready. A click uses it on what you point at",
}

# mode -> the skill a click will apply.
SKILL_CURSORS = {
    4: "First Aid",
    5: "Doctor",
    6: "Lockpick",
    7: "Steal",
    8: "Traps",
    9: "Science",
    10: "Repair",
}


def armed_skill(mode: Optional[int]) -> Optional[str]:
    """The skill a click would use, or None if the cursor is not holding one."""
    if mode is None:
        return None
    return SKILL_CURSORS.get(mode)


def cursor_name(mode: Optional[int]) -> Optional[str]:
    """What a left click will do right now, or None if we cannot say."""
    if mode is None:
        return None
    if mode in CURSOR_NAMES:
        return CURSOR_NAMES[mode]
    skill = SKILL_CURSORS.get(mode)
    if skill:
        return "{} ready. A click uses it".format(skill)
    # Never seen one outside 0-10, but an unknown mode gets a number and the
    # one thing that is definitely true, rather than a confident guess.
    return "cursor mode {}. Not the movement cursor. Press numpad 0 to walk".format(mode)


def detect(proc: Process, in_game: bool = False,
           mode: Optional[int] = None) -> str:
    """Which screen is showing.

    `in_game` comes from the in-game script having reported a game mode. It
    takes priority because memory alone cannot distinguish a loaded game from
    the premade-character screen -- both leave the same flags set, which had
    the mod cheerfully announcing "character selection" while the player was
    standing on a map. The script only runs inside a live session, so its word
    is decisive.

    `mode` is that game mode, and once a game is live it settles the question
    outright. The editor's window handle used to be consulted here instead, and
    it lies: opening the inventory sometimes left it reading as a live editor,
    so the mod announced "Character creation. Strength, 4." over a player who
    had just opened their pack. Window handles are recycled and the flag is
    stale between uses; the game mode is a direct statement of what is on
    screen, and the mod already has it.
    """
    # The save and load screens first, and from their own window rather than
    # from the game mode. They are reachable from the main menu, where no script
    # runs and therefore no game mode exists -- so the one detector that works
    # in both places is the one that does not depend on a script being alive.
    #
    # Testing it first makes this the most dangerous read in the file: a sensor
    # that says yes when it should say no does not merely mis-name one screen,
    # it hides every other screen behind it. That is precisely what happened
    # with the flag this used to read, which never went back to zero once the
    # save screen had been opened -- so the mod answered "load game" to the map,
    # to character selection, to all of it. A window that is actually open is a
    # fact; a flag somebody set is a promise.
    from . import slotscreen, timerwin  # local imports: avoid a cycle

    # The countdown first. It is a small window drawn over the map, so every
    # other detector still reports the map underneath it -- and a charge whose
    # timer is being set is the last thing that should be narrated as scenery.
    if timerwin.showing(proc):
        return TIMER

    if slotscreen.showing(proc):
        return SLOTS

    if in_game:
        if mode is not None:
            # The Pip-Boy before the character screen. Both are bits in the
            # mask and neither is ever set with the other, so the order is only
            # a statement of which question is asked first -- but it matters
            # that this is asked from the mode at all rather than from the
            # panel's window. The Pip-Boy is a 640x480 panel like the character
            # sheet and the save screen, and the engine saying PIPBOY is a
            # direct statement where a window shape is an inference.
            if mode & MODE_PIPBOY:
                return PIPBOY
            # The character screen mid-game is a bit in the mask, and nothing
            # else in a live session is the editor.
            if mode & MODE_CHARSCREEN:
                return CHARGEN
            # The world map is a screen of its own, which is a departure from
            # how dialogue and the loot window are handled. Those are panels
            # over a live map, and giving them their own screen would leave the
            # scripts' combat and inventory lines queued unspoken behind them.
            # The world map is not a panel: no map is loaded, so gl_world,
            # gl_combat and gl_inven have nothing to report while it is up, and
            # there is no queue to strand. It also genuinely is a different
            # place -- hexes do not exist here and subtiles do -- so the keys
            # mean different things and a separate watcher is the honest way to
            # say so.
            if mode & MODE_WORLDMAP:
                return WORLDMAP
            return WORLD
        # No mode reported yet. Fall back to the window handle, which is better
        # than nothing at the very start of a session.
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
