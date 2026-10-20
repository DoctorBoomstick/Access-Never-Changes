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

from typing import List, NamedTuple, Optional, Tuple

from .worldlog import ap_cost, attack_mode
from ..i18n import tr

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
def effects() -> List[Tuple[int, str]]:
    return [
        (DAM_CRITICAL, tr("combat.critical", "critical")),
        # DAM_DEAD is deliberately absent: HOOK_ONDEATH always follows and
        # reports the death by name, so including it here says the same thing
        # twice.
        (DAM_KNOCKED_OUT, tr("condition.knocked_out", "knocked out")),
        (DAM_KNOCKED_DOWN, tr("condition.knocked_down", "knocked down")),
        (DAM_BLIND, tr("condition.blinded", "blinded")),
        (DAM_ON_FIRE, tr("combat.on_fire", "on fire")),
    ]


# Hit modes that are not "the weapon's first or second attack", from the
# engine's HIT_MODE list. The unarmed specials are what the Unarmed skill and
# level unlock in place of punch and kick. These words are the mod's: the bar
# draws them as pictures and no message file the engine loads holds them --
# the same search, and the same reasoning, as worldlog.ATTACK_MODES.
def hit_mode(mode: int) -> Optional[str]:
    return {
        4: tr("attack.punch", "punch"), 5: tr("attack.kick", "kick"),
        6: tr("attack.reload", "reload"), 7: tr("attack.reload", "reload"),
        8: tr("attack.strong_punch", "strong punch"),
        9: tr("attack.hammer_punch", "hammer punch"),
        10: tr("attack.haymaker", "haymaker"), 11: tr("attack.jab", "jab"),
        12: tr("attack.palm_strike", "palm strike"),
        13: tr("attack.piercing_strike", "piercing strike"),
        14: tr("attack.strong_kick", "strong kick"),
        15: tr("attack.snap_kick", "snap kick"),
        16: tr("attack.power_kick", "power kick"),
        17: tr("attack.hip_kick", "hip kick"),
        18: tr("attack.hook_kick", "hook kick"),
        19: tr("attack.piercing_kick", "piercing kick"),
    }.get(mode)

# The interface bar's actions, at +0x10 in each item button.
BAR_USE = 0
BAR_RELOAD = 5

def hand_name(hand: int) -> Optional[str]:
    return {0: tr("combat.left_hand", "Left hand"),
            1: tr("combat.right_hand", "Right hand")}.get(hand)


def bar_words(f: List[str], last_hand: Optional[int] = None) -> Optional[str]:
    """A COMBAT:bar line's fields as the sentence to say, or None.

    What the attack button would do now: the item, the attack, whether it is
    aimed, and what it costs. The hand is named only when it changed, which is
    when B was pressed -- N on the same hand would otherwise say it every time.
    """
    if len(f) < 7:
        return None
    try:
        hand, act, mode, aim, kind, ap = (int(x) for x in f[:6])
    except ValueError:
        return None
    item = f[6].strip()
    parts = [item or tr("combat.unarmed", "Unarmed")]
    if act == BAR_USE:
        parts.append(tr("combat.use", "use"))
    else:
        what = attack_mode(kind) if 0 <= mode <= 3 else hit_mode(mode)
        if not what:
            what = tr("combat.attack", "attack")
        parts.append(what)
        if aim:
            parts.append(tr("combat.aimed", "aimed"))
        if ap > 0:
            parts.append(ap_cost(ap))
    said = ", ".join(parts) + "."
    if last_hand is not None and hand != last_hand and hand_name(hand):
        said = "{}. {}".format(hand_name(hand), said)
    return said


class CombatState(NamedTuple):
    ap: Optional[int]
    max_ap: Optional[int]
    in_combat: bool
    whose_turn: Optional[str]


def _turn(who: str) -> str:
    """Whose turn it is. "you" is the scripts' word for the player."""
    if who == "you":
        return tr("combat.your_turn", "Your turn.")
    return tr("combat.turn", "{name}'s turn.", name=who)


def _ap_of(ap: int, most: int) -> str:
    return tr("combat.ap_of", "{ap} of {most} action points.", ap=ap, most=most)


