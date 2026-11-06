"""The mod's own keys, from keys.ini beside the program.

Two halves of the mod listen to the keyboard. The Python side hears Windows
virtual keys, through pynput, and never takes a key from the game. The scripts
inside the game hear DirectInput scancodes, through sfall's keypress hook, and
swallow what they act on. A key the player moves has to move in both, so this
file is the one place a key is named: it reads keys.ini, checks it, hands the
Python side its virtual keys, and writes the scancodes out to a small file the
scripts read when they start (`SCRIPT_KEYS`).

The file names keys the way F1 says them -- "Numpad 7", "Right bracket",
"Control+Slash" -- because the settings file's own comment character is a
semicolon, and a key spelled `;` would be read as a comment and lost.

**Not every key can move.** The arrows, Enter, Escape, Backspace, Tab, Home and
End are the grammar every screen keeps (controls.py), and the game's own keys
besides; the number row arms skills and says replies. Apostrophe, backslash and
numpad 0 are the mod talking to its own scripts -- the Python side presses them
to find the pointer and to ask for totals -- and a player who took one would
break the thing that presses it. Those are `FIXED`, and binding one is a
mistake the log names.

A mistake costs only the action it is on. A key nobody knows, a fixed key, or
two actions on one key: each action involved keeps its default, and the log says
why. A settings file is edited by hand, and a typo in it must not be the reason
the mod falls silent.
"""

from __future__ import annotations

import configparser
import os
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

from . import paths

KEYS_NAME = "keys.ini"

# Where the scripts look, relative to the game folder: sfall's get_ini_setting
# takes nothing else. Inside the mod's own folder, which ordinary users can
# write to, and the same path whether the mod runs installed or from the repo.
SCRIPT_KEYS_DIR = "Access Never Changes"
SCRIPT_KEYS_NAME = "script_keys.ini"
SCRIPT_KEYS = SCRIPT_KEYS_DIR + "/" + SCRIPT_KEYS_NAME

# How a modifier rides along with a scancode in SCRIPT_KEYS. The scripts add
# the same bits to the key they were handed and compare one number.
SCRIPT_SHIFT = 256
SCRIPT_CTRL = 512


class Key(NamedTuple):
    name: str           # as F1 says it, and as keys.ini spells it
    vk: int             # Windows virtual key
    dik: int            # DirectInput scancode, as sfall hands it to a script
    aliases: Tuple[int, ...] = ()   # other virtual keys the same key sends


def _table() -> Dict[str, Key]:
    keys: List[Key] = []
    for i, ch in enumerate("QWERTYUIOP"):
        keys.append(Key(ch, ord(ch), 0x10 + i))
    for i, ch in enumerate("ASDFGHJKL"):
        keys.append(Key(ch, ord(ch), 0x1E + i))
    for i, ch in enumerate("ZXCVBNM"):
        keys.append(Key(ch, ord(ch), 0x2C + i))
    for i, ch in enumerate("1234567890"):
        keys.append(Key(ch, ord(ch), 0x02 + i))
    for n in range(1, 13):
        keys.append(Key("F{}".format(n), 0x6F + n,
                        0x3A + n if n <= 10 else 0x57 + n - 11))
    for n, dik in enumerate((0x52, 0x4F, 0x50, 0x51, 0x4B,
                             0x4C, 0x4D, 0x47, 0x48, 0x49)):
        # Numpad 5 with Num Lock off is Clear, a key of its own to Windows.
        keys.append(Key("Numpad {}".format(n), 0x60 + n, dik,
                        (0x0C,) if n == 5 else ()))
    keys += [
        Key("Numpad star", 0x6A, 0x37),
        Key("Numpad plus", 0x6B, 0x4E),
        Key("Numpad minus", 0x6D, 0x4A),
        Key("Numpad dot", 0x6E, 0x53),
        Key("Numpad slash", 0x6F, 0xB5),
        Key("Semicolon", 0xBA, 0x27),
        Key("Equals", 0xBB, 0x0D),
        Key("Comma", 0xBC, 0x33),
        Key("Minus", 0xBD, 0x0C),
        Key("Period", 0xBE, 0x34),
        Key("Slash", 0xBF, 0x35),
        Key("Grave", 0xC0, 0x29),
        Key("Left bracket", 0xDB, 0x1A),
        Key("Backslash", 0xDC, 0x2B),
        Key("Right bracket", 0xDD, 0x1B),
        Key("Apostrophe", 0xDE, 0x28),
        Key("Space", 0x20, 0x39),
        Key("Insert", 0x2D, 0xD2),
        Key("Delete", 0x2E, 0xD3),
        Key("Page up", 0x21, 0xC9),
        Key("Page down", 0x22, 0xD1),
        Key("Home", 0x24, 0xC7),
        Key("End", 0x23, 0xCF),
        Key("Up", 0x26, 0xC8),
        Key("Down", 0x28, 0xD0),
        Key("Left", 0x25, 0xCB),
        Key("Right", 0x27, 0xCD),
        Key("Enter", 0x0D, 0x1C),
        Key("Escape", 0x1B, 0x01),
        Key("Tab", 0x09, 0x0F),
        Key("Backspace", 0x08, 0x0E),
    ]
    return {k.name.lower(): k for k in keys}


