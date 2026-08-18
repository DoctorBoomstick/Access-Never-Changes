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
CONDITION_INDICES = [10, 11, 12, 13, 14, 15, 16, 17]
DERIVED_INDICES = [18, 19, 20, 21, 22, 23, 83, 24, 25, 26]
SKILL_INDICES = list(range(28, 46))
TRAIT_INDICES = [55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 94, 69, 70]

SECTION_ORDER = ["special", "condition", "derived", "skill", "trait"]

_SECTION_OF: Dict[int, Tuple[str, int]] = {}
for _name, _seq in (
    ("special", SPECIAL_INDICES),
    ("condition", CONDITION_INDICES),
    ("derived", DERIVED_INDICES),
    ("skill", SKILL_INDICES),
    ("trait", TRAIT_INDICES),
):
    for _pos, _idx in enumerate(_seq):
        _SECTION_OF[_idx] = (_name, _pos)

# stat.msg message numbers for the seven SPECIAL stats and their descriptions.
SPECIAL_NAME_MSG = [100, 101, 102, 103, 104, 105, 106]
SPECIAL_DESC_MSG = [200, 201, 202, 203, 204, 205, 206]

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

    # -- raw state ----------------------------------------------------------

    def selection(self) -> Optional[int]:
        return self.proc.read_i32(SEL_ADDR)

    def special(self) -> List[int]:
        raw = self.proc.read(SPECIAL_ADDR, 7 * 4)
        if raw is None or len(raw) < 28:
            return []
        return [
            int.from_bytes(raw[i * 4:i * 4 + 4], "little", signed=True) for i in range(7)
        ]

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

    def _msg(self, global_addr: int) -> Dict[int, str]:
        if global_addr not in self._msg_cache:
            lst = read_message_list(self.proc, global_addr)
            self._msg_cache[global_addr] = lst.by_num() if lst else {}
        return self._msg_cache[global_addr]

    def _ptr_text(self, addr: int, limit: int = 400) -> Optional[str]:
        ptr = self.proc.read_u32(addr)
        if not ptr or not (0x00010000 < ptr < 0x7FFF0000):
            return None
        text = self.proc.read_cstring(ptr, limit)
        return text or None

    # -- computed values ----------------------------------------------------

    def skills(self) -> List[int]:
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
            value = str(stats[pos]) if pos < len(stats) else None
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

        if section == "condition":
            label = self._ptr_text(COND_NAME_PTR, 96) or "Condition {}".format(pos)
            value = None
            if pos == 0:
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
        if stats:
            bits.append(
                ". ".join(
                    "{} {}".format(names.get(SPECIAL_NAME_MSG[i], "?"), v)
                    for i, v in enumerate(stats)
                )
            )
        points = self.char_points()
        if points is not None:
            bits.append("{} character points remaining".format(points))
        hp = self.hit_points()
        if hp is not None:
            bits.append("Hit points {}".format(hp))

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
        """
        index = self.selection()
        stats = self.special()
        if index is None or index not in _SECTION_OF:
            return False
        if len(stats) != 7 or not all(1 <= v <= 14 for v in stats):
            return False
        return True
