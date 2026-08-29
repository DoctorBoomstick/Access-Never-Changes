"""Read the in-game script's output.

gl_world.ssl runs inside Fallout 2 and writes "WORLD:" lines to debug.log --
hex readouts, game-mode changes, calibration. This tails that file so the
Python side can speak them.

Why a log file rather than shared memory: sfall scripts can write strings with
debug_msg and little else, and the engine's own object names are only reachable
from inside the game. The file is the one channel that carries text out. It is
polled at the same 20Hz as everything else, which is well inside the reaction
time that matters here.

The game truncates debug.log on launch, so a shrinking file means a new session
and all remembered state is dropped.
"""

from __future__ import annotations

import os
import re
from typing import List, NamedTuple, Optional

from . import charsheet

PREFIX = "WORLD:"
# gl_combat.ssl writes on the same channel. Two scripts, one log file: they are
# kept as separate scripts so a bug in one cannot crash the other, but there is
# only one way for either to get text out of the engine.
COMBAT_PREFIX = "COMBAT:"
# The scanner also writes on this channel, from gl_world.ssl.
SCAN_PREFIX = "SCAN:"
# gl_inven.ssl, a third script, for the inventory and loot windows.
INVEN_PREFIX = "INVEN:"
# The character sheet, reported once when that screen opens.
CHAR_PREFIX = "CHAR:"
# The Skilldex panel's contents, likewise.
SKILLDEX_PREFIX = "SKILLDEX:"

# get_game_mode's CHARSCREEN bit. Spelled out rather than imported, the same way
# slotscreen spells out SAVEGAME: screens.py is the module that owns these names
# and it already reaches into this one.
MODE_CHARSCREEN = 0x200

# "WORLD:hex 17488 dist 0 : you, Tree|"
# Contents stop at the terminating bar. The engine appends its own debug output
# to our lines without a newline, and without the bar that noise was read as
# part of the object list and spoken aloud.
_HEX_RE = re.compile(r"WORLD:hex\s+(\d+)\s+dist\s+(\d+)\s*:\s*([^|]*)")
_MODE_RE = re.compile(r"WORLD:gamemode\s+(-?\d+)")
# "WORLD:dudename Tara|" -- who the hex readout means by "you".
_DUDENAME_RE = re.compile(r"WORLD:dudename ([^|]*)\|")
# Both forms report the current cursor mode: "cursormode" when it changed,
# "cursorok" when a press found it already correct. Parsing only the first left
# the mode unknown exactly when nothing had changed, which is the common case.
_CURSOR_RE = re.compile(r"WORLD:cursor(?:mode|ok)\s+(-?\d+)")


# "WORLD:status 48|48|8|10|8|1|" and, since level was added, "...|1|2|1450|"
#
# The last two are optional so that a game still running the previously compiled
# script keeps working. A regex that demanded eight fields would not merely lose
# the level -- it would fail to match at all, and the one key that reports how
# you are doing would go silent, which is a far worse trade than a missing
# level.
_STATUS_RE = re.compile(
    r"WORLD:status\s+(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|"
    r"(?:(-?\d+)\|(-?\d+)\|)?"
)


def status_line(line: str) -> Optional[str]:
    """Turn a WORLD:status line into the sentence to say, or None.

    Health first, then action points, then armour class -- the order asked for,
    and the order they matter in when something is biting you. Level and
    experience last, because they are the only two on this line that do not
    change in the middle of a fight.

    Action points are only a live figure during a fight. Outside one the engine
    still reports a running count, but it is not a number anyone is spending, so
    the maximum is given instead and worded as a capacity rather than a
    remainder. Saying "3 action points" while walking around would be true of
    nothing.
    """
    m = _STATUS_RE.match(line)
    if not m:
        return None
    hp, max_hp, ap, max_ap, ac, fighting = (int(g) for g in m.groups()[:6])
    parts = ["Health {} of {}.".format(hp, max_hp)]
    if fighting:
        parts.append("{} of {} action points.".format(ap, max_ap))
    else:
        parts.append("{} action points.".format(max_ap))
    parts.append("Armor class {}.".format(ac))
    parts.extend(_level_words(m.group(7), m.group(8)))
    return " ".join(parts)


