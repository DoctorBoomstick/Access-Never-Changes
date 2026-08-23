"""The character screen of a character who already exists.

This is not the creation editor, and confusing the two is what made the in-game
sheet wrong rather than missing. It is the same panel drawn by the same code, so
the mod's editor reader happily narrates it -- with the wrong numbers.

    the editor reads SPECIAL out of the engine's stat table, which in a loaded
    game is the BASE table. Perception read 8 while the sheet showed 6, because
    healing powder's penalty lives in a separate bonus table.

    the editor COMPUTES skills from SPECIAL, using the formulas that are right
    at creation. They know nothing about tag skills or the points you have
    spent since, so Small Guns computed 37 against a sheet showing 47.

    damage resistance read 0 against a sheet showing 8%, because that is the
    armour and the engine applies it at display time.

Every one of those is a modifier the engine already knows how to total up. So
`gl_world.ssl` asks it -- `get_critter_stat` for the stats, `has_skill` for the
skills, both of which return exactly what the panel is showing -- and this turns
the answer into words.

The words themselves are the game's own. Nothing here ships a name: the stat and
skill names come from `stat.msg` and `skill.msg`, which the mod is already
reading out of the running process, so a translated game reads out translated.
"""

from __future__ import annotations

import re
from typing import List, NamedTuple, Optional

# The ten derived stats, in the order the sheet lists them, paired with the
# stat.msg entry that names each one. Same table the editor uses, because it is
# the same row of the same panel.
DERIVED_MSG = [
    ("Armor Class", 109),
    ("Action Points", 108),
    ("Carry Weight", 112),
    ("Melee Damage", 111),
    ("Damage Resistance", 124),
    ("Poison Resistance", 132),
    ("Radiation Resistance", 131),
    ("Sequence", 113),
    ("Healing Rate", 114),
    ("Critical Chance", 115),
]

# Which of them are percentages on screen. Saying "damage resistance 8" where
# the sheet says "8%" is a small wrongness that a player cannot check.
DERIVED_PERCENT = {"Damage Resistance", "Poison Resistance",
                   "Radiation Resistance", "Critical Chance"}

# critter_state's bits, and the condition each one is. The engine's own flags;
# the English is ours, because these have no .msg entries of their own that the
# mod can reach -- see the note on `conditions`.
STATE_FLAGS = [
    (0x001, "knocked out"),
    (0x002, "knocked down"),
    (0x004, "crippled left leg"),
    (0x008, "crippled right leg"),
    (0x010, "crippled left arm"),
    (0x020, "crippled right arm"),
    (0x040, "blinded"),
]

# The condition box, row by row, in the order the panel lists them -- which is
# also the order the editor's own arrow keys walk, indices 10 to 17.
#
# Confirmed against a sighted reading of a live sheet: Hit Points, Poisoned,
# Radiated, Eye Damage, then the four crippled limbs right arm first. The engine
# supplies the row's LABEL through the editor's name pointer, so only the state
# is wanted here -- the words stay the game's.
#
# "hp" is the first row and is a number rather than a yes or no.
CONDITION_ROWS = ["hp", "poison", "rads", 0x40, 0x20, 0x10, 0x08, 0x04]


def condition_value(sheet, position: int) -> Optional[str]:
    """"Yes" or "no" for one row of the condition box, or the hit points.

    The panel lights a row when it applies and leaves it dim when it does not,
    and a dim row is information: "am I still poisoned?" is a question the box
    answers at a glance and the mod could not answer at all. Stepping onto a row
    and hearing only its name tells you the row exists, which you knew.
    """
    if not 0 <= position < len(CONDITION_ROWS):
        return None
    which = CONDITION_ROWS[position]
    if which == "hp":
        if sheet.hp is None or sheet.max_hp is None:
            return None
        return "{} of {}".format(sheet.hp, sheet.max_hp)
    if which == "poison":
        return "yes" if sheet.poison else "no"
    if which == "rads":
        return "yes" if sheet.rads else "no"
    return "yes" if sheet.state & which else "no"


# skill.msg numbers the eighteen skill names from 100.
SKILL_NAME_MSG = 100

_SKILLDEX = re.compile(r"SKILLDEX:list (-?\d+)\|((?:-?\d+,-?\d+\|)+)")
_SNEAK = re.compile(r"SKILLDEX:sneak (-?\d+)\|")


def sneak_line(line: str) -> Optional[str]:
    """Whether you are sneaking, as the Skilldex shows it.

    Sneak is the only entry on that panel with no cursor of its own. Arming
    Lockpick changes the cursor and the mod announces the change, so you know it
    took; pressing 1 changes nothing audible, and the engine prints nothing
    either -- measured, by toggling it twice with the game's own message window
    under watch, which stayed empty both times. So the panel is asked instead,
    which is where a sighted player reads it.
    """
    m = _SNEAK.match(line)
    if not m:
        return None
    return "Sneaking." if m.group(1) != "0" else "Not sneaking."


