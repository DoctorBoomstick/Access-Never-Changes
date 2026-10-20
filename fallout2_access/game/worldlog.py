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

from . import charsheet, screens
from ..i18n import tr
from .. import words
from .. import i18n

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
#
# "WORLD:hex 19850 dist 3 : empty|exit:Exit to Downtown|"
# An exit grid on the hex comes after the names, in a field marked "exit:" so
# that stray engine output after the first bar can never be taken for one. It
# is kept out of the names because every name is something a click aims at,
# and an exit is ground to walk onto.
#
# "WORLD:hex 19850 dist 3 : Locker|roof|"
# A roof over the hex is the last field, for the same reason.
_HEX_RE = re.compile(r"WORLD:hex\s+(\d+)\s+dist\s+(\d+)\s*:\s*([^|]*)"
                     r"(?:\|(?:exit:([^|]*)\|)?(roof\|)?)?")
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


# "WORLD:weapon 1|Pipe Rifle|1|6|10|10mm JHP|6|5|6|6|0|0|4|Sharpened Spear|"
#
#   hand, name, is a weapon, rounds loaded, magazine size, ammo name,
#   mode 1, its AP cost, mode 2, its AP cost, the engine's attack type,
#   burst size, minimum strength, what the other hand holds.
#
# Names can hold anything except a pipe, including the empty string -- an empty
# hand and an unnamed ammunition both come through as nothing at all, and both
# are real answers rather than parse failures.
_WEAPON_RE = re.compile(
    r"WORLD:weapon\s+(-?\d+)\|([^|]*)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|([^|]*)\|"
    r"(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|([^|]*)\|"
)

# What the engine's attack-mode numbers mean, from sfall's ATTACK_MODE_ list.
#
# **These words are the mod's, and they were looked for in the game first.**
# Every one of the 22 message lists the engine had loaded was enumerated and
# searched -- with `find_message_list_globals`, the same reader that gets skill
# and stat names -- for "single", "burst", "aimed", "reload" and the rest. Not
# one of them holds a bare mode label. The interface bar does not print those
# words; it draws the weapon and its action point cost, and the mode is carried
# by the picture. So there is no engine string to quote, and the choice is
# between the mod's own words and saying nothing at all.
#
# That search was worth doing rather than assuming, and it also settled a
# neighbouring question: pro_item.msg IS loaded and readable, and it is where
# the minimum-strength figure lives -- "This is a hand-made single shot rifle.
# Min ST: 5." So that number was dropped from this readout instead of being
# repeated here in words of our own.
#
# **This is not a new kind of debt.** Nearly everything this readout says
# outside the item and ammunition names is already the mod's English -- "empty",
# "Both hands empty", "Not a weapon". The fix for the whole of it is a string
# table for the mod, not silence in one corner of it, and these nine live here
# in one obvious place so that table has somewhere to start.
def attack_mode(mode: int) -> str:
    """An item's attack type, in words; "" for none or one with no name."""
    return {
        1: tr("attack.punch", "punch"), 2: tr("attack.kick", "kick"),
        3: tr("attack.swing", "swing"), 4: tr("attack.thrust", "thrust"),
        5: tr("attack.throw", "throw"), 6: tr("attack.single", "single shot"),
        7: tr("attack.burst", "burst"), 8: tr("attack.flame", "flame"),
    }.get(mode, "")


def ap_cost(ap: int) -> str:
    return tr("attack.ap", "{ap} AP", ap=ap)


def _mode_words(mode: int, ap: int, burst: int) -> Optional[str]:
    """One firing mode and what it costs, or None if there is no such mode."""
    name = attack_mode(mode)
    if not name:
        return None
    if mode == 7 and burst > 0:
        name = tr("attack.burst_of", "burst of {rounds}", rounds=burst)
    if ap > 0:
        return "{}, {}".format(name, ap_cost(ap))
    return name


# "WORLD:ammo 10|10|" -- rounds now in the gun, and what it holds.
_AMMO_RE = re.compile(r"WORLD:ammo\s+(-?\d+)\|(-?\d+)\|")