def _level_words(level, experience) -> List[str]:
    """Your level, and how much experience the next one still wants.

    The character sheet has shown both for a while and there was no way to hear
    either without opening it, which makes "what level am I" a four-keystroke
    round trip for a one-word answer.

    **How much further, not how much altogether.** The sheet prints the total
    the next level costs, because a sighted player reads it against the total
    you have on the line above. Read aloud one after the other, two large
    similar numbers are something the listener has to subtract themselves, and
    the answer they wanted was the difference all along.

    The threshold is arithmetic rather than a reading -- see
    `charsheet.next_level_experience` -- so it is quietly dropped if it comes
    out at or below what you already have. That happens at the level cap and
    whenever a mod retables the progression, and a negative number of points to
    go would be worse than saying nothing.
    """
    if level is None or experience is None:
        return []
    level, experience = int(level), int(experience)
    said = ["Level {}.".format(level)]
    needed = charsheet.next_level_experience(level)
    if needed is not None and needed > experience:
        said.append("{} experience to the next level.".format(
            needed - experience))
    return said


# "WORLD:useactive Plastic Explosives|0||"  and, for an empty active hand,
# "WORLD:useactive empty|0|Healing Powder|" naming what the OTHER hand holds.
# The third field is optional so an older compiled script still parses.
_USEACTIVE_RE = re.compile(r"WORLD:useactive ([^|]*)\|(-?\d+)?\|?([^|]*)?\|?")


def use_active_line(line):
    """(item, is_a_weapon, what to say) for a WORLD:useactive line, or None.

    The script reports rather than acts, because using a carried item ends in a
    click on the interface bar's item slot and only the Python side has a
    pointer.

    **A weapon is no longer refused.** This used to stop and explain itself
    whenever the active item was a weapon, on the grounds that the item slot
    attacks with a live weapon and a stray swing costs a turn. That is a real
    consequence, and it is the player's to accept: a sighted player presses the
    same slot with the same weapon in hand and the game does not argue with
    them. Deciding on someone's behalf that they cannot have meant it is not
    accessibility, it is a smaller game.

    The flag is still reported and still spoken, because "Spear" and "Spear, a
    weapon" are different facts about what is in your hand -- and knowing it is
    what makes the decision an informed one instead of a blocked one.
    """
    m = _USEACTIVE_RE.match(line)
    if not m:
        return None
    name = m.group(1).strip()
    if name == "empty" or not name:
        # The slot acts on the ACTIVE hand, so an item in the other one might as
        # well be in the pack. Naming it is the difference between "this key is
        # broken" and "the powder is in your other hand" -- which is exactly the
        # confusion this reading used to cause, back when it reported the other
        # hand's item as though the slot would use it.
        other = (m.group(3) or "").strip()
        if other:
            return None, False, ("Your active hand is empty. {} is in the other "
                                 "hand.".format(other))
        return None, False, "Your hands are empty. Ready something first."
    weapon = m.group(2) == "1"
    if weapon:
        return name, True, "Using {}, a weapon.".format(name)
    return name, False, "Using {}.".format(name)


_MENU_RE = re.compile(r"WORLD:menu (\w+)\s*([^|]*)\|?([^|]*)\|?([^|]*)\|?([^|]*)\|?")


def menu_line(line: str, aimed_at: Optional[str] = None) -> Optional[str]:
    """Turn a WORLD:menu line into the sentence to say, or None.

    The mod's own version of the icon strip a sighted player gets: everything
    the engine says can be done to this object, arrows to move, Enter to do it.

    `aimed_at` is what the pointer was actually put on when the list was built.
    The engine's action array is never cleared, only overwritten, so a list read
    at the wrong moment is a confident answer about the previous object -- and
    since it is never empty, that looks exactly like a good one. Python knows
    what it aimed at and the script names what it opened the menu for; if the
    two disagree the only honest thing is to say so rather than read out a menu
    for something else.
    """
    m = _MENU_RE.match(line)
    if not m:
        return None
    what = m.group(1)
    if what == "none":
        return "Nothing there to act on."
    if what == "empty":
        return "{}. Nothing you can do to it.".format(m.group(2).strip() or "That")
    if what == "closed":
        return "Closed."
    if what == "gone":
        return "That is no longer there."
    if what == "noroute":
        return ("{}. The game offers that, but the mod has no way to do it yet."
                .format(m.group(2).strip().capitalize()))
    if what == "open":
        name, count, first = (m.group(2).strip(), m.group(3).strip(),
                              m.group(4).strip())
        # Tolerant, not equal. Both names come from the engine, but through two
        # doors that word them differently: the aim reports through obj_label,
        # which appends ", locked" or ", open", while the menu reports the bare
        # obj_name. An equality test therefore cried wolf on exactly the locked
        # doors and open containers -- announcing "read the wrong thing" about a
        # perfectly good menu for the one object the player most needed it for.
        if aimed_at and name and not names_match(name, aimed_at):
            return ("Read the wrong thing: pointed at {} but the game answered "
                    "for {}. Try again.".format(aimed_at, name))
        return "{}. {} actions. {}, 1 of {}.".format(
            name, count, first.capitalize(), count)
    if what == "at":
        label, index, count = (m.group(2).strip(), m.group(3).strip(),
                               m.group(4).strip())
        return "{}, {} of {}.".format(label.capitalize(), index, count)
    return None


