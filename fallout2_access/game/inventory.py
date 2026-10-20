"""Speak the inventory, loot and barter windows.

`gl_inven.ssl` reads the lists out of the engine and writes "INVEN:" lines;
this turns them into speech. It holds no idea of what is in a container -- every
line reports what the engine said at the moment the key was pressed, which is
the same rule the rest of the mod follows and the reason the speech cannot drift
away from the game.

Three lists, because the window has three and they mean different things:

    yours       what you are carrying
    theirs      the container, the corpse, or the person you are trading with
    worn        armour and the two hands

The worn list is a fixed three slots rather than a list of what happens to be
there, because an empty hand is a fact worth hearing. "Item 2, empty" is the
answer to "can I pick something up", and a list that simply omitted it would
leave that question unanswerable.

As everywhere else here, item names and weights are the game's own. The words
that describe *navigation* -- which list, which slot, how far through -- are
ours, because the game has no phrase for them: it simply shows you.
"""

from __future__ import annotations

import re
import time
from typing import List, Optional

from . import screens
from ..i18n import tr
from .. import words

SIDE_MINE = 0
SIDE_THEIRS = 1
SIDE_WORN = 2
# The barter window's two middle lists. They exist only during a trade, and
# only the script can see them -- see on_barterprice in gl_inven.ssl for why
# there is no address to read them from.
SIDE_MY_OFFER = 3
SIDE_THEIR_OFFER = 4

def side_names() -> dict:
    return {
        SIDE_MINE: tr("inventory.yours", "yours"),
        SIDE_THEIRS: tr("inventory.theirs", "theirs"),
        SIDE_WORN: tr("inventory.worn", "worn"),
        SIDE_MY_OFFER: tr("inventory.your_offer", "your offer"),
        SIDE_THEIR_OFFER: tr("inventory.their_offer", "their offer"),
    }

# What an empty list is called out loud. An empty carried list is now somewhere
# the player can deliberately stand -- it is where an unequipped item has to go
# -- so it needs a sentence that makes sense as a destination rather than the
# "No yours here" that the side names produced.
def empty_side(side: int) -> str:
    return {
        SIDE_MINE: tr("inventory.carrying_nothing", "Carrying nothing."),
        SIDE_THEIRS: tr("inventory.nothing_there", "Nothing there."),
        SIDE_WORN: tr("inventory.wearing_nothing", "Wearing nothing."),
        # An empty offer is a place you deliberately stand -- it is where an
        # item goes when you put it on the table -- so it needs a sentence
        # that works as a destination rather than as a complaint.
        SIDE_MY_OFFER: tr("inventory.offering_nothing", "You are offering nothing."),
        SIDE_THEIR_OFFER: tr("inventory.they_offer_nothing", "They are offering nothing."),
    }.get(side) or tr("inventory.nothing_here", "Nothing here.")

# The three fixed slots down the middle of the window. These are the game's own
# labels, printed on the window itself, which is why they are capitalised the
# way they are on screen.
def worn_slot(slot: int) -> str:
    names = [tr("inventory.armor", "Armor"), tr("inventory.item1", "Item 1"),
             tr("inventory.item2", "Item 2")]
    if 0 <= slot < len(names):
        return names[slot]
    return tr("inventory.slot", "Slot {number}", number=slot + 1)

