"""The dialogue screen, read out of the game's own memory.

Dialogue was the largest thing a blind player could not reach: the engine draws
the NPC's line in one box and the replies in another, and neither is anything a
screen reader can see. It looked like the hardest feature left, because every
other mouse-only screen in this game has needed the mod to aim a pointer at
something. This one does not, and that is worth explaining, because it changed
the whole shape of the work.

**The engine already binds the replies to the number keys.** Option *i* is
chosen by pressing `1 + i`, and the engine says so itself: each option's GNW
button carries the release code 49 + index, which is ASCII `'1'` upward.
Measured on a live conversation with Klint, not taken from documentation --
the same discovery, by the same route, as the loot window's TAKE ALL turning
out to be the `A` key. So choosing a reply needs no pointer, no aim, and no
verification that the pointer landed where it was meant to. Dialogue is pure
reading.

**And the text is in static memory**, not behind the script interface:

    0x0058F4E4  what the NPC just said, char[900]
    0x0058F4D8  which .msg file that line came from
    0x0058F4DC  which line of it -- a two-int identity for "have they spoken
                again?", far cheaper and sharper than comparing 900 bytes
    0x0058FF70  the replies: 30 entries, 928 bytes apart, text at +0x18
    0x005186D8  how many of those 30 are real
    0x00518744  the dialogue window's handle: -1 when no conversation is up

Confirmed against the running retail game -- all six read as zero and -1 with
no conversation on screen, and every one of them filled in with Klint's
greeting the moment one opened.

**The count is load-bearing.** Fallout's arrays are never cleared, only
overwritten: entry 4 of a five-reply conversation is still sitting there,
perfectly readable, during the next two-reply one. The action menu learned this
the hard way and carries a whole cross-check because of it. Here the engine
publishes the length, so the rule is simply that nothing past it is looked at.

Nothing here is remembered between reads. Every announcement re-reads the
screen, so what is spoken is what is on it -- the rule the whole mod is built
on, and one that costs nothing when the source is six memory reads.
"""

from __future__ import annotations

import struct
from typing import List, NamedTuple, Optional
from ..i18n import tr
from .. import words

# -- where the engine keeps it -----------------------------------------------

REPLY_TEXT = 0x0058F4E4
REPLY_MSGLIST = 0x0058F4D8
REPLY_MSGID = 0x0058F4DC

OPTIONS = 0x0058FF70
OPTION_COUNT = 0x005186D8

# -1 with no conversation on screen; a GNW window handle while one is up. Used
# only as a sanity check -- the game mode from the script is what actually says
# a conversation is happening.
WINDOW = 0x00518744

# Entry layout: messageListId, messageId, reaction, proc, btn, top, text[900],
# bottom. The text offset and the stride are what matter here.
OPTION_TEXT = 0x18
OPTION_STRIDE = 928
OPTION_MAX = 30

TEXT_MAX = 900

# The engine's own "[Done]" entry, which ends a conversation, is built rather
# than loaded from a .msg file and says so: both of its message ids are -2.
DONE_MSGLIST = -2


def clean(text: str) -> str:
    """Strip the bullet the engine puts in front of every reply.

    Measured: option text begins with the byte 0x95, which is a literal
    bullet character in the game's codepage, then a space. It is the same kind
    of thing as the colour byte on the interface bar's messages -- formatting
    that a sighted player sees as a shape rather than reads as a word, so
    speaking it would add "bullet" to the front of every single reply.

    Anything else the game wrote is left exactly as it wrote it. The square
    brackets around "[Done]" stay: they are the game's own punctuation, they
    appear on screen, and screen readers already know what to do with them.
    """
    text = text.strip()
    while text and (text[0] == "•" or ord(text[0]) < 32):
        text = text[1:].lstrip()
    return text.strip()