def ammo_line(line: str) -> Optional[str]:
    """Say that a gun was reloaded, and to what.

    The script emits this only when the count goes UP, so this is never firing
    and never a weapon swap -- it is the one ammunition event a player cannot
    otherwise confirm. Fallout puts reload in the same rotation as the firing
    modes and gives no feedback a blind player can read, which is exactly how
    the forum thread that started this went: the poster had reloaded
    successfully three times and could not tell.

    It reports the reading rather than the intention, so it covers the reload
    key, the engine's own reload mode and dragging ammunition onto the gun
    without knowing which of them happened.
    """
    m = _AMMO_RE.match(line)
    if not m:
        return None
    ammo, capacity = int(m.group(1)), int(m.group(2))
    if capacity > 0:
        return tr("weapon.reloaded_of", "Reloaded. {rounds} of {capacity}.",
                  rounds=ammo, capacity=capacity)
    return tr("weapon.reloaded", "Reloaded. {rounds}.", rounds=ammo)


def weapon_line(line: str) -> Optional[str]:
    """Turn a WORLD:weapon line into the sentence to say, or None.

    The order is the order the questions get asked in a fight: what am I
    holding, is it loaded, and what does pulling the trigger do. Everything
    else -- burst size, minimum strength -- rides inside those answers rather
    than being listed after them.

    **"Empty" is said as a word, not as a zero.** "Pipe Rifle, 0 of 10" is a
    sentence a listener has to finish themselves, and the moment it matters is
    the moment there is something biting them. The same reason the count is
    given at all: a sighted player reads it off a green bar without looking
    away from the fight.

    An item that is not a weapon still gets an answer. The key means "what is in
    my hand", and answering only for guns would make it silent exactly when the
    player has picked up something they cannot identify.
    """
    m = _WEAPON_RE.match(line)
    if not m:
        return None
    (_hand, name, is_weapon, ammo, capacity, ammo_name,
     mode1, ap1, mode2, ap2, _attack_type, burst, _min_st,
     other) = m.groups()
    name, ammo_name, other = name.strip(), ammo_name.strip(), other.strip()

    if not name:
        # Nothing in the active hand. Where the other hand's contents are named
        # because "your hands are empty" would be wrong and unhelpful in the
        # common case of having simply not switched hands.
        if other:
            return tr("weapon.other_hand", "Nothing in your active hand. {item} is in "
                      "the other one. Press b to swap.", item=other)
        return tr("weapon.hands_empty", "Both hands empty.")

    if not int(is_weapon):
        return tr("weapon.not_weapon", "{item}. Not a weapon.", item=name)

    parts = [name]
    capacity, ammo = int(capacity), int(ammo)
    if capacity > 0:
        if ammo <= 0:
            parts.append(tr("weapon.empty", "empty"))
        else:
            parts.append(words.of(ammo, capacity))
        if ammo_name:
            parts.append(ammo_name)
    said = ["{}.".format(", ".join(parts))]

    burst = int(burst)
    modes = [_mode_words(int(mode1), int(ap1), burst),
             _mode_words(int(mode2), int(ap2), burst)]
    modes = [w for w in modes if w]
    # The second mode is only worth saying when it is a different one. Plenty of
    # weapons carry the same number twice, and "single shot, then single shot"
    # is noise on the readout that has to be quick.
    if len(modes) == 2 and modes[0] == modes[1]:
        modes = modes[:1]
    if modes:
        # Only the first letter. `str.capitalize` lowercases everything after
        # it, which turned "5 AP" into "5 ap" -- and a screen reader says those
        # two quite differently.
        said.append("{}.".format(
            ". ".join(w[0].upper() + w[1:] for w in modes)))
    # Minimum strength is deliberately NOT here. It is printed in the weapon's
    # own description, which this mod already reads aloud, and a readout meant
    # to be pressed mid-fight should not repeat something the examine text
    # already says at length.
    return " ".join(said)


# Said after what is on a hex with a roof over it.
def roofed() -> str:
    return tr("hex.roofed", "roofed")

# "WORLD:light 0|26214|0|0|3|": the hex's own light, the map's ambient light,
# whether the hex is yours, the light you give off, and how far away it is.
_LIGHT_RE = re.compile(r"WORLD:light (-?\d+)\|(-?\d+)\|(\d+)\|(-?\d+)\|(\d+)\|")

FULL_LIGHT = 0x10000