# "WORLD:pick open|Door Track|1|2|"
_PICK_RE = re.compile(r"WORLD:pick (\w+)\s*\|?([^|]*)\|?([^|]*)\|?([^|]*)\|?")


def pick_line(line: str) -> Optional[str]:
    """Turn a WORLD:pick line into the sentence to say, or None.

    The list of things on the hex, offered before the list of things to do to
    them. It exists because "which object did you mean" was previously answered
    by where a mouse pointer ended up, and that answer was wrong twice in ways
    the player could not see -- a door lost to the Door Track sharing its tile,
    and walkable ground refused because a wall was drawn across it.

    Both entries and count are said, because the count is what tells you
    whether stepping the list is worth doing at all.
    """
    m = _PICK_RE.match(line)
    if not m:
        return None
    what = m.group(1)
    if what == "none":
        return "Nothing here to act on."
    if what == "closed":
        return "Cancelled."
    if what == "gone":
        return "That is no longer there."
    if what in ("open", "at"):
        label, index, count = (m.group(2).strip(), m.group(3).strip(),
                               m.group(4).strip())
        said = "{}, {} of {}.".format(label.capitalize(), index, count)
        if what == "open":
            # Only on the way in. Repeating it on every step would bury the
            # thing being stepped to.
            said = "{} things here. {}".format(count, said)
        return said
    return None


# "WORLD:useobj try Impenetrable Door|"
_USEOBJ_RE = re.compile(r"WORLD:useobj (\w+)\s*([^|]*)\|?")


def use_obj_line(line: str) -> Optional[str]:
    """Turn a WORLD:useobj line into the sentence to say, or None.

    "Use it" -- the hand icon. Nothing could reach this before: the mod only
    ever selects the movement or targeting cursor, so a click on a door walked
    into it instead of opening it, and opening one needs the command cursor the
    mod never picks.

    Like the item version, finishing says nothing. The engine reports what
    happened in its own words through the display window, which is already read
    aloud, and it knows whether the door was locked.
    """
    m = _USEOBJ_RE.match(line)
    if not m:
        return None
    what, target = m.group(1), m.group(2).strip()
    if what == "notarget":
        return "Nothing there to use."
    if what == "try":
        return "Using {}.".format(target or "it")
    return None


# "WORLD:useitem try Plastic Explosives|Impenetrable Door|"
_USEITEM_RE = re.compile(r"WORLD:useitem (\w+)\s*([^|]*)\|?([^|]*)\|?")


def use_item_line(line: str) -> Optional[str]:
    """Turn a WORLD:useitem line into the sentence to say, or None.

    Four outcomes, and the wording keeps them apart because they need
    different things done about them: nothing in your hand, nothing to use it
    on, the attempt starting, and the attempt returning.

    "Done" deliberately does not claim success. The engine runs the object's own
    handler, and whether a door opens or a lock refuses is something the game
    says in its own words through the display window -- which this mod already
    reads aloud. Inventing a verdict here would put a second, less informed
    voice on top of the one that actually knows.
    """
    m = _USEITEM_RE.match(line)
    if not m:
        return None
    what, item, target = m.group(1), m.group(2).strip(), m.group(3).strip()
    if what == "empty":
        return "Your hands are empty. Ready an item first."
    if what == "notarget":
        return "Nothing there to use it on."
    if what == "try":
        return "Using {} on {}.".format(item or "that", target or "it")
    return None      # "done" carries diagnostics; the game's own words follow


