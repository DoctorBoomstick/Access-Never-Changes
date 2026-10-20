"""The mod's keyboard, as one set of rules every screen keeps.

The keys grew one screen at a time, each taking whatever the game left free
when it was built: arrows and Enter in the action menu, numpad plus and minus
on the Pip-Boy, plus and minus again for the explosive timer, numpad plus to
travel on the world map. Each choice was reasonable on its own day, and
together they meant a player had to remember which screen wanted which hand.

So this is the grammar, and `tests/test_controls.py` fails the build if a
screen breaks it:

    Up, Down          move through a list. In a window with one number and
                      nothing to move between -- how many, the timer -- they
                      change it.
    Left, Right       change the value you are on.
    Enter             choose, open, do it.
    Escape            back out. Usually the game's own key, already working.
    Backspace         back one level, where Escape would close the whole
                      screen (the Pip-Boy).
    Home, End         the least and the most of a value.
    Numpad + and -    the mouse buttons. On the map, and only on the map.
    Numpad *          where am I.
    Numpad /          say that again.
    Numpad .          what can I do (the map), or the full description.
    F1                the keys for the screen you are on.
    Shift , and .     the message log: older and newer. Everywhere.

A screen states its keys as `Binding`s on its watcher. The same list does the
dispatching, is what F1 reads aloud, and is what the test checks -- so the
help cannot describe keys the screen does not have, and a screen cannot quietly
grow a key the grammar does not allow.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, NamedTuple, Optional, Tuple
from .i18n import tr, tr_text

# What each physical key is allowed to mean. The values are roles; a binding
# names its role, and the test checks the two agree.
ROLES: Dict[str, FrozenSet[str]] = {
    "dlg_prev": frozenset({"previous", "more"}),
    "num8": frozenset({"previous", "more"}),
    "dlg_next": frozenset({"next", "less"}),
    "num2": frozenset({"next", "less"}),
    "left": frozenset({"less", "previous"}),
    "right": frozenset({"more", "next"}),
    "enter": frozenset({"choose"}),
    "back": frozenset({"back"}),
    "home": frozenset({"least"}),
    "end": frozenset({"most"}),
    "click": frozenset({"mouse"}),
    "rclick": frozenset({"mouse"}),
    "summary": frozenset({"summary"}),
    "repeat": frozenset({"repeat"}),
    "num5": frozenset({"repeat"}),
    "dlg_say": frozenset({"repeat"}),
    "describe": frozenset({"describe", "menu"}),
    "help": frozenset({"help"}),
    "log_prev": frozenset({"history"}),
    "log_next": frozenset({"history"}),
}
for _d in range(10):
    ROLES["digit{}".format(_d)] = frozenset({"type"})
# The world map's own cursor and scanner, which are the map's numpad and
# brackets carried over to the one screen where no script reads them.
for _d in ("n", "s", "e", "w", "ne", "nw", "se", "sw", "snap"):
    ROLES["wm_" + _d] = frozenset({"cursor"})
for _d in ("scan_prev", "scan_next", "scan_jump"):
    ROLES["wm_" + _d] = frozenset({"scan"})
# T is the engine's own town view key, watched so a refusal can be explained.
ROLES["wm_town"] = frozenset({"watch"})

# The role of a key the mod does not dispatch -- the game's own, or one the
# in-game scripts read for themselves -- listed so F1 can say it.
GAME = "game"

# Spoken names for the keys, for the help.
KEY_NAMES = {
    "dlg_prev": "Up", "dlg_next": "Down", "num8": "Numpad 8", "num2": "Numpad 2",
    "left": "Left", "right": "Right", "enter": "Enter", "back": "Backspace",
    "home": "Home", "end": "End", "click": "Numpad plus",
    "rclick": "Numpad minus", "summary": "Numpad star", "repeat": "Numpad slash",
    "num5": "Numpad 5", "describe": "Numpad dot", "help": "F1",
    "log_prev": "Shift comma", "log_next": "Shift period",
}


class Binding(NamedTuple):
    """One key, or one pair of keys, on one screen.

    `actions` are the hotkey names that trigger it (empty for a key the game
    handles itself, which is listed only so F1 can mention it). `call` is the
    watcher method, given the announcer and then `args`. `role` is checked
    against ROLES. `keys` and `does` are what F1 says.
    """

    keys: str
    does: str
    role: str
    actions: Tuple[str, ...] = ()
    call: Optional[str] = None
    args: Tuple = ()


# The keys every screen answers to the same way. Not repeated per screen; F1
# says them last.
COMMON = (
    Binding("Numpad slash", "say it again", "repeat", ("repeat",), "repeat"),
    Binding("Numpad star", "where you are", "summary", ("summary",), "summary"),
    Binding("Shift with comma and period", "the message log, older and newer",
            "history", ("log_prev", "log_next")),
    Binding("F1", "these keys", "help", ("help",)),
)

# Where numpad plus and minus are mouse buttons. Everywhere else they are
# answered with a pointer to F1 instead of a click at wherever the pointer was
# last left.
MOUSE_SCREENS = frozenset({"world"})


def keys_of(watcher) -> Tuple[Binding, ...]:
    return tuple(getattr(watcher, "KEYS", ()) or ())


def find(watcher, what: str) -> Optional[Binding]:
    for b in keys_of(watcher):
        if what in b.actions:
            return b
    return None


def dispatch(watcher, what: str, ann) -> bool:
    """Run the binding for `what` on this screen. False if it has none."""
    b = find(watcher, what)
    if b is None or b.call is None:
        return False
    getattr(watcher, b.call)(ann, *b.args)
    return True


def help_text(bindings, screen_name: str = "") -> str:
    """What F1 says: this screen's keys, then the ones that are everywhere."""
    lines = []
    seen = set()
    for b in bindings:
        if b.keys in seen:
            continue
        seen.add(b.keys)
        lines.append(_said(b))
    head = (tr("controls.title", "{screen} keys.", screen=screen_name) + " "
            if screen_name else "")
    if not lines:
        lines.append(tr("controls.game_keys", "This screen uses the game's own keys."))
    tail = " ".join(_said(b) for b in COMMON if b.role != "help")
    return head + " ".join(lines) + " " + tail