KEYS = _table()

# Other spellings a player might reach for. Looked up after the names above.
_SPELLINGS = {
    "numpad *": "numpad star", "numpad +": "numpad plus",
    "numpad -": "numpad minus", "numpad .": "numpad dot",
    "numpad /": "numpad slash", "numpad period": "numpad dot",
    "numpad asterisk": "numpad star", "numpad multiply": "numpad star",
    "numpad add": "numpad plus", "numpad subtract": "numpad minus",
    "numpad divide": "numpad slash", "numpad decimal": "numpad dot",
    "[": "left bracket", "]": "right bracket", "/": "slash",
    "\\": "backslash", ",": "comma", ".": "period", "-": "minus",
    "=": "equals", "`": "grave", "'": "apostrophe", "pageup": "page up",
    "pagedown": "page down", "page_up": "page up", "page_down": "page down",
    "return": "enter", "esc": "escape", "del": "delete", "ins": "insert",
}
for _n in range(10):
    _SPELLINGS["num{}".format(_n)] = "numpad {}".format(_n)
    _SPELLINGS["numpad{}".format(_n)] = "numpad {}".format(_n)

_MODIFIERS = {"shift": "shift", "control": "ctrl", "ctrl": "ctrl"}


class Combo(NamedTuple):
    key: Key
    shift: bool = False
    ctrl: bool = False

    def said(self) -> str:
        """What F1 calls it: "Control and slash", "Shift and 1", "F1"."""
        mods = (["Control"] if self.ctrl else []) + (["Shift"] if self.shift else [])
        name = self.key.name
        if mods and len(name) > 1 and not name.startswith(("F", "Numpad")):
            name = name[0].lower() + name[1:]
        return " and ".join(mods + [name])

    def written(self) -> str:
        """How keys.ini spells it: "Control+Slash"."""
        mods = (["Control"] if self.ctrl else []) + (["Shift"] if self.shift else [])
        return "+".join(mods + [self.key.name])

    def script_code(self) -> int:
        return (self.key.dik + (SCRIPT_SHIFT if self.shift else 0)
                + (SCRIPT_CTRL if self.ctrl else 0))


def parse(text: str) -> Optional[Combo]:
    """ "Control+Slash" -> Combo. None if any part of it is not a key."""
    parts = [p.strip().lower() for p in (text or "").split("+")]
    # "Numpad +" splits into "numpad " and "": put a trailing plus back.
    if len(parts) >= 2 and parts[-1] == "" and parts[-2].endswith("numpad"):
        parts = parts[:-2] + [parts[-2] + " +"]
    if not parts or not parts[-1]:
        return None
    shift = ctrl = False
    for mod in parts[:-1]:
        which = _MODIFIERS.get(mod)
        if which == "shift":
            shift = True
        elif which == "ctrl":
            ctrl = True
        else:
            return None
    if shift and ctrl:
        # One modifier at most: the scripts and the listener both read one.
        return None
    name = " ".join(parts[-1].split())
    key = KEYS.get(name) or KEYS.get(_SPELLINGS.get(name, ""))
    return Combo(key, shift, ctrl) if key else None


