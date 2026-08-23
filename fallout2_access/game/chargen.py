"""A read-only view of the character creation screen.

Every address here was confirmed against the live process (see HARNESS.md);
none were borrowed from a reimplementation. The index map in particular was
*measured* by walking the editor, because the real executable's ranges differ
from fallout2-ce's and include two genuine non-contiguous outliers.

Where values come from
----------------------
- SPECIAL and spare character points are read straight from memory.
- Names and descriptions are read from the game's own loaded .msg lists, so
  translations and text-replacing mods work without changes here.
- Skill percentages and derived stats are *computed*. The engine does not store
  them anywhere -- a 285 MB search found them at no width -- it recalculates
  them at render time. The formulas below were each checked against a live
  screen capture and all 29 matched exactly.

  The one caveat worth stating plainly: because these are computed rather than
  read, a mod that changes the skill or derived-stat formulas (sfall can, via
  skills.ini) would make these numbers wrong while the names stayed right. The
  names are mod-proof; these particular numbers are not.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional, Tuple

from ..memory.process import Process
from ..msg.memlist import read_message_list

# -- confirmed addresses -----------------------------------------------------

SEL_ADDR = 0x005709EC          # characterEditorSelectedItem
SPECIAL_ADDR = 0x0051C394      # 7 x i32, Strength..Luck
CHAR_POINTS_ADDR = 0x00518538  # unspent character points
NAME_ADDR = 0x0056D75C         # char buffer, the character's name
TAGS_ADDR = 0x00668070         # 4 x i32 skill indices, -1 when empty
TRAITS_ADDR = 0x0066BE40       # 2 x i32 trait indices, -1 when empty

MAX_TAGS = 3                   # at creation; a 4th comes from the Tag! perk
MAX_TRAITS = 2

# Age and sex, and how they were found.
#
# SPECIAL_ADDR is not a seven-entry array. It is the head of the engine's WHOLE
# stat array, and the rest of it was sitting there in the open the entire time.
# Read past the seven and every value identifies itself by its own formula, on a
# character with 5 in everything:
#
#     [7]  30   max hit points     15 + 2*EN + ST
#     [8]   7   action points      5 + AG/2
#     [12] 150  carry weight       25 + 25*ST
#     [29] 100  EMP resistance     humans are immune
#     [31]  10  radiation resist   2*EN
#     [32]  25  poison resist      5*EN
#     [33]  25  AGE                the default a new character starts at
#     [34]   0  SEX                0 male, 1 female
#
# Six formulas landing exactly is what makes [33] and [34] a measurement rather
# than a guess -- and it matters, because 32 and 33 both read 25 on this
# character, and picking the wrong one of that pair would have produced an "age"
# that quietly tracked Endurance.
#
# Then confirmed live, which is the standard everything else here is held to:
# with the sex dialog open, Right made [34] read 1 and Left made it read 0
# again; with the age dialog open, Right stepped [33] 25 -> 26 -> 27 and Escape
# put it back to 25.
STAT_AGE = 33
STAT_SEX = 34
AGE_ADDR = SPECIAL_ADDR + 4 * STAT_AGE
SEX_ADDR = SPECIAL_ADDR + 4 * STAT_SEX

# editor.msg: the game's own words for the two, so a translation carries them.
SEX_MSG = {0: 107, 1: 108}     # MALE, FEMALE

# The three dialogs behind the N, A and S keys.
#
# Not one of them needed a pointer, which is the whole finding. The buttons that
# open them carry no key code at all -- the editor's button table reads press=-1
# for all three -- so they looked mouse-only, and the mod had no way in. They
# are not: the editor handles N, A and S itself, arrow keys work inside age and
# sex, and Escape cancels cleanly. Measured on a live editor.
#
# Each dialog is a 139x72 panel that opens directly beneath the button that
# raised it, so which one is up is read off where it sits. The offsets are the
# editor's own button positions, which are constants in the art rather than
# anything that moves with resolution; only the 640x480 panel's origin moves,
# and that is read from the window list rather than assumed.
DIALOG_SIZE = (139, 72)
EDITOR_PANEL = (640, 480)

# Offset from the editor panel's left edge to each dialog's left edge, measured:
# name 17, age 154, sex 235. Split between them rather than matched exactly --
# the point is to tell three well-separated things apart, not to re-measure.
DIALOG_BOUNDS = ((90, "name"), (200, "age"), (10 ** 6, "sex"))

COND_NAME_PTR = 0x005700F4     # char*, tracks the condition section only
TRAIT_NAME_PTR = 0x005705B8    # char*, tracks the trait section only
TRAIT_DESC_PTR = 0x005705CC    # char*, ditto

MSG_EDITOR = 0x0056FCA8
MSG_STAT = 0x0066817C
MSG_SKILL = 0x00668080
MSG_TRAIT = 0x0066BE38

# -- measured index map ------------------------------------------------------
# Tab cycles these five sections. The order within each is the order the editor
# actually visits on Down, including the outliers 83 and 94 (both verified
# stable across ~200 samples; 94 is Sex Appeal).

SPECIAL_INDICES = [0, 1, 2, 3, 4, 5, 6]
# Name, age and sex. Measured on the in-game sheet by tabbing onto the row and
# reading the indices the mod could not name -- 7, 8 and 9, which is the gap
# between SPECIAL and the condition block that had been sitting unexplained in
# this map since it was first written.
#
# During creation these three are buttons that open dialogs, and the dialogs are
# read separately; here they are simply a row to be read.
IDENTITY_INDICES = [7, 8, 9]
CONDITION_INDICES = [10, 11, 12, 13, 14, 15, 16, 17]
DERIVED_INDICES = [18, 19, 20, 21, 22, 23, 83, 24, 25, 26]
SKILL_INDICES = list(range(28, 46))
TRAIT_INDICES = [55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 94, 69, 70]

# The Perks, Karma and Kills box, which only a character who exists has.
#
# Measured by walking the in-game sheet and reading the index the mod could not
# name against the label the trait pointer was holding at that moment:
#
#     71  Perks          (with its description in the condition pointer)
#     48  Karma
#     46  Kills          -- one row per creature, "Giant Ants Kills"
#
# 47, 54 and 135 turn up in the same three tabs and are almost certainly the
# rest of that box, but they were not caught with a label attached, so they are
# listed here to be READ rather than to be named: the label comes from the
# pointer at the time, and an entry whose pointer says nothing sensible falls
# back to its number instead of being guessed at.
RECORD_INDICES = [46, 47, 48, 54, 71, 135]

SECTION_ORDER = ["special", "identity", "condition", "derived", "skill",
                 "trait", "record"]

_SECTION_OF: Dict[int, Tuple[str, int]] = {}
for _name, _seq in (
    ("special", SPECIAL_INDICES),
    ("identity", IDENTITY_INDICES),
    ("condition", CONDITION_INDICES),
    ("derived", DERIVED_INDICES),
    ("skill", SKILL_INDICES),
    ("trait", TRAIT_INDICES),
    ("record", RECORD_INDICES),
):
    for _pos, _idx in enumerate(_seq):
        _SECTION_OF[_idx] = (_name, _pos)

# stat.msg message numbers for the seven SPECIAL stats and their descriptions.
SPECIAL_NAME_MSG = [100, 101, 102, 103, 104, 105, 106]
SPECIAL_DESC_MSG = [200, 201, 202, 203, 204, 205, 206]

# The word the editor prints beside each SPECIAL value -- Average, Good, Great.
# A sighted player reads it without looking away from the stat, and it was the
# one part of that row the mod never said.
#
# Message 300 + value, for values 1 to 10. Read out of the running game's own
# loaded stat.msg rather than reasoned about: 301 "V. Bad" through 310 "Heroic",
# with "Average" landing on 305, which is the value Fallout starts every stat
# at. Ten words for ten values, and the default in the middle -- that is the
# mapping confirming itself.
#
# **Two tables exist, and this is deliberately not the one on screen.** The
# editor prints from editor.msg 200-209, which is the same ten words truncated
# to fit the panel: "Avrg", "Exclnt", "V.Bad". Dumped from a live editor side by
# side, they line up entry for entry with stat.msg 301-310 -- "Average",
# "Excellent", "V. Bad".
#
# Speaking the untruncated pair is not a departure from "say what is on screen".
# An abbreviation is a pixel-width measure rather than a word: a sighted player
# reads "Avrg" and hears "average" in their head, and nobody wants a screen
# reader saying "avurg". It is the same call `clean()` makes about the bullet in
# front of every dialogue reply -- formatting a sighted player decodes as a
# shape, not something they read aloud. Both tables are the game's own, so a
# translation carries either one; only one of them is a word.
#
# Clamped at both ends. A stat can reach 14 with bonuses and the engine has no
# word past Heroic, so it says Heroic; inventing an eleventh would be inventing
# English the game does not have, which is the one thing this mod refuses to do.
STAT_RATING_BASE = 300
STAT_RATING_MIN = 1
STAT_RATING_MAX = 10


def rating_msg(value: int) -> int:
    """Which stat.msg entry holds the word for this stat value."""
    return STAT_RATING_BASE + max(STAT_RATING_MIN, min(STAT_RATING_MAX, value))

# Derived stats in the order the editor lists them, matching DERIVED_INDICES.
# The label is looked up in stat.msg where a clean equivalent exists.
DERIVED_LAYOUT = [
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


class EditorItem(NamedTuple):
    index: int
    section: str
    position: int
    label: str
    value: Optional[str]
    description: Optional[str]

    def announce(self) -> str:
        parts = [self.label]
        if self.value:
            parts.append(self.value)
        return ", ".join(p for p in parts if p)


class CharGen:
    """Reads character creation state. Never writes."""

    def __init__(self, proc: Process) -> None:
        self.proc = proc
        self._msg_cache: Dict[int, Dict[int, str]] = {}
        # The engine's own answer for a character who already exists, set by the
        # app when the in-game character screen reports one. While it is here it
        # WINS over everything computed below -- see the note on `special`.
        self.sheet = None

    # -- raw state ----------------------------------------------------------

    def selection(self) -> Optional[int]:
        return self.proc.read_i32(SEL_ADDR)

    def _live(self):
        """The engine's report for an existing character, or None.

        Only ever set in a loaded game. During creation there is no character
        to ask about and the editor's own working copy IS the truth, so every
        reading below falls through to memory and the formulas.
        """
        sheet = self.sheet
        return sheet if (sheet is not None and sheet.ready) else None

    def base_special(self) -> List[int]:
        """The seven before anything modified them, straight from memory.

        Kept apart from `special` so the two can be compared. The gap between
        them is what a drug, a perk or a piece of armour is doing to you right
        now, and Fallout puts that on the screen -- a modified stat is drawn in
        a different colour, so a sighted player can see at a glance that the
        number is not the one they built.
        """
        raw = self.proc.read(SPECIAL_ADDR, 7 * 4)
        if raw is None or len(raw) < 28:
            return []
        return [
            int.from_bytes(raw[i * 4:i * 4 + 4], "little", signed=True)
            for i in range(7)
        ]

    def special(self) -> List[int]:
        """The seven, as the screen shows them.

        **Base plus every modifier, once a character exists.** This address is
        the head of the engine's BASE stat table, which is exactly right in the
        editor and quietly wrong afterwards: measured in a live game, Perception
        read 8 here while the sheet on screen said 6, because healing powder's
        penalty is kept in a separate bonus table and added at display time.
        `get_critter_stat` totals all of that, so when the script has reported
        it, that answer wins.
        """
        live = self._live()
        if live:
            return list(live.special)
        return self.base_special()

    def char_points(self) -> Optional[int]:
        return self.proc.read_i32(CHAR_POINTS_ADDR)

    def _ints(self, addr: int, count: int) -> List[int]:
        raw = self.proc.read(addr, count * 4)
        if not raw or len(raw) < count * 4:
            return []
        return [
            int.from_bytes(raw[i * 4:i * 4 + 4], "little", signed=True)
            for i in range(count)
        ]

    def tags(self) -> List[int]:
        """Indices of tagged skills. Empty slots read -1."""
        return [t for t in self._ints(TAGS_ADDR, 4) if t >= 0]

    def traits(self) -> List[int]:
        """Indices of chosen optional traits. Empty slots read -1."""
        return [t for t in self._ints(TRAITS_ADDR, MAX_TRAITS) if t >= 0]

    def name(self) -> Optional[str]:
        return self.proc.read_cstring(NAME_ADDR, 32) or None

    def age(self) -> Optional[int]:
        return self.proc.read_i32(AGE_ADDR)

    def sex(self) -> Optional[int]:
        return self.proc.read_i32(SEX_ADDR)

    def sex_name(self) -> Optional[str]:
        """"Male" or "Female", in the game's own words.

        Falls back to the number rather than to English of our own. An
        unrecognised value is a fact about the game we do not understand, and
        saying "male" about it would be inventing the half we are missing.
        """
        value = self.sex()
        if value is None:
            return None
        text = self._msg(MSG_EDITOR).get(SEX_MSG.get(value, -1))
        return text.capitalize() if text else "sex {}".format(value)

    def dialog(self) -> Optional[str]:
        """Which of the name, age and sex dialogs is open, if any.

        Read from GNW's window list rather than from a flag, for the reason the
        save screen learned the hard way: a window that is open is a fact, and a
        flag somebody set is a promise. The three are told apart by where they
        sit, because each opens directly under the button that raised it.
        """
        from . import uiwindow

        width, height = DIALOG_SIZE
        panel = None
        dialog = None
        for win in uiwindow.live_windows(self.proc):
            if (win.width, win.height) == (width, height):
                dialog = win
            elif (win.width, win.height) == EDITOR_PANEL:
                panel = win
        if dialog is None or panel is None:
            return None
        offset = dialog.left - panel.left
        for limit, name in DIALOG_BOUNDS:
            if offset < limit:
                return name
        return None

    def _msg(self, global_addr: int) -> Dict[int, str]:
        """A loaded message list, cached -- but an EMPTY one is not cached.

        editor.msg is only loaded while the character screen is up. Asked for it
        from the map, the engine answers with nothing, and caching that nothing
        meant the list stayed empty for the rest of the session even once the
        screen was open. The visible symptom was the sheet saying "sex 1"
        instead of "Female", because the fallback had become permanent.
        """
        cached = self._msg_cache.get(global_addr)
        if cached:
            return cached
        lst = read_message_list(self.proc, global_addr)
        found = lst.by_num() if lst else {}
        if found:
            self._msg_cache[global_addr] = found
        return found

    def _ptr_text(self, addr: int, limit: int = 400) -> Optional[str]:
        ptr = self.proc.read_u32(addr)
        if not ptr or not (0x00010000 < ptr < 0x7FFF0000):
            return None
        text = self.proc.read_cstring(ptr, limit)
        return text or None

    def _label_text(self, addr: int, limit: int = 96) -> Optional[str]:
        """`_ptr_text`, but only when it reads like a label.

        These pointers track one section of the editor each and hold whatever
        they last pointed at everywhere else, so off their own section they
        return the previous label or outright rubbish -- measured, on the
        derived block, as a run of high bytes. A wrong label is the one thing
        this file will not say, so anything that is not plainly text is treated
        as no answer at all.
        """
        text = self._ptr_text(addr, limit)
        if not text:
            return None
        text = text.strip()
        if not text or len(text) > 48:
            return None
        printable = sum(1 for ch in text if 32 <= ord(ch) < 127)
        if printable != len(text):
            return None
        # A label has letters in it. A run of punctuation does not.
        if not any(ch.isalpha() for ch in text):
            return None
        return text

    # -- computed values ----------------------------------------------------

    def skills(self) -> List[int]:
        """The eighteen percentages.

        The formulas below are the creation-time ones and are right there and
        only there. They know nothing about tag skills or the points you have
        spent since, so in a live game Small Guns computed 37 against a sheet
        showing 47. `has_skill` knows about both.
        """
        live = self._live()
        if live:
            return list(live.skills)
        s = self.special()
        if len(s) < 7:
            return []
        st, pe, en, ch, in_, ag, lk = s
        return [
            5 + 4 * ag,            # Small Guns
            2 * ag,                # Big Guns
            2 * ag,                # Energy Weapons
            30 + 2 * (ag + st),    # Unarmed
            20 + 2 * (ag + st),    # Melee Weapons
            4 * ag,                # Throwing
            2 * (pe + in_),        # First Aid
            5 + pe + in_,          # Doctor
            5 + 3 * ag,            # Sneak
            10 + pe + ag,          # Lockpick
            3 * ag,                # Steal
            10 + pe + ag,          # Traps
            4 * in_,               # Science
            3 * in_,               # Repair
            5 * ch,                # Speech
            4 * ch,                # Barter
            5 * lk,                # Gambling
            2 * (en + in_),        # Outdoorsman
        ]

    def derived(self) -> List[int]:
        """The ten, in the order the panel lists them.

        Armour is the case that makes computing these hopeless once the game is
        running: damage resistance is 0 in the stat table and 8% on the sheet,
        the difference being what you are wearing, which the engine adds when it
        draws the row and stores nowhere.
        """
        live = self._live()
        if live:
            return list(live.derived)
        s = self.special()
        if len(s) < 7:
            return []
        st, pe, en, ch, in_, ag, lk = s
        return [
            ag,                    # Armor Class
            5 + ag // 2,           # Action Points
            25 + 25 * st,          # Carry Weight
            max(1, st - 5),        # Melee Damage
            0,                     # Damage Resistance
            5 * en,                # Poison Resistance
            2 * en,                # Radiation Resistance
            2 * pe,                # Sequence
            max(1, en // 3),       # Healing Rate
            lk,                    # Critical Chance
        ]

    def hit_points(self) -> Optional[int]:
        live = self._live()
        if live and live.max_hp is not None:
            return live.max_hp
        s = self.special()
        if len(s) < 7:
            return None
        st, _pe, en, _ch, _in, _ag, _lk = s
        return 15 + 2 * en + st

    # -- the current item ---------------------------------------------------

    def current(self) -> Optional[EditorItem]:
        index = self.selection()
        if index is None or index not in _SECTION_OF:
            return None
        section, pos = _SECTION_OF[index]

        if section == "special":
            stats = self.special()
            names = self._msg(MSG_STAT)
            descs = self._msg(MSG_STAT)
            label = names.get(SPECIAL_NAME_MSG[pos]) or "Stat {}".format(pos)
            value = None
            if pos < len(stats):
                value = str(stats[pos])
                # The rating word the editor prints beside the number. The
                # game's own, so it travels with any translation.
                rating = names.get(rating_msg(stats[pos]))
                if rating:
                    value = "{}, {}".format(value, rating)
                # **Nothing is said about the stat being modified**, and that
                # was a deliberate removal rather than an omission.
                #
                # This briefly read "Perception, 6, Good, down from 8", on the
                # belief that Fallout marks a modified stat by drawing it in a
                # different colour. A screenshot of the live sheet says
                # otherwise: the only row drawn differently is the SELECTED one
                # -- its rating word is white where the other six are green --
                # and Perception, reduced by two from a drug at that very
                # moment, was green like everything else.
                #
                # So the screen shows the total and nothing else, and saying
                # where the total came from would hand a blind player a
                # reference a sighted one does not get. Both are told about the
                # drug the same way: by the message the game printed when it
                # was taken, which this mod already reads aloud.
            return EditorItem(
                index, section, pos, label, value,
                descs.get(SPECIAL_DESC_MSG[pos]),
            )

        if section == "skill":
            names = self._msg(MSG_SKILL)
            values = self.skills()
            label = names.get(100 + pos) or "Skill {}".format(pos)
            value = "{} percent".format(values[pos]) if pos < len(values) else None
            if pos in self.tags():
                value = "{}, tagged".format(value) if value else "tagged"
            return EditorItem(
                index, section, pos, label, value, names.get(200 + pos)
            )

        if section == "trait":
            label = self._ptr_text(TRAIT_NAME_PTR, 96) or "Trait {}".format(pos)
            value = "selected" if pos in self.traits() else None
            return EditorItem(
                index, section, pos, label, value,
                self._ptr_text(TRAIT_DESC_PTR, 400),
            )

        if section == "record":
            # Perks, Karma and Kills. The label is whatever the trait pointer
            # is holding, because that is the pointer the engine moves for this
            # box -- confirmed by reading "Perks", "Karma" and "Giant Ants
            # Kills" off it while stepping these very indices. When it is not
            # holding anything readable the index is said instead, which is
            # honest about not knowing rather than confident and wrong.
            label = self._label_text(TRAIT_NAME_PTR)
            if not label:
                return EditorItem(index, section, pos,
                                  "Item {}".format(index), None, None)
            return EditorItem(index, section, pos, label, None,
                              self._ptr_text(TRAIT_DESC_PTR, 400))

        if section == "identity":
            # Labels from editor.msg, which is loaded whenever this screen is.
            # 106 NAME, 104 AGE, 105 SEX -- the game's own words, so they travel
            # with a translation the way every other label here does.
            ed = self._msg(MSG_EDITOR)
            if pos == 0:
                name = self.name()
                return EditorItem(index, section, pos, ed.get(106) or "Name",
                                  name if name and name != "None" else None,
                                  None)
            if pos == 1:
                age = self.age()
                return EditorItem(index, section, pos, ed.get(104) or "Age",
                                  None if age is None else str(age), None)
            return EditorItem(index, section, pos, ed.get(105) or "Sex",
                              self.sex_name(), None)

        if section == "condition":
            label = self._ptr_text(COND_NAME_PTR, 96) or "Condition {}".format(pos)
            value = None
            live = self._live()
            if live:
                # Every row gets a yes or a no. The panel lights the ones that
                # apply and leaves the rest dim, and dim is an answer -- "am I
                # still poisoned" is a question the box settles at a glance and
                # the mod could not settle at all. A row that only reads out its
                # own name tells you the row exists, which you knew.
                from .charsheet import condition_value

                value = condition_value(live, pos)
            elif pos == 0:
                hp = self.hit_points()
                if hp is not None:
                    value = "{} of {}".format(hp, hp)
            return EditorItem(index, section, pos, label, value, None)

        if section == "derived":
            stat_msg = self._msg(MSG_STAT)
            fallback, msg_num = DERIVED_LAYOUT[pos]
            label = stat_msg.get(msg_num) or fallback
            values = self.derived()
            value = str(values[pos]) if pos < len(values) else None
            return EditorItem(index, section, pos, label, value, None)

        return None

    # -- summaries ----------------------------------------------------------

    def summary(self) -> str:
        """Everything at a glance, for a 'where am I' key."""
        stats = self.special()
        names = self._msg(MSG_STAT)
        skill_msg = self._msg(MSG_SKILL)
        trait_msg = self._msg(MSG_TRAIT)
        bits: List[str] = []

        name = self.name()
        if name:
            # Labelled, because an unnamed character's buffer literally reads
            # "None" and a bare "None." at the start of the summary is baffling.
            bits.append("Name {}".format(name))
        age = self.age()
        if age is not None:
            bits.append("Age {}".format(age))
        sex = self.sex_name()
        if sex:
            bits.append(sex)
        if stats:
            bits.append(
                ". ".join(
                    "{} {}".format(names.get(SPECIAL_NAME_MSG[i], "?"), v)
                    for i, v in enumerate(stats)
                )
            )
        # Both of these belong to a character being MADE. The unspent character
        # points are the editor's own pool, and in a loaded game the address
        # still holds whatever was left over at creation -- a number that means
        # nothing and sounds like it means something. The maximum hit points are
        # said properly below, as part of "health 7 of 26".
        if not self._live():
            points = self.char_points()
            if points is not None:
                bits.append("{} character points remaining".format(points))
            hp = self.hit_points()
            if hp is not None:
                bits.append("Hit points {}".format(hp))

        # An existing character has facts a new one does not: how hurt they are,
        # what is wrong with them, and how far along they are.
        live = self._live()
        if live:
            from .charsheet import conditions

            if live.hp is not None and live.max_hp is not None:
                bits.append("Health {} of {}".format(live.hp, live.max_hp))
            wrong = conditions(live)
            if wrong:
                bits.append(", ".join(wrong).capitalize())
            # The level box, the way the screen lays it out: Level, Exp, and
            # what the next one wants.
            if live.level is not None:
                bits.append("Level {}".format(live.level))
            if live.experience is not None:
                bits.append("{} experience".format(live.experience))
            from .charsheet import next_level_experience

            needed = next_level_experience(live.level)
            if needed is not None:
                bits.append("Next level at {}".format(needed))
            if live.unspent:
                bits.append("{} skill points to spend".format(live.unspent))

        tags = self.tags()
        if tags:
            bits.append(
                "Tagged: "
                + ", ".join(skill_msg.get(100 + t, "skill {}".format(t)) for t in tags)
            )
        bits.append("{} of {} tags used".format(len(tags), MAX_TAGS))

        traits = self.traits()
        if traits:
            bits.append(
                "Traits: "
                + ", ".join(trait_msg.get(100 + t, "trait {}".format(t)) for t in traits)
            )
        else:
            bits.append("No traits chosen")
        return ". ".join(bits) + "."

    def is_plausible(self) -> bool:
        """Cheap sanity check that we are looking at a real editor state.

        Only a backstop -- the screen flags in screens.py are what actually
        decide which screen is showing. This used to be the whole test, which
        is why the selection screen got narrated as character creation.

        **It no longer requires the selection to be an index we can name.** It
        did, and the cost was out of all proportion: landing on Name, Age or Sex
        -- none of which are in the measured index map -- made this return False,
        which made the watcher's snapshot None, which made its poll return early.
        So the three unmapped controls did not merely fail to announce
        themselves. They switched the entire character editor off, and the next
        SPECIAL stat stepped to was silent too, for the same reason and with
        nothing to suggest why.

        Whether an item can be described is a question about that item. Whether
        this is the editor at all is a question about the screen, and the SPECIAL
        array below answers it perfectly well on its own.
        """
        index = self.selection()
        stats = self.special()
        if index is None or index < 0:
            return False
        if len(stats) != 7 or not all(1 <= v <= 14 for v in stats):
            return False
        return True
