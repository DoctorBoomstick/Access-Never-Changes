"""The premade character selection screen.

Left/Right cycle three characters; C creates your own, M modifies the shown
one, T takes it as-is. This reads whichever is displayed so it can be described
out loud -- otherwise the screen is a dead end for a blind player, since the
only way past it is a button they cannot see.

Addresses confirmed live. The tagged-skill and trait arrays were validated by
cycling all three premades and checking the indices decode to the real
characters (Narg: Melee/Small Guns/Throwing, Heavy Handed + Gifted, and so on)
-- a coincidence does not survive that test.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional

from ..memory.process import Process
from ..msg.memlist import read_message_list

NAME_ADDR = 0x0056D75C      # char buffer holding the shown character's name
COUNTER_ADDR = 0x0051E2E0   # increments per Left/Right; character = value % 3
SPECIAL_ADDR = 0x0051C394   # shared with the editor
TAGS_ADDR = 0x00668070      # 4 x i32 skill indices, -1 when empty
TRAITS_ADDR = 0x0066BE40    # 2 x i32 trait indices, -1 when empty

MSG_STAT = 0x0066817C
MSG_SKILL = 0x00668080
MSG_TRAIT = 0x0066BE38

SPECIAL_NAME_MSG = [100, 101, 102, 103, 104, 105, 106]
PREMADE_COUNT = 3


class PremadeInfo(NamedTuple):
    name: str
    slot: int
    special: List[int]
    tags: List[str]
    traits: List[str]

    def announce(self) -> str:
        return "{}. {} of {}.".format(self.name, self.slot + 1, PREMADE_COUNT)

    def full(self, stat_names: List[str]) -> str:
        bits = [self.name]
        if self.special and stat_names:
            bits.append(
                ", ".join(
                    "{} {}".format(n, v) for n, v in zip(stat_names, self.special)
                )
            )
        if self.tags:
            bits.append("Tagged skills: " + ", ".join(self.tags))
        if self.traits:
            bits.append("Traits: " + ", ".join(self.traits))
        return ". ".join(bits) + "."


class PremadeScreen:
    """Read-only view of character selection."""

    def __init__(self, proc: Process) -> None:
        self.proc = proc
        self._msg_cache: Dict[int, Dict[int, str]] = {}

    def _msg(self, global_addr: int) -> Dict[int, str]:
        if global_addr not in self._msg_cache:
            lst = read_message_list(self.proc, global_addr)
            self._msg_cache[global_addr] = lst.by_num() if lst else {}
        return self._msg_cache[global_addr]

    def _ints(self, addr: int, count: int) -> List[int]:
        raw = self.proc.read(addr, count * 4)
        if not raw or len(raw) < count * 4:
            return []
        return [
            int.from_bytes(raw[i * 4:i * 4 + 4], "little", signed=True)
            for i in range(count)
        ]

    def stat_names(self) -> List[str]:
        stat = self._msg(MSG_STAT)
        return [stat.get(n, "?") for n in SPECIAL_NAME_MSG]

    def name(self) -> Optional[str]:
        return self.proc.read_cstring(NAME_ADDR, 32) or None

    def slot(self) -> int:
        counter = self.proc.read_i32(COUNTER_ADDR)
        if counter is None:
            return 0
        return counter % PREMADE_COUNT

    def read(self) -> Optional[PremadeInfo]:
        name = self.name()
        if not name:
            return None
        skill_msg = self._msg(MSG_SKILL)
        trait_msg = self._msg(MSG_TRAIT)
        tags = [t for t in self._ints(TAGS_ADDR, 4) if t >= 0]
        traits = [t for t in self._ints(TRAITS_ADDR, 2) if t >= 0]
        return PremadeInfo(
            name=name,
            slot=self.slot(),
            special=self._ints(SPECIAL_ADDR, 7),
            tags=[skill_msg.get(100 + t, "skill {}".format(t)) for t in tags],
            traits=[trait_msg.get(100 + t, "trait {}".format(t)) for t in traits],
        )