# Keys no action may take, and why -- said in the log when one is tried.
FIXED_REASON = {
    "up": "the grammar every screen keeps", "down": "the grammar every screen keeps",
    "left": "the grammar every screen keeps", "right": "the grammar every screen keeps",
    "enter": "the grammar every screen keeps", "escape": "the grammar every screen keeps",
    "backspace": "the grammar every screen keeps", "home": "the grammar every screen keeps",
    "end": "the grammar every screen keeps", "tab": "the game's and the character sheet's",
    "apostrophe": "the mod presses it to find the pointer",
    "backslash": "the mod presses it to set up a click",
    "numpad 0": "the mod presses it to ask for an inventory's totals",
}
# The number row, unmodified: skills on the map, replies in a conversation,
# and amounts in the "how many" window.
for _d in "1234567890":
    FIXED_REASON[_d] = "the game's, for skills and replies"


def fixed_reason(combo: Combo) -> Optional[str]:
    """Why no action may have this key, or None if one may.

    A digit is only the game's on its own: Shift and 1 is the light level.
    Everything else in the list is fixed with or without a modifier -- Shift
    and Tab is the character editor's, Control and Up steps by ten.
    """
    name = combo.key.name.lower()
    if len(name) == 1 and name.isdigit() and (combo.shift or combo.ctrl):
        return None
    return FIXED_REASON.get(name)


class Action(NamedTuple):
    name: str                 # as keys.ini spells it
    default: str              # as keys.ini spells it
    note: str                 # the comment above it in keys.ini
    python: Tuple[str, ...]   # the hotkey names the Python side dispatches
    script: bool              # whether the scripts read it
    where: str = "map"        # its section in keys.ini


# The order is the order keys.ini lists them in. `python` names are the ones
# f2access.HOTKEYS already uses, so a default keymap leaves those tables as
# they always were.
ACTIONS: Tuple[Action, ...] = (
    # -- the look cursor, and the world map's cursor on the same keys ---------
    Action("cursor_northwest", "Numpad 7", "Look cursor one hex north-west; a square on the world map.", ("wm_nw",), True),
    Action("cursor_northeast", "Numpad 9", "North-east.", ("wm_ne",), True),
    Action("cursor_west", "Numpad 4", "West.", ("wm_w",), True),
    Action("cursor_east", "Numpad 6", "East.", ("wm_e",), True),
    Action("cursor_southwest", "Numpad 1", "South-west.", ("wm_sw",), True),
    Action("cursor_southeast", "Numpad 3", "South-east.", ("wm_se",), True),
    Action("cursor_north", "Numpad 8", "North, on the world map only; hexes have no north. Also the previous item in a list.", ("num8",), True),
    Action("cursor_south", "Numpad 2", "South, on the world map only. Also the next item in a list.", ("num2",), True),
    Action("cursor_home", "Numpad 5", "Back to you. In a list, say it again.", ("num5",), True),
    # -- the scanner --------------------------------------------------------
    Action("scan_kind_previous", "Left bracket", "The scanner: the previous kind of thing. Places you know, on the world map.", ("wm_scan_prev",), True),
    Action("scan_kind_next", "Right bracket", "The next kind of thing.", ("wm_scan_next",), True),
    Action("scan_one_previous", "Shift+Left bracket", "The previous one of that kind.", (), True),
    Action("scan_one_next", "Shift+Right bracket", "The next one of that kind.", (), True),
    Action("scan_category_previous", "Control+Left bracket", "The previous category: critters, items, scenery, exits.", (), True),
    Action("scan_category_next", "Control+Right bracket", "The next category.", (), True),
    Action("scan_go", "Slash", "Put the look cursor on what the scanner is on.", ("wm_scan_jump",), True),
    Action("route_say", "Shift+Slash", "The way to the look cursor.", (), True),
    Action("route_walk", "Control+Slash", "Walk all the way to the look cursor; again to stop.", (), True),
    # -- you ----------------------------------------------------------------
    Action("status", "Semicolon", "Health, action points and armour class.", (), True),
    Action("weapon", "Shift+Semicolon", "What is in your hand.", (), True),
    Action("use_hand", "U", "Use what is in your hand.", (), True),
    Action("light", "Shift+1", "How much light is on the look cursor's hex.", (), True),
    Action("menu", "Numpad dot", "What can I do to this; on other screens, the full description.", ("describe",), True),
    # -- the mouse, and the questions every screen answers ------------------
    Action("left_click", "Numpad plus", "Left mouse button, on the look cursor's hex.", ("click",), False, "everywhere"),
    Action("right_click", "Numpad minus", "Right mouse button: the cursor mode.", ("rclick",), False, "everywhere"),
    Action("where_am_i", "Numpad star", "Where you are.", ("summary",), False, "everywhere"),
    Action("say_again", "Numpad slash", "Say it again.", ("repeat",), False, "everywhere"),
    Action("help", "F1", "The keys for the screen you are on.", ("help",), True, "everywhere"),
    Action("log_older", "Shift+Comma", "The message log, older.", ("log_prev",), True, "everywhere"),
    Action("log_newer", "Shift+Period", "The message log, newer.", ("log_next",), True, "everywhere"),
    Action("barter_offer", "O", "Offer, when trading.", ("barter_offer",), False, "everywhere"),
)