class CombatWatcher:
    """Turns COMBAT: log lines into things to say."""

    def __init__(self) -> None:
        self.ap: Optional[int] = None
        self.max_ap: Optional[int] = None
        self.in_combat = False
        self.whose_turn: Optional[str] = None
        self.target_name: Optional[str] = None
        self.target_valid = False
        # Fallout prints its own account of every blow to the interface bar --
        # "You hit the Giant Ant for 10 points of damage." Once the mod can read
        # that buffer it is strictly better than anything assembled here: the
        # engine's own wording, already translated, including the body part
        # struck, which this file deliberately refuses to name in English.
        # Turn order and action points stay ours, because the game never writes
        # those anywhere.
        self.narrate_damage = True
        # The hand the last COMBAT:bar line was about.
        self.bar_hand: Optional[int] = None
        # The called-shot window's chances, as the to-hit hook heard them while
        # it drew: body part -> (chance, the game's name for the part), and
        # the critter they were worked out against.
        self.aims = {}
        self.aim_target: Optional[str] = None

    def reset(self) -> None:
        self.__init__()

    def state(self) -> CombatState:
        return CombatState(self.ap, self.max_ap, self.in_combat, self.whose_turn)

    def summary(self) -> str:
        if not self.in_combat:
            return tr("combat.not_in_combat", "Not in combat.")
        parts = []
        if self.whose_turn:
            parts.append(_turn(self.whose_turn))
        if self.ap is not None and self.max_ap is not None:
            parts.append(_ap_of(self.ap, self.max_ap))
        return " ".join(parts) if parts else tr("combat.in_combat", "In combat.")

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
        if head == "bar":
            return self._bar(fields)
        if head == "aim":
            return self._aim(fields)
        return []

    def _bar(self, f: List[str]) -> List[str]:
        said = bar_words(f, self.bar_hand)
        try:
            self.bar_hand = int(f[0])
        except (ValueError, IndexError):
            pass
        return [said] if said else []

    def _aim(self, f: List[str]) -> List[str]:
        """One body part's chance, as the called-shot window worked it out.

        Silent: the window watcher reads these when the window is up. A new
        target starts a fresh table, so a chance against one critter is never
        read out over the window for another.
        """
        if len(f) < 4:
            return []
        try:
            loc, chance = int(f[0]), int(f[1])
        except ValueError:
            return []
        target = f[3].strip()
        if target != self.aim_target:
            self.aims = {}
            self.aim_target = target
        self.aims[loc] = (chance, f[2].strip())
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
            return [tr("combat.over", "Combat over.")] if was else []

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
                return [_turn(who)]
            return [_turn(who)] if who else []
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
            return [_ap_of(cur, mx)]
        if cur == 0:
            return [tr("combat.no_ap", "No action points left.")]
        return ["{}.".format(cur)]

    def _damage(self, f: List[str]) -> List[str]:
        if not self.narrate_damage:
            return []
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

        hurt = [name for bit, name in effects() if flags & bit]
        if attacker == "you":
            text = tr("combat.you_hit", "You hit {target} for {damage}",
                      target=target, damage=amount_n)
        elif target == "you":
            text = tr("combat.hits_you", "{attacker} hits you for {damage}",
                      attacker=attacker, damage=amount_n)
        else:
            text = tr("combat.hits", "{attacker} hits {target} for {damage}",
                      attacker=attacker, target=target, damage=amount_n)
        if hurt:
            text += ", " + ", ".join(hurt)
        return [text + "."]

    def _miss(self, f: List[str]) -> List[str]:
        if not self.narrate_damage:
            return []
        if len(f) < 3:
            return []
        try:
            result = int(f[0])
        except ValueError:
            return []
        attacker, target = f[1], f[2]
        if attacker == "you":
            text = tr("combat.you_miss", "You miss {target}", target=target)
        elif target == "you":
            text = tr("combat.misses_you", "{attacker} misses you", attacker=attacker)
        else:
            text = tr("combat.misses", "{attacker} misses {target}",
                      attacker=attacker, target=target)
        if result == ROLL_CRITICAL_MISS:
            text += ", " + tr("combat.critical_miss", "critical miss")
        return [text + "."]

    def _death(self, f: List[str]) -> List[str]:
        if not f or not f[0]:
            return []
        who = f[0]
        if who == "you":
            return [tr("combat.you_die", "You are dead.")]
        return [tr("combat.dies", "{name} dies.", name=who)]