_OPEN = re.compile(r"INVEN:open (\d+)\|([^|]*)\|(\d+)\|(\d+)\|")
# Where the window is, straight from sfall. This is what lets the mod find the
# same window in memory and read its buttons: a rectangle the engine states is
# a rectangle we do not have to guess, so the struct we match is confirmed
# rather than assumed.
_RECT = re.compile(r"INVEN:rect (\d+)\|(\d+)\|(\d+)\|(\d+)\|(\d+)\|(\d+)x(\d+)\|")
# The last two -- rounds loaded and magazine size -- are optional, so a game
# still running the previously compiled script keeps listing its inventory
# instead of failing to match and going silent. -1 rounds means "not a weapon,
# nobody asked", which is a different fact from a weapon holding none.
#
# **Parsed and deliberately not spoken.** Saying what a gun in the pack holds
# was tried and taken back out: `:` is the key for that question, and putting
# the same fact on every listing line adds words to the one place a player is
# stepping quickly, in a sentence the mod would have to translate itself. The
# numbers stay because they are numbers -- what a reload actually did has to be
# read from the engine rather than assumed from a click, and this is where that
# reading comes from.
#
# Then the value of one, and last the rounds in an ammunition stack -- every
# box, not just the top one -- or -1 for anything that is not ammunition. For
# ammunition the count is the BOXES, which is what a price is per and what the
# "Move Items" window counts.
_ENTRY = re.compile(
    r"INVEN:entry (\d+)\|(\d+)\|(\d+)\|([^|]*)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|"
    r"(?:(-?\d+)\|(?:(-?\d+)\|(-?\d+)\|(?:(-?\d+)\|(?:(-?\d+)\|)?)?)?)?"
)
_NONE = re.compile(r"INVEN:none (\d+)\|")
# The item menu: the map's action menu, for what you carry.
_MENU = re.compile(r"INVEN:menu (\w+)\|?([^|]*)\|?([^|]*)\|?([^|]*)\|?")
# action | item | side | index | total | is it the ACTIVE item
_DO = re.compile(r"INVEN:do\|([^|]*)\|([^|]*)\|(\d+)\|(\d+)\|(\d+)\|(\d+)\|")
# item | the prototype's description. Answered by the script and complete on
# arrival, unlike the rest of this menu -- nothing here needs the pointer.
# What became of "drop it": the engine's own drop, run by gl_inven.ssl.
_DROPPED = re.compile(r"INVEN:dropped\|([^|]*)\|(\d+)\|")
_DROPNOT = re.compile(r"INVEN:dropnot (\w+)\|")
_DROPASK = re.compile(r"INVEN:dropask\|([^|]*)\|(\d+)\|(\d+)\|")
_DROPCOUNT = re.compile(r"INVEN:dropcount\|(\d+)\|(\d+)\|")


def _how_many(n: int, most: int) -> str:
    if n >= most:
        return tr("drop.all", "All {count}.", count=most)
    return "{}.".format(words.of(n, most))


def drop_line(line: str) -> Optional[str]:
    """The sentence for an INVEN:dropped or INVEN:dropnot line, or None."""
    m = _DROPPED.match(line)
    if m:
        name, count = m.group(1).strip(), int(m.group(2))
        if count == 1:
            return tr("drop.one", "Dropped {item}.", item=name)
        return tr("drop.many", "Dropped {count} {item}.", count=count, item=name)
    m = _DROPASK.match(line)
    if m:
        name, n, most = m.group(1).strip(), int(m.group(2)), int(m.group(3))
        return tr("drop.ask", "Drop how many {item}? {count} Up and down change "
                  "it, Control for tens, or type a number. End for all of them. "
                  "Enter drops, Escape cancels.",
                  item=name, count=_how_many(n, most))
    m = _DROPCOUNT.match(line)
    if m:
        return _how_many(int(m.group(1)), int(m.group(2)))
    m = _DROPNOT.match(line)
    if m:
        why = m.group(1)
        if why == "here":
            return tr("drop.not_here", "Only things you carry or wear can be "
                      "dropped, from your own inventory.")
        if why == "unsafe":
            return tr("drop.unsafe", "Dropping needs AllowUnsafeScripting in "
                      "ddraw.ini. Run the installer again to set it.")
        if why == "cancel":
            return tr("pick.cancelled", "Cancelled.")
        return tr("drop.failed", "That did not drop.")
    return None


_LOOK = re.compile(r"INVEN:look\|([^|]*)\|(.*)\|", re.DOTALL)