# determine_to_hit (0x004246FB on): when you attack, the light on the target
# costs this much, at or below each level. A weapon with the Night Sight perk
# ignores it, which is the weapon's business and not the hex's.
LIGHT_PENALTIES = ((0x6666, 40, "very_dark"), (0x9999, 25, "dark"),
                   (0xCCCC, 10, "dim"))


def light_word(which: str) -> str:
    return {"very_dark": tr("light.very_dark", "very dark"),
            "dark": tr("light.dark", "dark"),
            "dim": tr("light.dim", "dim")}[which]


def visible_light(own: int, ambient: int, yours: bool, glow: int) -> int:
    """The light the engine counts for whoever stands on the hex.

    obj_get_visible_light (0x0048AD04): the hex's own light, less your own glow
    if it is your hex, but never below the map's ambient, never above full.
    """
    lit = own - glow if yours else own
    return max(0, min(FULL_LIGHT, max(lit, ambient)))


def _hexes(n: int) -> str:
    return words.hexes(n)


def _steps(n: int) -> str:
    if n == 1:
        return tr("route.one_step", "1 step")
    return tr("route.steps", "{count} steps", count=n)


# The pairs a hex grid zigzags between to go straight up or down the screen.
_NORTH = frozenset((0, 5))
_SOUTH = frozenset((2, 3))

# Turns said before "and so on". Past this, a list of directions stops being a
# thing anyone can hold in their head, and walking it is the better offer.
ROUTE_TURNS_SAID = 6


def route_turns(runs: List[tuple]) -> List[tuple]:
    """Runs of one direction, as (name, steps), with zigzags said as north/south.

    A hex grid has no north: straight up the screen is north-east, north-west,
    north-east, by turns, and saying each of those would be a list of ones. Three
    or more runs alternating between the two are one leg north (or south).
    """
    from ..words import direction
    out: List[tuple] = []
    i = 0
    while i < len(runs):
        d, n = runs[i]
        pair = _NORTH if d in _NORTH else _SOUTH if d in _SOUTH else None
        if pair is not None:
            j = i
            total = 0
            while j < len(runs) and runs[j][0] in pair:
                total += runs[j][1]
                j += 1
            if j - i >= 3:
                out.append((words.compass(0, -1 if pair is _NORTH else 1), total))
                i = j
                continue
        out.append((direction(d) if 0 <= d < 6 else tr("route.on", "on"), n))
        i += 1
    # Neighbours that came out the same, a north after a north, are one leg.
    merged: List[tuple] = []
    for name, n in out:
        if merged and merged[-1][0] == name:
            merged[-1] = (name, merged[-1][1] + n)
        else:
            merged.append((name, n))
    return merged


def _parse_runs(text: str) -> List[tuple]:
    runs = []
    for part in text.split(","):
        if "*" not in part:
            continue
        d, _, n = part.partition("*")
        try:
            runs.append((int(d), int(n)))
        except ValueError:
            continue
    return runs


def route_line(line: str) -> Optional[str]:
    """Shift and slash, or Control and slash: the way there, or how walking it went.

    Most of these are answers to a key, so they are worded as answers. The
    ones that are not news -- a search starting, a walk found again after the
    engine strayed from it -- say nothing.
    """
    if not line.startswith("WORLD:route "):
        return None
    fields = line[len("WORLD:route "):].split("|")
    kind = fields[0]
    rest = fields[1:]
    if kind == "way" and len(rest) >= 6:
        try:
            walk, steps, dist, doors, runs = (int(x) for x in rest[:5])
        except ValueError:
            return None
        if walk == 2:
            return None
        doors_said = ""
        if doors == 1:
            doors_said = " " + tr("route.one_door", "Through 1 door.")
        elif doors:
            doors_said = " " + tr("route.doors", "Through {count} doors.", count=doors)
        if walk:
            return tr("route.walking", "Walking there, {steps}.",
                      steps=_steps(steps)) + doors_said
        turns = route_turns(_parse_runs(rest[5]))
        legs = [tr("route.leg", "{direction} {count}", direction=name, count=n)
                for name, n in turns[:ROUTE_TURNS_SAID]]
        said = tr("route.summary", "{steps}, {distance} straight.",
                  steps=_steps(steps), distance=_hexes(dist))
        if legs:
            way = ", ".join(legs)
            if len(turns) > ROUTE_TURNS_SAID or runs > ROUTE_RUNS_SENT:
                way += ", " + tr("route.and_on", "and on")
            said += " " + way[:1].upper() + way[1:] + "."
        return said + doors_said
    if kind == "here":
        return tr("route.here", "You are already there.")
    if kind == "combat":
        return tr("route.combat", "Not during combat: walking would spend your "
                  "action points. Shift and slash says the way.")
    if kind == "none":
        return tr("route.none", "No way there from here.")
    if kind == "door" and rest:
        return tr("route.door", "Stopped at {door}. The look cursor is on it.",
                  door=rest[0] or tr("route.a_door", "a door"))
    if kind == "blocked" and rest:
        return tr("route.blocked", "Stopped: {thing} is in the way.",
                  thing=rest[0] or tr("route.something", "something"))
    if kind == "end" and rest:
        return route_end(rest[0])
    return None