BY_NAME = {a.name: a for a in ACTIONS}


class Keymap(NamedTuple):
    combos: Dict[str, Combo]

    def __getitem__(self, action: str) -> Combo:
        return self.combos[action]

    def moved(self, action: str) -> bool:
        return self.combos[action] != DEFAULTS.combos[action]

    def said(self, action: str) -> str:
        return self.combos[action].said()


def defaults() -> Keymap:
    return Keymap({a.name: parse(a.default) for a in ACTIONS})


DEFAULTS = defaults()


def keys_path() -> str:
    return os.path.join(paths.app_dir(), KEYS_NAME)


def load(path: Optional[str] = None, problems: Optional[List[str]] = None) -> Keymap:
    """Read keys.ini. A missing file is the defaults; a bad line costs only itself."""
    path = path or keys_path()
    problems = problems if problems is not None else []
    cfg = configparser.ConfigParser(interpolation=None,
                                    inline_comment_prefixes=(";", "#"))
    try:
        with open(path, encoding="utf-8-sig") as fh:
            cfg.read_file(fh)
    except FileNotFoundError:
        return DEFAULTS
    except (OSError, configparser.Error, UnicodeDecodeError) as exc:
        problems.append("{}: {}".format(path, exc))
        return DEFAULTS
    return resolve(_entries(cfg, problems), problems)


def _entries(cfg, problems: List[str]) -> Dict[str, str]:
    wanted: Dict[str, str] = {}
    for section in cfg.sections():
        for name, value in cfg.items(section):
            name = name.strip().lower()
            if name not in BY_NAME:
                problems.append("keys.ini: {} is not one of the mod's keys".format(name))
                continue
            wanted[name] = value.strip()
    return wanted


def resolve(wanted: Dict[str, str], problems: Optional[List[str]] = None) -> Keymap:
    """The keymap `wanted` asks for, with every mistake put back to the default."""
    problems = problems if problems is not None else []
    combos = dict(DEFAULTS.combos)
    for name, text in wanted.items():
        if not text:
            continue
        combo = parse(text)
        if combo is None:
            problems.append("keys.ini: {} = {}: not a key the mod knows, "
                            "keeping {}".format(name, text, combos[name].written()))
            continue
        why = fixed_reason(combo)
        if why:
            problems.append("keys.ini: {} = {}: that key is not free ({}), so it stays {}".format(
                name, text, why, combos[name].written()))
            continue
        combos[name] = combo
    # Two actions on one key: neither can be told apart from the other, so
    # both go back -- and so on, in case going back makes a new clash.
    while True:
        seen: Dict[Combo, str] = {}
        clash = None
        for a in ACTIONS:
            other = seen.get(combos[a.name])
            if other is not None:
                clash = (other, a.name)
                break
            seen[combos[a.name]] = a.name
        if clash is None:
            break
        moved = [n for n in clash if combos[n] != DEFAULTS.combos[n]]
        if not moved:   # two defaults clashing is a bug in this file
            raise AssertionError("default keys clash: {} and {}".format(*clash))
        for n in moved:
            problems.append("keys.ini: {} and {} are both on {}; {} goes back to {}".format(
                clash[0], clash[1], combos[n].written(), n,
                DEFAULTS.combos[n].written()))
            combos[n] = DEFAULTS.combos[n]
    return Keymap(combos)