def skilldex_line(line: str, names) -> Optional[str]:
    """Turn a SKILLDEX:list line into the sentence to say, or None.

    The panel was unreachable in the way that is easiest to miss: opening it
    announced "skilldex" and stopped, so the player knew a panel existed and
    nothing about what was on it. Most of its entries at least change the cursor
    when armed, and that IS announced -- but Sneak is a toggle with no cursor of
    its own, so pressing 1 was completely silent.

    The key number is the position in the panel, not the skill's index: the
    Skilldex lists Sneak, Lockpick, Steal, Traps, First Aid, Doctor, Science,
    Repair, whose indices are 8, 9, 10, 11, 6, 7, 12, 13. `names` is skill.msg,
    read out of the running game, so these arrive translated.
    """
    m = _SKILLDEX.match(line)
    if not m:
        return None
    # Sneak's state travels on this line rather than a second one. Sent
    # separately it was a second announcement, and both are marked as answers to
    # a keypress, so it cut the list off mid-word -- the panel read out as
    # nothing but "Not sneaking." and the eight skills were never heard.
    said = ["Skilldex.", "Sneaking." if m.group(1) != "0" else "Not sneaking."]
    for key, pair in enumerate(m.group(2).rstrip("|").split("|"), start=1):
        index, _, level = pair.partition(",")
        try:
            name = names.get(SKILL_NAME_MSG + int(index)) or "skill {}".format(index)
        except ValueError:
            continue
        said.append("{} {}, {} percent.".format(key, name, level))
    return " ".join(said) if len(said) > 1 else None


_STATS = re.compile(r"CHAR:stats " + r"(-?\d+)\|" * 7)
_DERIVED = re.compile(r"CHAR:derived " + r"(-?\d+)\|" * 10)
_COND = re.compile(r"CHAR:cond " + r"(-?\d+)\|" * 5)
_SKILLS = re.compile(r"CHAR:skills " + r"(-?\d+)\|" * 18)
_PC = re.compile(r"CHAR:pc " + r"(-?\d+)\|" * 3)


class Sheet:
    """What the engine says is on the character screen.

    Filled in a line at a time as the script reports it. Deliberately tolerant
    of a partial fill: the five lines arrive across a frame or two, and half a
    sheet read out is better than silence while the rest lands.
    """

    def __init__(self) -> None:
        self.special: List[int] = []
        self.derived: List[int] = []
        self.skills: List[int] = []
        self.hp: Optional[int] = None
        self.max_hp: Optional[int] = None
        self.poison: Optional[int] = None
        self.rads: Optional[int] = None
        self.state: int = 0
        self.level: Optional[int] = None
        self.experience: Optional[int] = None
        self.unspent: Optional[int] = None

    @property
    def ready(self) -> bool:
        return bool(self.special and self.derived and self.skills)

    def handle(self, line: str) -> bool:
        """Absorb one CHAR: line. True if it was one of ours."""
        m = _STATS.match(line)
        if m:
            self.special = [int(g) for g in m.groups()]
            return True
        m = _DERIVED.match(line)
        if m:
            self.derived = [int(g) for g in m.groups()]
            return True
        m = _SKILLS.match(line)
        if m:
            self.skills = [int(g) for g in m.groups()]
            return True
        m = _COND.match(line)
        if m:
            (self.hp, self.max_hp, self.poison,
             self.rads, self.state) = (int(g) for g in m.groups())
            return True
        m = _PC.match(line)
        if m:
            self.level, self.experience, self.unspent = (
                int(g) for g in m.groups())
            return True
        return line.startswith("CHAR:")


def next_level_experience(level: Optional[int]) -> Optional[int]:
    """How much experience the next level wants, as the sheet's box shows it.

    **Computed, because there is nothing to read.** The level box prints it, so
    the engine knows it, but it is not a table sitting in memory: the module was
    scanned for the sequence 1000, 3000, 6000 -- with and without a leading
    zero -- and there is no such array. Fallout works it out each time, by a
    rule that has not changed since the first game: reaching level L costs L
    times L minus one, halved, times a thousand. So from here, the next one
    wants that with L plus one.

    Checked against a live sheet at level 1, which prints "Next Level: 1,000",
    and that is the only point it has been checked at. This is arithmetic rather
    than a reading, so a mod that retables the progression would make this
    number wrong while everything around it stayed right -- the same caveat the
    creation-time skill formulas carry, and worth the same suspicion.
    """
    if level is None or level < 1:
        return None
    return (level + 1) * level // 2 * 1000


def conditions(sheet: Sheet) -> List[str]:
    """What is wrong with you, as the sheet's condition box lists it.

    Only what is actually set. The panel shows a fixed column of labels and
    lights up the ones that apply, so reading the whole column out would tell a
    player they are blind, poisoned and missing both legs when they are fine.

    These few words are the mod's own rather than the game's, which is the
    exception this project makes for scaffolding it cannot reach: the flags come
    from `critter_state` as a bitmask, and the engine's own labels for them live
    in the character screen's art rather than in a message list.
    """
    out: List[str] = []
    for bit, name in STATE_FLAGS:
        if sheet.state & bit:
            out.append(name)
    if sheet.poison:
        out.append("poisoned")
    if sheet.rads:
        out.append("radiated")
    return out