# What the script's ROUTE_RUNS lets through. More turns than this were cut.
ROUTE_RUNS_SENT = 40

# How a walk ended, where that is worth saying. Doors and blockers have said
# so already, on their own lines; a screen opening speaks for itself.
def route_end(how: str) -> Optional[str]:
    return {
        "arrived": tr("route.arrived", "Arrived."),
        "cancel": tr("route.stopped", "Stopped."),
        "combat": tr("route.stopped_combat", "Stopped for combat."),
        "stuck": tr("route.stuck", "Stopped: cannot get any further."),
    }.get(how)


def light_line(line: str) -> Optional[str]:
    """Shift and 1: how much light is on the look cursor's hex, and what it does.

    The penalty is what makes this worth knowing -- standing a target in the
    dark costs your shot, and a flare dropped beside it gives it back.
    """
    m = _LIGHT_RE.match(line)
    if not m:
        return None
    own, ambient, yours, glow, _dist = (int(g) for g in m.groups())
    lit = visible_light(own, ambient, bool(yours), glow)
    percent = (lit * 100 + FULL_LIGHT // 2) // FULL_LIGHT
    said = tr("light.percent", "{percent} percent light", percent=percent)
    for limit, penalty, word in LIGHT_PENALTIES:
        if lit <= limit:
            said = "{}, {}".format(said, tr("light.penalty", "{level}: minus {penalty} to hit",
                                            level=light_word(word), penalty=penalty))
            break
    else:
        said = "{}, {}".format(said, tr("light.bright", "bright"))
    if own - (glow if yours else 0) > ambient:
        # Lit by something of its own: a lamp, a fire, a flare.
        said = "{}, {}".format(said, tr("light.nearby", "lit from nearby"))
    return said + "."


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
    parts = [tr("status.health", "Health {hp} of {most}.", hp=hp, most=max_hp)]
    if fighting:
        parts.append(tr("combat.ap_of", "{ap} of {most} action points.",
                        ap=ap, most=max_ap))
    else:
        parts.append(tr("status.ap", "{ap} action points.", ap=max_ap))
    parts.append(tr("status.armor_class", "Armor class {ac}.", ac=ac))
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
    said = [tr("status.level", "Level {level}.", level=level)]
    needed = charsheet.next_level_experience(level)
    if needed is not None and needed > experience:
        said.append(tr("status.to_next_level", "{experience} experience to the next level.",
                       experience=needed - experience))
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
            return None, False, tr("use.other_hand", "Your active hand is empty. "
                                   "{item} is in the other hand.", item=other)
        return None, False, tr("use.hands_empty", "Your hands are empty. Ready something first.")
    weapon = m.group(2) == "1"
    if weapon:
        return name, True, tr("use.weapon", "Using {item}, a weapon.", item=name)
    return name, False, tr("use.item", "Using {item}.", item=name)


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
        return tr("menu.nothing", "Nothing there to act on.")
    if what == "empty":
        return tr("menu.empty", "{thing}. Nothing you can do to it.",
                  thing=m.group(2).strip() or tr("inventory.that", "That"))
    if what == "closed":
        return tr("inventory.closed", "Closed.")
    if what == "gone":
        return tr("menu.gone", "That is no longer there.")
    if what == "noroute":
        return tr("menu.unsupported", "{action}. The game offers that, but the mod "
                  "has no way to do it yet.",
                  action=say_script(m.group(2).strip()).capitalize())
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
            return tr("menu.wrong_thing", "Read the wrong thing: pointed at {aimed} "
                      "but the game answered for {got}. Try again.",
                      aimed=aimed_at, got=name)
        return tr("inventory.menu", "{name}. {count} actions. {first}, {position}.",
                  name=name, count=count, first=say_script(first).capitalize(),
                  position=words.of(1, count))
    if what == "at":
        label, index, count = (m.group(2).strip(), m.group(3).strip(),
                               m.group(4).strip())
        return "{}, {}.".format(_first_up(say_script(label)), words.of(index, count))
    if what == "sub":
        # A second list under one entry: the skills under "use a skill on it",
        # the body parts under an aimed "attack it".
        kind, count, first = (m.group(2).strip(), m.group(3).strip(),
                              m.group(4).strip())
        return "{} {}, {}.".format(sub_question(kind), _first_up(first),
                                   words.of(1, count))
    return None


def sub_question(kind: str) -> str:
    if kind == "skill":
        return tr("menu.which_skill", "Which skill?")
    if kind == "aim":
        return tr("menu.aim_where", "Aim where?")
    return tr("menu.choose", "Choose.")


# Every fixed phrase the in-game scripts send to be spoken. The scripts go on
# writing English -- it is the protocol, and parts of it are parsed back here
# -- and these are translated only on the way out. gl_world.ssl's menu_label,
# facing_name, obj_label, describe_cursor and the exit grid labels, and
# gl_inven.ssl's menu entries.
i18n.script_words({
    "act.attack": "attack it",
    "act.use": "use it",
    "act.look": "look at it",
    "act.use_item_on": "use an item on it",
    "act.use_skill": "use a skill on it",
    "act.talk": "talk to it",
    "act.drop": "drop something here",
    "act.rotate": "turn it",
    "act.unload": "unload it",
    "act.cancel": "cancel",
    "act.drop_it": "drop it",
    "hex.you": "you",
    "hex.yourself": "yourself",
    "hex.empty": "empty",
    "hex.blocked": "blocked",
    "hex.dead": "dead",
    "hex.locked": "locked",
    "hex.open": "open",
    "hex.exit": "Exit",
    "hex.exit_world": "Exit to the world map",
    "hex.exit_town": "Exit to the town map",
    "dir.ne": "north east",
    "dir.e": "east",
    "dir.se": "south east",
    "dir.sw": "south west",
    "dir.w": "west",
    "dir.nw": "north west",
})

_ACTION_N = re.compile(r"action (\d+)$")
_FACING = re.compile(r"facing (.+)$")
_EXIT_TO = re.compile(r"Exit to (.+)$")


def say_script(text: str) -> str:
    """A phrase the in-game script sent, in the player's language.

    The scripts write English, and Python parses some of it back -- so the
    words stay English all the way here and are only translated on their way
    out. See i18n.say_script. Three carry a value, and are matched by shape.
    """
    said = i18n.say_script(text)
    if said is not text:
        return said
    m = _ACTION_N.match(text)
    if m:
        return tr("act.unknown", "action {code}", code=m.group(1))
    m = _FACING.match(text)
    if m:
        return tr("hex.facing", "facing {direction}",
                  direction=i18n.say_script(m.group(1)))
    m = _EXIT_TO.match(text)
    if m:
        return tr("hex.exit_to", "Exit to {place}", place=m.group(1))
    return text


def say_script_fields(text: str) -> str:
    """`say_script` on each comma-separated field of a readout."""
    return ", ".join(say_script(f.strip()) for f in text.split(","))


def _first_up(text: str) -> str:
    """Capital first letter, the rest untouched -- the game's own names keep
    their capitals, and "45%" stays a number a screen reader says as one."""
    return text[:1].upper() + text[1:]


def attack_line(line: str) -> Optional[str]:
    """WORLD:attack -- an attack from the menu that did not go ahead.

    `aimnow` is the one case the script declines rather than the engine: an
    aimed mode switched on between choosing "attack it" and it running, which
    would have opened the called-shot window from inside the script.
    """
    if line.startswith("WORLD:attack aimnow"):
        return tr("menu.aim_now", "Aimed mode is on now. Choose attack again to pick where.")
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
    if line.startswith("WORLD:pick use|"):
        # U: what to use the item in your hand on.
        fields = line.split("|")
        if len(fields) >= 5:
            item, label, index, count = (f.strip() for f in fields[1:5])
            return tr("pick.use_on", "Use {item} on what? {thing}, {position}.",
                      item=item, thing=label[:1].upper() + label[1:],
                      position=words.of(index, count))
        return None
    m = _PICK_RE.match(line)
    if not m:
        return None
    what = m.group(1)
    if what == "none":
        return tr("pick.nothing", "Nothing here to act on.")
    if what == "closed":
        return tr("pick.cancelled", "Cancelled.")
    if what == "gone":
        return tr("menu.gone", "That is no longer there.")
    if what in ("open", "at"):
        label, index, count = (m.group(2).strip(), m.group(3).strip(),
                               m.group(4).strip())
        said = "{}, {}.".format(say_script(label).capitalize(), words.of(index, count))
        if what == "open":
            # Only on the way in. Repeating it on every step would bury the
            # thing being stepped to.
            said = tr("pick.things_here", "{count} things here. {first}",
                      count=count, first=said)
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
        return tr("use.nothing_there", "Nothing there to use.")
    if what == "try":
        return tr("use.item", "Using {item}.", item=target or tr("use.it", "it"))
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
        return tr("use.ready_first", "Your hands are empty. Ready an item first.")
    if what == "notarget":
        return tr("use.no_target", "Nothing there to use it on.")
    if what == "try":
        return tr("use.on", "Using {item} on {target}.",
                  item=item or tr("use.that", "that"), target=target or tr("use.it", "it"))
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


def aim_at_yourself(reading, cursor_mode, player_name) -> Optional[List[str]]:
    """Are you the thing this click should point at? The name to hunt, or None.

    **Your own hex reports "you", and "you" means the hex holds nothing to
    point at.** That is deliberate and right for almost every click: standing on
    a tile, what you want is the ground, not your own body. So the aim settles
    dead centre on the hex -- which is where your FEET are -- and Fallout picks
    what a click hits by the sprite drawn over that pixel.

    Measured live, with Healing Powder armed and the cursor snapped to the
    player: the engine reported "Wooden Wall" at the hex centre, "Boxes" thirty
    pixels up, and the player fifty-six pixels up. Using a stimpak on yourself
    used it on the wall behind you, silently, because a wall is a perfectly
    ordinary thing for a click to land on.

    The exception is a click that is going to ACT on something -- an item armed
    by the reload key, or a skill armed from the Skilldex. Then you are the
    target, and the aimer already knows how to walk up a sprite until the engine
    agrees it is pointing at a named thing. It could never do it here before,
    for the plain reason that the script asked the engine to ignore the player.

    Returns a list because that is what the aimer's `wanted` takes, and None
    when this is an ordinary click that should go on meaning the ground.
    """
    if reading is None or player_name is None:
        return None
    if reading.distance != 0:
        return None          # not standing on the hex being clicked
    if reading.names():
        return None          # something else is here and was named; aim at that
    if not (cursor_mode == screens.CURSOR_USE_ITEM
            or cursor_mode in screens.SKILL_CURSORS):
        return None          # an ordinary click still means the ground
    return [player_name]


class HexReading(NamedTuple):
    tile: int
    distance: int
    contents: str
    # Where an exit grid on this hex leads, as the script words it, or "".
    exit: str = ""
    # A roof over it: inside a building, or under its eaves.
    roofed: bool = False

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
        if self.exit:
            # "empty, Exit to Downtown" says the same thing twice, badly: the
            # hex is not empty, it is the way out.
            what = self.exit if what == "empty" else "{}, {}".format(what, self.exit)
        # The script's words, translated now that nothing will parse them
        # again. A name the player chose is left alone even if it happens to
        # be one of them.
        what = ", ".join(f if f == player_name else say_script(f)
                         for f in (x.strip() for x in what.split(",")))
        if self.roofed:
            what = "{}, {}".format(what, roofed())
        if self.distance == 0:
            return what
        return "{}, {}".format(what, words.hexes(self.distance))

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
                    exit=(m.group(4) or "").strip(),
                    roofed=bool(m.group(5)),
                )
        return out