# Words the readout is not naming an object with.
#
# "empty", "blocked" and "you" are what describe_cursor says INSTEAD of a list
# of objects. "locked" and "open" are the state gl_world.ssl's obj_label appends
# to a door or a container -- and it appends them with the same comma that
# separates one object from the next, which is why they have to be named here:
# nothing about the string itself distinguishes "Door, locked" (one object) from
# "Door Track, Door" (two). Both halves of that pair are ours rather than the
# game's, so listing them does not break a translation the way filtering on an
# object name would.
# The words the mod appends to a name, plus the ones it says instead of a name.
# `names()` splits the readout on commas, so every state word obj_label can add
# has to be listed here or it comes back as an object called "dead".
NOT_A_NAME = frozenset(("empty", "blocked", "you", "locked", "open", "dead"))

# The same problem, but the suffix carries a value so it cannot be a fixed word.
# "Klint, facing north east" is ONE object, and without this the readout parses
# as two -- an object called "facing north east" that a click could then be
# aimed at. Matched by prefix because the six bearings are the mod's own words
# and always follow this one.
NOT_A_NAME_PREFIXES = ("facing ",)


def wanted_names(wanted) -> List[str]:
    """Normalise one name, or many, into a list to match against.

    Callers that know exactly what they aimed at -- the action menu, handed an
    object name by the script -- pass a string. The click passes everything the
    hex readout named, because the readout is the player's own knowledge of that
    hex and any of it is a fair answer.
    """
    if not wanted:
        return []
    if isinstance(wanted, str):
        wanted = [wanted]
    return [w.strip().lower() for w in wanted if w and w.strip()]


def bare_name(name: str) -> str:
    """An object's name with the mod's state words taken back off.

    The engine is asked the same question through two doors that word the
    answer differently: `prepare_cursor` reports through `obj_label`, which
    appends state -- "Door, locked" -- while the menu reports the bare
    `obj_name`, "Door". The suffix is the mod's own and always comes after a
    comma, so it comes off the same way the hex readout takes it off.
    """
    return (name or "").split(",")[0].strip().lower()


def names_match(name: str, acceptable) -> bool:
    """Is `name` one of the objects in `acceptable`?

    Whole names, once the state suffix is off. This was a substring test either
    way round, and that is not a smaller mistake than demanding equality -- it
    is the same mistake pointing the other way. **"Door" is a substring of
    "Door Track"**, so on the hex that every sliding door in the game sits on,
    a caller asking for the door accepted the flat rail underneath it, and a
    lockpick armed for the door was spent on a piece of track. Measured on hex
    11108 in the Arroyo caves: `WORLD:prepare 6|Door Track|` seven times over,
    each one a skill use the player watched do nothing.
    """
    low = bare_name(name)
    if not low:
        return False
    return any(low == bare_name(w) for w in wanted_names(acceptable))


def _say_as(contents: str, player_name: str) -> str:
    """Swap the script's word for you with your name, and nothing else.

    Field by field, and only on a whole field. A blanket replace would find the
    "you" inside "Young Radscorpion", and a hex holding one of those is a hex
    where being told the wrong thing has consequences.
    """
    fields = [f.strip() for f in contents.split(",")]
    return ", ".join(player_name if f.lower() == "you" else f for f in fields)


class HexReading(NamedTuple):
    tile: int
    distance: int
    contents: str

    def announce(self, player_name: Optional[str] = None) -> str:
        """What to say when the cursor lands here.

        `player_name` replaces the word the script uses for you. The script
        cannot send the name in the first place: "you" is one of the words that
        tells the parser this hex holds nothing to point at, and a hex reading
        "Tara" would have the click machinery trying to aim at a character the
        engine deliberately refuses to confirm a pointer is over.

        So the substitution happens here, at the last possible moment, on the
        string nobody parses again. Everything upstream keeps a word it can
        trust, and the player hears their own name -- which is what the readout
        was already doing for every other critter on the map.
        """
        what = self.contents.strip() or "empty"
        if player_name:
            what = _say_as(what, player_name)
        if self.distance == 0:
            return what
        return "{}, {} hex{}".format(what, self.distance, "" if self.distance == 1 else "es")

    def names(self) -> List[str]:
        """Every object the readout named, in the order the script listed them.

        This exists because `contents.split(",")[0]` was being used as "the
        thing the player meant", and on a hex holding more than one object that
        picks whichever the engine happened to list first. Every sliding door in
        the game sits on a Door Track, so a door hex reads "Door Track, Door",
        the first field is the track, and the click then refused to act on the
        door because the engine kept answering "Door" -- which was correct, and
        was discarded thirty-two times in a row.

        The readout is prose written for a listener, so parsing it back is doing
        the string a violence it was not designed for. Returning all of the
        fields rather than one of them is what makes that tolerable: the caller
        no longer has to guess which is right, because it asks the engine and
        accepts any answer the player has been told about.
        """
        out: List[str] = []
        for field in self.contents.split(","):
            name = field.strip()
            if not name or name.lower() in NOT_A_NAME:
                continue
            if name.lower().startswith(NOT_A_NAME_PREFIXES):
                continue
            if name not in out:
                out.append(name)
        return out