# "INVEN:price <asking>|<offering>|<caps in the stack>|<before skill>|"
#
# The two totals the barter screen prints, taken from inside the engine's own
# calculation of them rather than worked out here. `before` is the same goods
# at face value before either barter skill is applied; the engine does not draw
# it, so it is parsed and not spoken.
# The last two are optional so that a game still running the previously
# compiled script keeps working: a regex that demanded them would not merely
# lose the offer flag, it would fail to match at all and the prices would go
# silent -- a far worse trade than a missing field.
_PRICE = re.compile(
    r"INVEN:price (-?\d+)\|(-?\d+)\|(-?\d+)\|(-?\d+)\|"
    r"(?:(-?\d+)\|(-?\d+)\|)?")


def look_line(line):
    """Turn an INVEN:look line into the sentence to say, or None.

    The name is repeated before the description on purpose. The list cursor can
    be moved between opening the menu and choosing from it, so "look at it"
    has to say which "it" it answered for -- otherwise a description is a
    paragraph with nothing tying it to the thing you thought you asked about.

    An item whose prototype carries no description says so rather than going
    quiet. Silence here reads as the key not working, which is the failure this
    codebase keeps having to fix in other places.
    """
    m = _LOOK.match(line)
    if not m:
        return None
    name, text = m.group(1).strip(), m.group(2).strip()
    if not name:
        name = tr("inventory.that", "That")
    if not text:
        return tr("inventory.no_description", "{name}. No description.", name=name)
    return "{}. {}".format(name, text)


def menu_line(line):
    """Turn an INVEN:menu line into the sentence to say, or None.

    Deliberately the same shape as the map's action menu -- arrows move, Enter
    does it -- because it is the same idea and a second set of habits to learn
    would be a worse answer than a slightly duller one.
    """
    m = _MENU.match(line)
    if not m:
        return None
    what = m.group(1)
    if what == "none":
        return tr("inventory.nothing_selected", "Nothing selected.")
    if what == "closed":
        return tr("inventory.closed", "Closed.")
    if what == "gone":
        return tr("inventory.gone", "That item is no longer there.")
    if what == "open":
        name, count, first = (m.group(2).strip(), m.group(3).strip(),
                              m.group(4).strip())
        return tr("inventory.menu", "{name}. {count} actions. {first}, {position}.",
                  name=name or tr("inventory.that", "That"), count=count,
                  first=_say(first).capitalize(), position=words.of(1, count))
    if what == "at":
        label, index, count = (m.group(2).strip(), m.group(3).strip(),
                               m.group(4).strip())
        return "{}, {}.".format(_say(label).capitalize(), words.of(index, count))
    return None
_SUMMARY = re.compile(
    r"INVEN:summary (\d+)\|(-?\d+)\|(-?\d+)\|(\d+)\|(\d+)\|(-?\d+)\|"
)

def _say(text: str) -> str:
    """A menu entry from gl_inven.ssl, translated on its way out."""
    from .worldlog import say_script

    return say_script(text)


def help_text() -> str:
    return tr("inventory.help", "Up and down step the list, left and right change "
              "list, numpad slash re-reads the item.")


def _items(n: int) -> str:
    if n == 1:
        return tr("inventory.one_item", "1 item")
    return tr("inventory.items", "{count} items", count=n)