def _said(b: Binding) -> str:
    """One line of F1, translated under keys made from the table's English."""
    return "{}: {}.".format(tr_text("keys", b.keys), tr_text("help", b.does))


def violations(screen: str, bindings: Iterable[Binding], watcher_cls=None):
    """Every way a screen's keys break the grammar, as sentences. Empty is good."""
    out = []
    used: Dict[str, str] = {}
    known = {r for rs in ROLES.values() for r in rs} | {GAME}
    for b in bindings:
        if b.role == GAME and b.actions:
            out.append("{}: {} is marked as the game's but the mod acts on it"
                       .format(screen, b.keys))
        if b.role not in known:
            out.append("{}: unknown role {!r}".format(screen, b.role))
        for a in b.actions:
            allowed = ROLES.get(a)
            if allowed is None:
                out.append("{}: {!r} is not a key the mod listens for".format(screen, a))
            elif b.role not in allowed:
                out.append("{}: {} may not mean {!r}".format(
                    screen, KEY_NAMES.get(a, a), b.role))
            if a in used:
                out.append("{}: {} is bound twice".format(screen, KEY_NAMES.get(a, a)))
            used[a] = b.role
            if b.role == "mouse" and screen not in MOUSE_SCREENS:
                out.append("{}: numpad plus and minus are mouse buttons, and "
                           "only on the map".format(screen))
        if b.call and watcher_cls is not None and not callable(
                getattr(watcher_cls, b.call, None)):
            out.append("{}: {} calls {!r}, which does not exist".format(
                screen, b.keys, b.call))
    return out