class WorldLog:
    def __init__(self, path: str) -> None:
        self.path = path
        self._pos = 0
        self.game_mode: Optional[int] = None
        self.cursor_mode: Optional[int] = None
        self.last_hex: Optional[HexReading] = None
        # The in-game character screen, as the engine reports it. Lives here
        # rather than on a watcher because the script fills it and a different
        # watcher reads it.
        self.sheet = charsheet.Sheet()
        # The name the readout says instead of "you". None until the script has
        # sent it, and the readout falls back to "you" until then -- which is
        # true, and better than a name nobody has checked.
        self.player_name: Optional[str] = None
        self.session_live = False
        # Bumped every time the script announces itself, which it does once per
        # game load. The display window's buffer is reallocated at the same
        # moment, so this is what tells the reader its anchor has gone stale --
        # loading a save without restarting the game left it pointing at freed
        # heap, and the game's own words went quiet with nothing to show why.
        self.ready_count = 0

    def reset(self) -> None:
        self._pos = 0
        self.game_mode = None
        self.cursor_mode = None
        self.last_hex = None
        self.sheet = charsheet.Sheet()
        self.player_name = None
        self.session_live = False
        self.ready_count = 0

    def poll(self) -> List[str]:
        """Return new WORLD: lines, updating cached state."""
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return []

        if size < self._pos:
            # Truncated: the game relaunched.
            self.reset()

        out: List[str] = []
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._pos)
                chunk = fh.read()
                self._pos = fh.tell()
        except OSError:
            return []

        for line in chunk.splitlines():
            if SCAN_PREFIX in line:
                out.append(line[line.index(SCAN_PREFIX):].strip())
                continue
            if COMBAT_PREFIX in line:
                combat = line[line.index(COMBAT_PREFIX):].strip()
                out.append(combat)
                if combat.startswith("COMBAT:ready"):
                    self.session_live = True
                continue
            if INVEN_PREFIX in line:
                inven = line[line.index(INVEN_PREFIX):].strip()
                out.append(inven)
                if inven.startswith("INVEN:ready"):
                    self.session_live = True
                continue
            if SKILLDEX_PREFIX in line:
                out.append(line[line.index(SKILLDEX_PREFIX):].strip())
                self.session_live = True
                continue
            if CHAR_PREFIX in line:
                # Absorbed here rather than passed on. These are numbers for
                # the character screen to read out when asked, not events, and
                # the default for an unrecognised line is to speak it -- which
                # would read five rows of raw digits aloud.
                self.sheet.handle(line[line.index(CHAR_PREFIX):].strip())
                self.session_live = True
                continue
            if PREFIX not in line:
                continue
            line = line[line.index(PREFIX):].strip()
            out.append(line)

            if line.startswith("WORLD:ready"):
                self.session_live = True
                self.ready_count += 1
                continue

            m = _DUDENAME_RE.match(line)
            if m:
                # Absorbed rather than passed on: it is a fact to keep, not an
                # event to announce. Nobody wants their own name read out every
                # time they walk through a door.
                self.player_name = m.group(1).strip() or None
                self.session_live = True
                continue

            m = _MODE_RE.match(line)
            if m:
                self.game_mode = int(m.group(1))
                self.session_live = True
                if not (self.game_mode & MODE_CHARSCREEN):
                    # Dropped on the way out, so it cannot outlive the screen it
                    # describes. Rolling a NEW character in the same session
                    # would otherwise inherit the old one's numbers, and the
                    # creation editor is precisely where the reader must fall
                    # back on the editor's own working copy.
                    self.sheet = charsheet.Sheet()
                continue

            m = _CURSOR_RE.match(line)
            if m:
                self.cursor_mode = int(m.group(1))
                self.session_live = True
                continue

            m = _HEX_RE.match(line)
            if m:
                self.last_hex = HexReading(
                    tile=int(m.group(1)),
                    distance=int(m.group(2)),
                    contents=m.group(3).strip(),
                )
        return out
