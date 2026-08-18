"""Speak what the in-game combat script reports.

`gl_combat.ssl` writes "COMBAT:" lines to debug.log; this turns them into
speech. It holds no state about the fight -- like everything else here, the
game is the only source of truth and each line is reported as it arrives.

Two rules govern the wording.

**Names and numbers come from the game.** Critter names are whatever
`obj_name` returned, so translations and content mods work untouched. Damage
figures and hit chances are the engine's own. Nothing here invents a fact about
the world.

**Body parts are not spoken yet, on purpose.** The engine reports which body
part was struck as an index, and naming those in English here would be inventing
vocabulary the game already owns in `combat.msg`. Until we can read the game's
own words for them, the index is logged and stays silent -- a missing detail is
recoverable, a wrong one told confidently is not.
"""

from __future__ import annotations

from typing import List, NamedTuple, Optional

# HOOK_COMBATTURN arg0
TURN_START = 1
TURN_END = 0
COMBAT_ENDED_ABRUPT = -1
COMBAT_ENDED = -2

# HOOK_AFTERHITROLL arg0
ROLL_CRITICAL_MISS = 0
ROLL_MISS = 1

# define_lite.h -- the flags the engine sets on a damaging hit.
DAM_KNOCKED_OUT = 0x1
DAM_KNOCKED_DOWN = 0x2
DAM_BLIND = 0x40
DAM_DEAD = 0x80
DAM_CRITICAL = 0x200
DAM_ON_FIRE = 0x400

# Only the effects a player would notice happening to them. The full DAM_ set
# includes bookkeeping flags (DAM_PERFORM_REVERSE, DAM_BACKWASH) that describe
# how the engine animates a hit, not anything that happened in the world.
EFFECTS = [
    (DAM_CRITICAL, "critical"),
    # DAM_DEAD is deliberately absent: HOOK_ONDEATH always follows and reports
    # the death by name, so including it here says the same thing twice.
    (DAM_KNOCKED_OUT, "knocked out"),
    (DAM_KNOCKED_DOWN, "knocked down"),
    (DAM_BLIND, "blinded"),
    (DAM_ON_FIRE, "on fire"),
]


class CombatState(NamedTuple):
    ap: Optional[int]
    max_ap: Optional[int]
    in_combat: bool
    whose_turn: Optional[str]


def _verb(subject: str, third: str, other: str) -> str:
    """Agree the verb with the subject, since 'you' takes the plural form."""
    return third if subject == "you" else other


class CombatWatcher:
    """Turns COMBAT: log lines into things to say."""

    def __init__(self) -> None:
        self.ap: Optional[int] = None
        self.max_ap: Optional[int] = None
        self.in_combat = False
        self.whose_turn: Optional[str] = None
        self.target_name: Optional[str] = None
        self.target_valid = False

    def reset(self) -> None:
        self.__init__()

    def state(self) -> CombatState:
        return CombatState(self.ap, self.max_ap, self.in_combat, self.whose_turn)

    def summary(self) -> str:
        if not self.in_combat:
            return "Not in combat."
        parts = []
        if self.whose_turn:
            parts.append(
                "Your turn" if self.whose_turn == "you"
                else "{}'s turn".format(self.whose_turn)
            )
        if self.ap is not None and self.max_ap is not None:
            parts.append("{} of {} action points".format(self.ap, self.max_ap))
        return ". ".join(parts) + "." if parts else "In combat."

    def handle(self, line: str) -> List[str]:
        """One COMBAT: line in, zero or more things to say out."""
        body = line[len("COMBAT:"):] if line.startswith("COMBAT:") else line
        head, _, rest = body.partition(" ")
        fields = rest.split("|") if rest else []

        if head == "turn":
            return self._turn(fields)
        if head == "ap":
            return self._ap(fields)
        if head == "dmg":
            return self._damage(fields)
        if head == "miss":
            return self._miss(fields)
        if head == "death":
            return self._death(fields)
        if head == "target":
            return self._target(fields)
        return []

    def _target(self, f: List[str]) -> List[str]:
        """HOOK_TARGETOBJECT: what the engine thinks the crosshair is on.

        Silent by design. It exists so the mod can confirm an attack is aimed at
        the critter the player chose, rather than trusting a pixel offset -- the
        same standard movement is held to. Announcing every hover would be
        chatter, so the state is recorded and the aiming code consults it.
        """
        if len(f) < 3:
            return []
        try:
            self.target_valid = bool(int(f[1]))
        except ValueError:
            self.target_valid = False
        self.target_name = f[2] or None
        return []

    # -- handlers -------------------------------------------------------

    def _turn(self, f: List[str]) -> List[str]:
        if not f:
            return []
        try:
            event = int(f[0])
        except ValueError:
            return []
        who = f[1] if len(f) > 1 else ""

        if event in (COMBAT_ENDED, COMBAT_ENDED_ABRUPT):
            was = self.in_combat
            self.in_combat = False
            self.whose_turn = None
            self.ap = None
            return ["Combat over."] if was else []

        self.in_combat = True
        if event == TURN_START:
            self.whose_turn = who
            if who == "you":
                # Forget the running AP figure so the next AP line gives the
                # full "8 of 8" rather than a bare "8". At the start of a turn
                # the total is the number you are planning against; mid-turn
                # only the remainder matters.
                self.ap = None
                # AP arrives on its own line moments later; announcing the turn
                # without waiting keeps it responsive, and the AP line follows.
                return ["Your turn."]
            return ["{}'s turn.".format(who)] if who else []
        return []

    def _ap(self, f: List[str]) -> List[str]:
        if len(f) < 2:
            return []
        try:
            cur, mx = int(f[0]), int(f[1])
        except ValueError:
            return []
        first = self.ap is None
        self.ap, self.max_ap = cur, mx
        # At the start of your turn, the full figure is what matters. After
        # that only the remainder does -- "3 action points" every time you take
        # a step, with the maximum repeated each time, is unbearable.
        if first:
            return ["{} of {} action points.".format(cur, mx)]
        if cur == 0:
            return ["No action points left."]
        return ["{}.".format(cur)]

    def _damage(self, f: List[str]) -> List[str]:
        if len(f) < 3:
            return []
        attacker, target, amount = f[0], f[1], f[2]
        flags = 0
        if len(f) > 3:
            try:
                flags = int(f[3])
            except ValueError:
                flags = 0

        try:
            amount_n = int(amount)
        except ValueError:
            return []

        effects = [name for bit, name in EFFECTS if flags & bit]
        text = "{} {} {} for {}".format(
            attacker.capitalize() if attacker == "you" else attacker,
            _verb(attacker, "hit", "hits"),
            target,
            amount_n,
        )
        if effects:
            text += ", " + ", ".join(effects)
        return [text + "."]

    def _miss(self, f: List[str]) -> List[str]:
        if len(f) < 3:
            return []
        try:
            result = int(f[0])
        except ValueError:
            return []
        attacker, target = f[1], f[2]
        text = "{} {} {}".format(
            attacker.capitalize() if attacker == "you" else attacker,
            _verb(attacker, "miss", "misses"),
            target,
        )
        if result == ROLL_CRITICAL_MISS:
            text += ", critical miss"
        return [text + "."]

    def _death(self, f: List[str]) -> List[str]:
        if not f or not f[0]:
            return []
        who = f[0]
        if who == "you":
            return ["You are dead."]
        return ["{} dies.".format(who)]