class Reading(NamedTuple):
    """One look at the dialogue screen."""

    msglist: int
    msgid: int
    reply: str
    options: List[str]

    def key(self) -> tuple:
        """What counts as "the screen changed".

        The message ids alone are not enough. A conversation can loop back to
        the line it just said -- ask the same question twice and the ids are
        identical -- so the replies on offer are part of the identity too.
        """
        return (self.msglist, self.msgid, self.reply, tuple(self.options))

    @property
    def ending(self) -> bool:
        """True when the only thing left to say is the engine's own [Done]."""
        return self.msglist == DONE_MSGLIST


class Dialogue:
    """Reads the conversation on screen. Never writes, never remembers."""

    def __init__(self, proc) -> None:
        self.proc = proc

    def showing(self) -> bool:
        """Is a dialogue window open? Cross-check, not the primary test."""
        handle = self.proc.read_i32(WINDOW)
        return handle is not None and handle >= 0

    def count(self) -> int:
        n = self.proc.read_i32(OPTION_COUNT)
        if n is None or n <= 0:
            return 0
        return min(n, OPTION_MAX)

    def option(self, index: int) -> str:
        """Reply `index`, counting from zero. Empty if it cannot be read."""
        if not 0 <= index < OPTION_MAX:
            return ""
        addr = OPTIONS + index * OPTION_STRIDE + OPTION_TEXT
        return clean(self.proc.read_cstring(addr, max_len=TEXT_MAX) or "")

    def read(self) -> Optional[Reading]:
        msglist = self.proc.read_i32(REPLY_MSGLIST)
        msgid = self.proc.read_i32(REPLY_MSGID)
        if msglist is None or msgid is None:
            return None
        reply = clean(self.proc.read_cstring(REPLY_TEXT, max_len=TEXT_MAX) or "")
        # Exactly `count` of them, empties included. An unreadable entry keeps
        # its place in the list because the place IS the answer: reply three is
        # chosen by pressing 3 whether or not reply two could be read, and
        # closing the gap would renumber every reply below it.
        options = [self.option(i) for i in range(self.count())]
        return Reading(msglist=msglist, msgid=msgid, reply=reply,
                       options=options)


# -- putting it into words ---------------------------------------------------

def hint_text() -> str:
    return tr("dialogue.hint", "Enter says the reply you are on, or press its number.")


def say_options(options: List[str]) -> str:
    """The replies on offer, numbered by the key that chooses them."""
    if not options:
        return tr("dialogue.no_replies", "No replies offered.")
    said = [tr("dialogue.replies", "{count} replies.", count=len(options))
            if len(options) != 1 else tr("dialogue.one_reply", "One reply.")]
    for index, text in enumerate(options):
        if not text:
            # Numbered anyway. Silence where a reply should be is a fact about
            # the screen worth stating -- and the number still works.
            said.append(tr("dialogue.unreadable_numbered", "{number}, unreadable.",
                           number=index + 1))
            continue
        said.append("{}, {}".format(index + 1, text.rstrip(".") + "."))
    return " ".join(said)


def say_option(index: int, options: List[str]) -> str:
    """One reply, said the way a list cursor should say it.

    "Three of five" rather than just the text, because the number is not
    decoration here -- it is the key that says this line. A player who steps to
    a reply and then wants to say it needs to know which digit that is.
    """
    if not options:
        return tr("dialogue.no_replies", "No replies offered.")
    index = max(0, min(index, len(options) - 1))
    return "{}. {}".format(words.of(index + 1, len(options)),
                           options[index] or tr("dialogue.unreadable", "Unreadable."))


def say_reading(reading: Reading, opening: bool = False,
                hint: bool = False) -> str:
    """Everything on the dialogue screen, in the order a reader wants it.

    The NPC's line first: it is what the replies are answers to, and hearing
    the answers before the question is the wrong way round.
    """
    parts: List[str] = []
    if opening:
        parts.append(tr("dialogue.opening", "Conversation."))
    if reading.reply:
        parts.append(reading.reply.rstrip(".") + ".")
    parts.append(say_options(reading.options))
    if hint:
        parts.append(hint_text())
    return " ".join(p for p in parts if p)