# -- the Python side ------------------------------------------------------------

def apply(keymap: Keymap, plain: Dict[int, str], shifted: Dict[int, str],
          ctrl: Dict[int, str]) -> None:
    """Move each action the keymap moved, in the listener's three tables.

    Only moved actions are touched, so the defaults leave the tables exactly as
    f2access.py writes them -- comments, aliases and all.
    """
    for a in ACTIONS:
        if not a.python or not keymap.moved(a.name):
            continue
        for table in (plain, shifted, ctrl):
            for vk in [vk for vk, what in table.items() if what in a.python]:
                del table[vk]
    for a in ACTIONS:
        if not a.python or not keymap.moved(a.name):
            continue
        combo = keymap[a.name]
        table = ctrl if combo.ctrl else shifted if combo.shift else plain
        for vk in (combo.key.vk,) + combo.key.aliases:
            table[vk] = a.python[0]


# -- the scripts' side ----------------------------------------------------------

def script_lines(keymap: Keymap) -> List[str]:
    lines = ["; Written by Access Never Changes from keys.ini every time it starts.",
             "; Edit keys.ini, not this.",
             "[keys]"]
    for a in ACTIONS:
        if a.script:
            lines.append("{}={}".format(a.name, keymap[a.name].script_code()))
    return lines


def write_script_keys(keymap: Keymap, game_dir: Optional[str],
                      problems: Optional[List[str]] = None) -> Optional[str]:
    """Hand the scripts their keys. Returns where, or None if it could not."""
    if not game_dir:
        return None
    folder = os.path.join(game_dir, SCRIPT_KEYS_DIR)
    path = os.path.join(folder, SCRIPT_KEYS_NAME)
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="ascii", newline="\r\n") as fh:
            fh.write("\n".join(script_lines(keymap)) + "\n")
    except OSError as exc:
        if problems is not None:
            problems.append("could not write {}: {}".format(path, exc))
        return None
    return path


def file_text(keymap: Keymap = DEFAULTS) -> str:
    """keys.ini as shipped: every action, its note, and its key."""
    out = [
        "; Access Never Changes, keys.",
        "; Lines starting with a semicolon are notes, and are ignored. Change a key, save the file, and start the mod again.",
        "; Keys are written the way F1 says them: A, F5, Numpad 7, Numpad plus, Semicolon, Left bracket, Slash, Page up. Hold a key with Shift or Control by writing Shift+ or Control+ in front of it: Control+Slash.",
        "; The arrows, Enter, Escape, Backspace, Tab, Home, End, the number row, Apostrophe, Backslash and Numpad 0 cannot be moved: every screen, or the mod itself, depends on them.",
        "; A key that is not right, or that two lines ask for, goes back to what it was, and f2access.log says which.",
        "; The keys in [map] are taken from the game while it is on a map, so a key the game uses for something else stops doing that there. The keys in [everywhere] work on every screen, and the game still hears them, apart from help and the message log.",
    ]
    section = None
    for a in ACTIONS:
        if a.where != section:
            section = a.where
            out += ["", "[{}]".format(section)]
        out += ["; " + a.note, "{} = {}".format(a.name, keymap[a.name].written())]
    return "\n".join(out) + "\n"


def describe(actions: Iterable[str], keymap: Keymap) -> str:
    """Several actions' keys as F1 says them: "K, L and semicolon"."""
    names: List[str] = []
    for a in actions:
        s = keymap.said(a)
        if s not in names:
            names.append(s)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