class InventoryWatcher:
    """Turns INVEN: log lines into things to say."""

    def __init__(self) -> None:
        self.open = False
        self.container: Optional[str] = None
        self.last: Optional[str] = None
        # Where the window sits, and what is selected in it. Held so that the
        # part of the mod that moves an item knows which row to point at
        # without having to ask the game again -- the script already said.
        self.rect: Optional[tuple] = None       # (x, y, width, height)
        self.side: Optional[int] = None
        self.index: int = 0
        self.total: int = 0
        self.selected: Optional[str] = None     # the item's own name
        self.selected_count: int = 1            # how many of it
        # How many of the item being MOVED, and until when that holds. Not the
        # same as `selected_count`: a move is two presses, and by the second the
        # list cursor is on the destination. The "Move Items" window took its
        # maximum from there, so 203 caps dropped beside 24 rounds could only be
        # moved 24 at a time. See `moving`.
        self.moving_count: Optional[int] = None
        self.moving_until: float = 0.0
        # (weight carried, items carried, items on the other side), from the
        # totals line. The only reading a move reliably changes.
        self.counts: Optional[tuple] = None
        # (what they are asking, what you are offering), from the engine's own
        # barter calculation. None until the first one arrives, which is what
        # distinguishes "nothing on the table" from "not bartering".
        self.price: Optional[tuple] = None
        # The two totals as they stood when an offer was made, until the next
        # reading says what became of it. None the rest of the time.
        self.offered: Optional[tuple] = None
        # The window's game mode, and whether the trade is with a companion.
        self.mode = 0
        self.party = False

    def reset(self) -> None:
        self.open = False
        self.container = None
        self.last = None
        self.price = None
        self.offered = None
        self.mode = 0
        self.party = False
        self.rect = None
        self.side = None
        self.index = 0
        self.total = 0
        self.selected = None
        self.counts = None
        self.moving_count = None
        self.moving_until = 0.0

    # How long a move's count is good for. The window opens as the drag ends,
    # a second or two after it starts; anything much later is some other move
    # that this one has no business sizing.
    MOVING_FOR = 10.0

    def start_moving(self, count: int, now: Optional[float] = None) -> None:
        """Remember how many of the item being dragged there are."""
        now = time.time() if now is None else now
        self.moving_count = count
        self.moving_until = now + self.MOVING_FOR

    def moving(self, now: Optional[float] = None) -> Optional[int]:
        """How many of the dragged item, or None if no drag is recent.

        Read, not taken: the window's watcher is reset on the way in and again
        as it is entered, and taking the count on the first left the second to
        size the window off the list cursor -- the bug this exists to fix. The
        time limit is what keeps it from sizing some later window instead.
        """
        now = time.time() if now is None else now
        if self.moving_count is None or now > self.moving_until:
            return None
        return self.moving_count

    def handle(self, line: str) -> List[str]:
        """One INVEN: line in, zero or more things to say out."""
        m = _RECT.match(line)
        if m:
            self.rect = (int(m.group(1)), int(m.group(2)),
                         int(m.group(3)), int(m.group(4)))
            return []
        m = _OPEN.match(line)
        if m:
            return self._open(m)
        m = _ENTRY.match(line)
        if m:
            return self._entry(m)
        m = _NONE.match(line)
        if m:
            side = int(m.group(1))
            self.side, self.index, self.total = side, 0, 0
            self.selected = None
            self.last = empty_side(side)
            return [self.last]
        m = _PRICE.match(line)
        if m:
            return self._price(m)
        m = _SUMMARY.match(line)
        if m:
            return self._summary(m)
        said = drop_line(line)
        if said:
            return [said]
        if line.startswith("INVEN:close"):
            was, self.open = self.open, False
            self.container = None
            self.last = None
            self.price = None
            self.offered = None
            return [tr("inventory.closed", "Closed.")] if was else []
        return []

    # -- handlers -------------------------------------------------------

    def _price(self, m) -> List[str]:
        """What the two piles are worth, when it changes.

        The hook behind this runs every time the engine recalculates -- twice
        on the way in, once for each side, and again after every item moved --
        so it fires far more often than there is anything new to say. Speaking
        only on a change is what keeps it from talking over the item that was
        just moved.

        Both totals in one sentence, because the question is never what one
        pile is worth. It is whether they balance, and that is a comparison.
        """
        asking = int(m.group(1))
        offering = int(m.group(2))
        now = (asking, offering)
        self.party = m.group(6) == "1"

        # Whether this recalculation was caused by the offer being made. It is
        # the only signal the mod has that a trade was attempted, and it comes
        # from the engine rather than from the mod having sent a click.
        if m.group(5) == "1":
            self.offered = now
            return [tr("barter.offered", "Offered. {balance}",
                       balance=self._balance(asking, offering))]

        # The reading straight after an offer says what became of it. **An
        # empty table is the acceptance**: the engine clears both sides when the
        # goods change hands, and leaves them exactly as they were when the
        # shopkeeper says no. So this is read out of what the engine did rather
        # than out of what the mod asked for.
        if self.offered is not None:
            was, self.offered = self.offered, None
            self.price = now
            if now == (0, 0):
                gave, got = was[1], was[0]
                if got:
                    return [tr("barter.traded", "Traded. You gave {gave} and took {got}.",
                               gave=gave, got=got)]
                # Offering with nothing asked for is a legal thing to do and
                # not usually a thing anyone means to do.
                return [tr("barter.gave_away", "Traded. You gave {gave} for nothing.",
                           gave=gave)]
            return [tr("barter.refused", "They would not take that.")]

        if now == self.price:
            return []
        first, self.price = self.price is None, now
        if not (asking or offering) and not first:
            return [tr("barter.empty_table", "Nothing on the table.")]
        return [self._balance(asking, offering)]

    def _balance(self, asking: int, offering: int) -> str:
        """Both totals, and whether they meet.

        The verdict is given only when it is settled one way. "Enough" is what a
        sighted player reads off the two numbers at a glance, and working it out
        from two figures read aloud a second apart is exactly the sort of
        arithmetic this mod exists to save.
        """
        said = tr("barter.balance", "They want {asking}. You are offering {offering}.",
                  asking=asking, offering=offering)
        if asking and offering >= asking:
            said += " " + tr("barter.enough", "Enough.")
        elif asking:
            said += " " + tr("barter.short", "{amount} short.", amount=asking - offering)
        return said

    def _open(self, m) -> List[str]:
        mode = int(m.group(1))
        name = m.group(2).strip()
        theirs = int(m.group(3))
        mine = int(m.group(4))
        self.open = True
        self.container = name or None
        self.mode = mode

        # Name the window from the game mode rather than from whether a
        # container happened to be found: a corpse with nothing on it and a
        # window that failed to identify what it was looking at should not
        # sound the same.
        what = screens.mode_name(mode)
        if name:
            head = "{}: {}. {}.".format(what.capitalize(), name, _items(theirs))
        else:
            head = "{}.".format(what.capitalize())
        return ["{} {} {}".format(head, tr("inventory.you_carry", "You are carrying {items}.",
                                           items=_items(mine)), help_text())]

    def _entry(self, m) -> List[str]:
        side = int(m.group(1))
        index = int(m.group(2))
        total = int(m.group(3))
        name = m.group(4).strip()
        count = int(m.group(5))
        weight = int(m.group(6))
        slot = int(m.group(7))

        self.side, self.index, self.total = side, index, total
        self.selected = name or None
        # How many of it there are. The "Move Items" window needs this to say
        # "1 of 24" rather than a bare number, and it is already on this line.
        self.selected_count = count

        if slot >= 0:
            # A worn slot. The slot's name comes first because it is what the
            # player is navigating by -- they are asking what is in their right
            # hand, not hunting for an item.
            label = worn_slot(slot)
            text = "{}, {}.".format(label, name or tr("inventory.empty", "empty"))
            self.last = text
            return [text]

        if not name:
            # An entry the engine offered but would not name. This used to
            # return nothing, which is the one answer a blind player cannot act
            # on: pressing a key and hearing silence is indistinguishable from
            # the key never arriving, and that is exactly how it was reported.
            # Say the position, which is true, and say the name is missing,
            # which is also true and is a bug report rather than a guess.
            text = tr("inventory.unnamed", "Unnamed item. {position}.",
                      position=words.of(index + 1, total))
            self.last = text
            return [text]

        parts = [name]
        rounds = int(m.group(12)) if m.group(12) else -1
        if rounds >= 0:
            # Ammunition: both numbers, because each alone was misheard. The
            # rounds are the shots you have; the boxes are what a trader prices
            # and what the "Move Items" window counts.
            if count > 1:
                parts.append(tr("inventory.boxes", "{count} boxes", count=count))
            if rounds == 1:
                parts.append(tr("inventory.one_round", "1 round"))
            else:
                parts.append(tr("inventory.rounds", "{count} rounds", count=rounds))
        # Only say "3" when there is more than one. A quantity of one on every
        # single item is noise on every single item.
        elif count > 1:
            parts.append(str(count))
        if weight > 0:
            if weight == 1:
                parts.append(tr("inventory.one_pound", "1 pound"))
            else:
                parts.append(tr("inventory.pounds", "{count} pounds", count=weight))
        # Its value, while trading. Off a barter screen nobody is pricing
        # anything, and it would be one more number on every line.
        value = int(m.group(11)) if m.group(11) else -1
        if self.bartering and value > 0:
            if rounds >= 0:
                parts.append(tr("barter.worth_box", "worth {value} a box", value=value))
            elif count > 1:
                parts.append(tr("barter.worth_each", "worth {value} each", value=value))
            else:
                parts.append(tr("barter.worth", "worth {value}", value=value))
        text = "{}. {}.".format(", ".join(parts), words.of(index + 1, total))
        self.last = text
        return [text]

    def _summary(self, m) -> List[str]:
        carried = int(m.group(2))
        capacity = int(m.group(3))
        mine = int(m.group(4))
        theirs = int(m.group(5))
        ap_cost = int(m.group(6))

        # The counts a move actually changes. An item leaving the carried list
        # for an equipment slot changes this and nothing about the slot side's
        # own reading, which is why checking the selected side called every
        # successful equip a failure.
        self.counts = (carried, mine, theirs)

        parts = [tr("inventory.summary", "Carrying {items}, {weight} of {capacity} pounds.",
                    items=_items(mine), weight=carried, capacity=capacity)]
        if theirs:
            parts.append(tr("inventory.there", "{items} there.", items=_items(theirs)))
        # The AP cost of an inventory action only exists during a fight, and it
        # is the number that decides whether swapping a weapon is affordable.
        if ap_cost > 0:
            if ap_cost == 1:
                parts.append(tr("inventory.ap_one", "1 action point to use an item."))
            else:
                parts.append(tr("inventory.ap", "{ap} action points to use an item.",
                                ap=ap_cost))
        return [" ".join(parts)]

    @property
    def bartering(self) -> bool:
        return self.open and bool(getattr(self, "mode", 0) & screens.MODE_BARTER)

    def totals(self) -> Optional[str]:
        """Both sides of the table, for asking at any time."""
        if not self.bartering:
            return None
        if not self.price or self.price == (0, 0):
            return tr("barter.empty_table", "Nothing on the table.")
        return self._balance(*self.price)

    def lopsided(self) -> Optional[str]:
        """Why an offer should be asked about twice, or None if it need not.

        Offering goods for nothing is a legal trade, and an expensive one when
        it is a whole purse of caps put up while meaning to buy. So is paying
        far more than the goods come to. Both are things a sighted player sees
        at a glance in the two totals before pressing; here they are said, and
        the offer waits for a second press. A party member is exempt: handing
        a companion things for nothing is the point of trading with them.
        """
        if not self.bartering or not self.price or self.party:
            return None
        asking, offering = self.price
        if offering <= 0:
            return None
        if asking <= 0:
            return tr("barter.for_nothing", "You are offering {offering} for nothing.",
                      offering=offering)
        if offering >= 2 * asking and offering - asking >= 20:
            return tr("barter.overpaying",
                      "You are offering {offering} for goods worth {asking}.",
                      offering=offering, asking=asking)
        return None

    def repeat(self) -> Optional[str]:
        return self.last
