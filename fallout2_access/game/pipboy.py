"""The Pip-Boy 2000: what it offers, and how to reach it without a pointer.

This is the last big screen in the game that had nothing at all, and it is the
hardest kind: **entirely mouse-driven, and its text is not text.**

Every other panel this mod reads keeps its words somewhere -- the dialogue
screen in a static buffer, the save screen in a copy of each save's header, the
inventory in the objects themselves. The Pip-Boy paints its lines straight into
the window bitmap and keeps nothing. That was not assumed; it was measured three
ways on a live game with the panel open:

* Every string address in `pipboy.msg` and `quests.msg` -- 1,322 of them -- was
  searched for across all writable memory. The only arrays holding any of them
  are the two message lists themselves. There is no list of "the lines this page
  is drawing" anywhere.
* The text of a line that was visibly on screen (`Rest for ten minutes`) occurs
  exactly **once** in the whole process: in the message list it was loaded into.
  So the engine does not copy a line before drawing it either.
* A scan for the shape such a list would have -- runs of `{char* text, int
  flag}` -- found none in the executable's data.

So the words cannot be read. What *can* be read is the engine's own account of
where everything is: GNW keeps a button for every control and for **every row a
page draws**, with its rectangle and its event code. That is the whole basis of
this file. The panel is navigated by reading those buttons, and a choice is made
by clicking the rectangle the engine gave -- the same route the save screen's
page arrows and the inventory's rows already use.

**Every code lives in the release field, and every one is above 256.** So unlike
the loot window's TAKE ALL, no key presses any of these; each one has to be
pointed at. `uiwindow.Button.release` exists because of this screen.

Measured on a live game, at 1024x768, with the panel at (192,94):

    fresh                504 alarm clock, 500-503 the four lights,
                         768 and 769 a small unidentified pair
    STATUS      500      2 rows, codes 507 508
    AUTOMAPS    501      1 row,  code  507
    ARCHIVES    502      2 rows, codes 507 508
    ALARM CLOCK 504      13 rows, codes 510 to 522

A row is 350x10 at x=254, and rows sit 20 pixels apart. Row codes are the
engine's own line numbering, and the number a page starts at is the number of
header lines it draws above its list.

**Rows leak.** Opening a second page does not destroy the first page's rows, and
re-rendering the same page adds a duplicate set -- both measured. GNW puts new
buttons at the head of the list, so the live page is the run at the head, and
`rows()` below takes exactly that run and stops.

What is offered here, and what is not:

* **The alarm clock is read and operated in full.** Its options are
  `pipboy.msg` 302 upwards in order, so a row's name is its position -- which is
  a rule rather than a reading, and is therefore checked before it is trusted.
* **The other pages can be reached, counted and clicked, and their entries are
  named by position rather than by name.** Saying "entry 2 of 2" is worth a
  great deal more than silence and is the one thing that is certainly true. It
  is also not pretending: a page whose contents cannot be read says so.
"""

from __future__ import annotations

import datetime
import struct
from typing import List, NamedTuple, Optional, Tuple

# -- the panel ---------------------------------------------------------------
#
# 640x480 like the character sheet and the save screen, so the size does not
# name it. The STATUS light does: no other panel carries a button whose release
# code is 500.
PANEL_WIDTH = 640
PANEL_HEIGHT = 480

# The five places you can go, by the event code each raises.
STATUS = 500
AUTOMAPS = 501
ARCHIVES = 502
CLOSE = 503
ALARM_CLOCK = 504

# In the order they appear down the panel. The alarm clock is the small button
# above the four lights, which is why it comes first -- and it is also the one
# thing on this screen a player needs regularly, so leading with it costs
# nothing and saves four keystrokes.
DESTINATIONS = (ALARM_CLOCK, STATUS, AUTOMAPS, ARCHIVES, CLOSE)

# A pair of small buttons at (140,334) and (140,348), present on every page.
# Deliberately **not bound to anything**: what they do has not been measured,
# and this project does not ship a key whose effect it has not seen. Recorded so
# the next person starts from a fact rather than from a rediscovery.
UNKNOWN_PAIR = (768, 769)

# The rows a page draws, by event code. 505 is the engine's first line; a page
# whose list starts at 507 has drawn two header lines above it.
ROW_FIRST = 505
ROW_LAST = 767          # below UNKNOWN_PAIR, which are not rows
ROW_STRIDE = 20         # pixels between one row and the next

# -- the Pip-Boy's own words -------------------------------------------------
#
# pipboy.msg, found by scanning the executable's data for MessageList structures
# and keeping the one holding "Rest for ten minutes".
#
# **Loaded only while the panel is open.** Measured: shut, open, shut again --
# 0 entries, 1146, 0. The globals stay where they are; it is the array they
# point at that comes and goes. That costs nothing, since every caller here runs
# with the panel up, but it does mean a read that happens to fall outside that
# window returns nothing rather than failing, which is why the cache below is
# only allowed to keep an answer it actually got.
MSG_PIPBOY = 0x00664348

# What to call each destination. These are the page titles the panel draws, not
# the labels painted into the background art -- the art is a picture and has no
# text to quote. They are the game's own words for the same four places, so a
# translated game reads out translated, which is the whole reason for going
# through the message list rather than writing "Status" here.
#
# CLOSE takes 214, "DONE". The art says CLOSE; `pipboy.msg` has no such string,
# and 214 is this file's own word for the control that leaves. Between an
# English word this project invented and a translated word the game uses for
# exactly this, the game's wins.
MSG_NAME = {
    ALARM_CLOCK: 300,   # ALARM CLOCK
    STATUS: 202,        # STATUS
    AUTOMAPS: 205,      # AUTOMAPS
    ARCHIVES: 206,      # VIDEO ARCHIVES
    CLOSE: 214,         # DONE
}

# "You cannot rest at this location!" -- recorded, and deliberately not used.
# The engine paints it onto the panel like everything else here, so there is no
# way to know it has appeared. A refused rest is reported from the clock not
# moving instead, which is a measurement rather than a message, and which also
# covers resting until healed when you are already well.
MSG_CANNOT_REST = 215

# What a destination does, said only where the game's word for it does not say.
#
# **Exactly one entry, and it stays that way.** STATUS is a bad name for the
# quest screen and it is the game's name for it; a gloss was added here and
# taken straight back out. The rule is that the panel reads as the game wrote
# it, and a mod that quietly improves the game's labels is one where the player
# and everyone else are looking at different software.
#
# The bottom light is the exception because there is no word to keep faith
# with. The art says CLOSE, `pipboy.msg` has no such string, and 214 -- the
# nearest thing the file has -- reads out as "Done", which is not obviously the
# way out when you meet it at the end of a list of places to go.
DOES = {CLOSE: "closes the Pip-Boy"}

# The rest options, in the order the alarm clock page lists them: ten minutes
# through six hours, the four "rest until" times, rest until healed, and rest
# until the party is healed.
REST_FIRST = 302
REST_LAST = 315
REST_COUNT = REST_LAST - REST_FIRST + 1     # 14

# The page drops the last option when you have nobody with you, and drops
# nothing else. Measured at 17:24 on a party-less character: thirteen rows, so
# all four "rest until <time>" options were listed even though two of those
# times had already passed that day. That rules out the obvious alternative
# rule -- that the list is trimmed by the clock -- which would have made every
# name after the eighth wrong for half of every day.
REST_ROW_COUNTS = (REST_COUNT - 1, REST_COUNT)

# Where the alarm clock's list starts. Five header lines sit above it.
ALARM_ROW_FIRST = 510


# -- what the pages are lists of ---------------------------------------------
#
# The panel keeps no text, but it does keep the **tables it builds its lists
# from**, and those are as good as text: they are message numbers, and the mod
# already knows how to read a message list. So the words are still the game's
# own and still arrive translated. What had to be established was the rule --
# which entries the engine shows -- and that was read out of the engine's code
# rather than guessed, after a rule that looked obvious predicted one row where
# the panel drew two.
#
# `data/quests.txt`, parsed at each open into 20-byte records:
#
#     location   a message number in map.msg -- "Arroyo", "The Den"
#     description  a message number in quests.msg
#     gvar       which global variable this quest's progress lives in
#     display    show the quest once that variable reaches this
#     completed  and call it done once it reaches this
QUEST_TABLE = 0x0051C128
QUEST_COUNT = 0x0051C12C
QUEST_STRIDE = 20

# `data/holodisk.txt`, 12-byte records: the global that says you have it, its
# name in pipboy.msg, and the message number its text starts at.
#
# Twenty of them, named 401 to 420. **Message 400, the Vault 13 holodisk, is
# not in this table** -- the engine handles that one somewhere else -- so it is
# not offered here rather than being invented.
HOLODISK_TABLE = 0x0051C130
HOLODISK_COUNT = 0x0051C134
HOLODISK_STRIDE = 12

# How many rest options the alarm clock is offering, straight from the engine.
# Found by reading the code that builds the page's buttons, which passes this
# as the count -- so the naming rule below is now checkable against a number the
# engine states rather than only against the row count it produces.
REST_OPTION_COUNT = 0x0051C138

# The game's global variables: an int per variable, and every quest and holodisk
# is gated on one. Found by looking for an array of small numbers, mostly zero,
# long enough to cover every index the quest table uses -- and confirmed by what
# it said: the two variables set on a character two days into the game were
# exactly "Rescue Nagor's dog" and "Find Vic the Trader".
GAME_GLOBALS = 0x005186C0

# One byte per movie, 1 once you have seen it. The Video Archives page walks
# indices 2 to 15 and lists the ones set, naming each from pipboy.msg 500 plus
# its index.
MOVIES_SEEN = 0x00596C78
MOVIE_FIRST = 2
MOVIE_LAST = 15
MSG_MOVIE = 500

# map.msg, which is where quest location names live. **Not quests.msg**, which
# holds only the descriptions -- an hour went into that, because the location
# numbers resolve perfectly well against quests.msg and come back as sentences
# from a completely different part of the game.
MSG_MAP = 0x00631D48
MSG_QUESTS = 0x00664410

# The line counts the engine works out for itself while drawing a page. Read as
# a check on the mod's own reckoning, never as a substitute for it: a count is
# not a list, and what the player needs is the names.
#
# They are only meaningful once the page in question has been drawn, which is
# exactly when they are consulted. All four were confirmed against the panel:
# one quest location and no holodisks on a two-day-old character, two films in
# the archives, one map.
LINES_QUEST_LOCATIONS = 0x00664418
LINES_STATUS_HOLODISKS = 0x0066444C
LINES_ARCHIVES = 0x00664520
LINES_AUTOMAPS = 0x0066450C

# A holodisk's text is consecutive messages from where its record points, with
# these two markers in the stream. They are the game's own layout, not a
# convention invented here.
END_PARAGRAPH = "**END-PAR**"
END_DISK = "**END-DISK**"

# Nothing sane indexes a global variable beyond this. A table read out of freed
# memory is the case being guarded against, and a wild index is how it shows up.
MAX_GLOBALS = 4096


class Quest(NamedTuple):
    location: int       # a map.msg number
    description: int    # a quests.msg number
    gvar: int
    display: int        # shown once the variable reaches this
    completed: int      # and done once it reaches this


class Holodisk(NamedTuple):
    gvar: int           # non-zero once you have it
    name: int           # a pipboy.msg number
    text: int           # where its text starts, in pipboy.msg


def _table(proc, ptr_addr: int, count_addr: int, stride: int, kind):
    """Read one of the Pip-Boy's parsed tables, or [] if it is not there.

    Both tables are built when the panel opens and freed when it closes, so
    "not there" is the ordinary state rather than a fault.
    """
    count = proc.read_i32(count_addr)
    base = proc.read_u32(ptr_addr)
    if not count or not base or count < 0 or count > 4096:
        return []
    blob = proc.read_chunked(base, stride * count)
    if not blob or len(blob) < stride * count:
        return []
    out = []
    for i in range(count):
        fields = struct.unpack_from("<%di" % (stride // 4), blob, i * stride)
        out.append(kind(*fields))
    return out


def quests(proc) -> List[Quest]:
    return _table(proc, QUEST_TABLE, QUEST_COUNT, QUEST_STRIDE, Quest)


def holodisks(proc) -> List[Holodisk]:
    return _table(proc, HOLODISK_TABLE, HOLODISK_COUNT, HOLODISK_STRIDE,
                  Holodisk)


def globals_upto(proc, highest: int) -> Optional[List[int]]:
    """The game's global variables, as far as anything here needs them."""
    if highest < 0 or highest >= MAX_GLOBALS:
        return None
    base = proc.read_u32(GAME_GLOBALS)
    if not base:
        return None
    blob = proc.read_chunked(base, 4 * (highest + 1))
    if not blob or len(blob) < 4 * (highest + 1):
        return None
    return list(struct.unpack("<%di" % (highest + 1), blob))


def movies_seen(proc) -> List[int]:
    """The indices of the archived movies you have watched."""
    blob = proc.read_chunked(MOVIES_SEEN + MOVIE_FIRST,
                             MOVIE_LAST - MOVIE_FIRST + 1)
    if not blob:
        return []
    return [MOVIE_FIRST + i for i, b in enumerate(blob) if b == 1]


def shown_locations(table: List[Quest], values: List[int]) -> List[int]:
    """The locations the Status page lists, in the order it lists them.

    This is the engine's own loop, and it is worth writing down exactly, since
    reasoning about it from the outside got it wrong twice. Walk the table in
    order; a quest counts when its variable has reached its display threshold;
    the first quest that counts puts its location on the list, and the rest of
    that location's block is then skipped. The table is sorted by location, so a
    block is all of a place's quests.

    The threshold really is `>=`, including zero: "Retrieve the GECK" has a
    display threshold of nothing at all, which is why Arroyo is on the list from
    the first minute of the game.
    """
    out: List[int] = []
    last = -1
    for quest in table:
        if quest.location == last:
            continue
        if not (0 <= quest.gvar < len(values)):
            continue
        if values[quest.gvar] >= quest.display:
            out.append(quest.location)
            last = quest.location
    return out


def quests_at(table: List[Quest], values: List[int], location: int):
    """(description number, finished) for each quest shown at one location.

    `finished` is not the mod being helpful. The engine compares the same
    variable against the same field and, when it has been reached, **draws that
    line in a different colour** -- a second colour byte and a second draw flag,
    which is as far as this panel ever goes towards saying a thing is done.
    Colour is not available through a screen reader, so it arrives as a word.

    The comparison is `>=`, matching the `jl` the engine branches on.
    """
    out = []
    for quest in table:
        if quest.location != location:
            continue
        if not (0 <= quest.gvar < len(values)):
            continue
        value = values[quest.gvar]
        if value >= quest.display:
            out.append((quest.description, value >= quest.completed))
    return out


def held_holodisks(table: List[Holodisk], values: List[int]) -> List[Holodisk]:
    """The ones you actually have. The test is the engine's: not zero."""
    return [h for h in table
            if 0 <= h.gvar < len(values) and values[h.gvar] != 0]


def disk_paragraphs(message, first: int, limit: int = 400) -> List[str]:
    """A holodisk's text, as paragraphs.

    The engine stores it as consecutive messages, hard-wrapped to the width of
    the panel, with `**END-PAR**` between pages and `**END-DISK**` at the end.
    The wrapping is a fact about the panel rather than about the writing, so the
    lines are joined back up: a screen reader has no column to respect, and
    hearing a sentence delivered in six pieces is worse than hearing it.
    """
    paragraphs: List[str] = []
    lines: List[str] = []
    for num in range(first, first + limit):
        text = message(num)
        if text is None:
            break
        text = text.strip()
        if text == END_DISK:
            break
        if text == END_PARAGRAPH:
            if lines:
                paragraphs.append(" ".join(lines))
            lines = []
            continue
        if text:
            lines.append(text)
    if lines:
        paragraphs.append(" ".join(lines))
    return paragraphs


# -- the clock ---------------------------------------------------------------
#
# Ticks since the game began, ten to the second. Found by diffing the
# executable's writable data across four seconds and keeping the one value that
# rose at a rate a clock would.
#
# **Confirmed against the engine's own writing, not against a belief about it.**
# Fallout 2 records the in-game date and the raw tick count in every SAVE.DAT
# header, big-endian, at offsets 101 and 107. Three real saves:
#
#     ticks     header date     ticks // 864000
#     302677    25/07/2241      0
#     322141    25/07/2241      0
#     1488625   26/07/2241      1
#
# So a day is 864,000 ticks and day zero is 25 July 2241, stated three times by
# the game itself. The first of those saves is 302,677 ticks, and 302,400 is
# exactly 08:24:00 -- the save was taken 27 seconds into a new game, which puts
# the start of the game at 08:24 and leaves no free parameter to guess at.
GAME_TIME = 0x0051C720
TICKS_PER_SECOND = 10
SECONDS_PER_DAY = 24 * 60 * 60
TICKS_PER_DAY = TICKS_PER_SECOND * SECONDS_PER_DAY
EPOCH = datetime.date(2241, 7, 25)

# Where a save keeps the same two things, so a test can check the arithmetic
# against a real file rather than against itself.
SAVE_OFF_GAME_DATE = 101    # three big-endian shorts: month, day, year
SAVE_OFF_GAME_TICKS = 107   # one big-endian int


class Clock(NamedTuple):
    date: datetime.date
    hour: int
    minute: int

    def say(self) -> str:
        """The date and time, in words that invent nothing.

        **The month is a number, and that is deliberate.** Fallout draws month
        names as art -- `PIPBOY_FRM_MONTHS` is a picture of twelve words -- so
        there is no string in the game to quote, and writing "July" here would
        be this mod inventing an English word for something a translated game
        shows in its own language. That is the same call already made about the
        body parts struck in combat, and the game itself sets the precedent: the
        save screen prints its dates as numbers too.

        The time is the mod's own prose, which is a different thing from
        inventing a name -- "half past five" is a rendering of a number, not a
        translation of a word the game displays.
        """
        return "{}. Day {} of month {}, {}.".format(
            say_time(self.hour, self.minute),
            self.date.day, self.date.month, self.date.year)


def say_time(hour: int, minute: int) -> str:
    """A clock time, spoken rather than printed.

    "17:24" is not a thing a screen reader says usefully -- depending on the
    voice it is "seventeen colon twenty four" or "one thousand seven hundred
    and twenty four" -- so the hour is said as a twelve-hour number with the
    part of the day after it, which is how anyone would read a clock aloud.
    """
    part = "in the morning"
    if hour >= 18:
        part = "in the evening"
    elif hour >= 12:
        part = "in the afternoon"
    twelve = hour % 12 or 12
    return "{}:{:02d} {}".format(twelve, minute, part)


def from_ticks(ticks: int) -> Clock:
    """The date and time a tick count means."""
    days, rest = divmod(ticks, TICKS_PER_DAY)
    seconds = rest // TICKS_PER_SECOND
    return Clock(date=EPOCH + datetime.timedelta(days=days),
                 hour=seconds // 3600,
                 minute=(seconds % 3600) // 60)


def clock(proc) -> Optional[Clock]:
    """What the Pip-Boy's clock says, or None if it cannot be read.

    Bounds-checked rather than trusted. A negative or absurd tick count means
    the address is wrong for this build, and a confidently wrong date is worse
    than none -- resting until morning is a decision made on this number.
    """
    ticks = proc.read_i32(GAME_TIME)
    if ticks is None or ticks < 0 or ticks > TICKS_PER_DAY * 400000:
        return None
    return from_ticks(ticks)


# -- the panel's controls ----------------------------------------------------


def window(proc):
    """The Pip-Boy's window, with its buttons, or None if it is not open.

    Found by the STATUS light rather than by size. The character sheet and the
    save screen are 640x480 panels too, and a size-only test would claim them --
    which does not mis-name one screen, it hides every other screen behind this
    one, exactly as a stuck flag once did to the save screen.
    """
    from . import uiwindow
    return uiwindow.live_window_with(proc, PANEL_WIDTH, PANEL_HEIGHT,
                                     release=STATUS)


def showing(proc) -> bool:
    """Is the Pip-Boy on screen right now?"""
    return window(proc) is not None


def destinations(win) -> List[Tuple[int, object]]:
    """The five places you can go, top to bottom, as (code, button).

    Read from the window rather than listed here, so a destination the engine is
    not currently offering is not offered by the mod either.
    """
    found = []
    for code in DESTINATIONS:
        button = win.by_code(code)
        if button is not None:
            found.append((code, button))
    return found


def rows(win) -> List[object]:
    """The rows the page currently on screen is drawing, top to bottom.

    **Only the live page's rows**, which is the whole difficulty. The engine
    does not destroy a page's row buttons when you move to another page, and
    re-rendering the same page adds a second set on top of the first -- both
    measured, by opening STATUS twice and watching 507 and 508 arrive again.

    GNW puts each new button at the head of the window's list, so a page's rows
    sit at the head in descending code order, with everything older below them.
    This walks the head and stops at the first button that does not continue the
    run, where "continues" means two things at once:

    * its code is one less than the last, and
    * its rectangle is one row higher, by the same step as the rest.

    The second test is what makes it safe. Codes alone would merge a live page
    starting at 510 into a stale page whose rows ended at 509 -- reachable as
    soon as a player has three quest locations -- and the merged list would be
    named entirely wrongly. Two pages never share a row grid, so the y step
    catches it.
    """
    run: List[object] = []
    step: Optional[int] = None
    for b in win.buttons:
        if not (ROW_FIRST <= b.release <= ROW_LAST):
            if run:
                break
            continue
        if not run:
            run.append(b)
            continue
        last = run[-1]
        if b.release != last.release - 1:
            break
        gap = last.top - b.top
        if gap <= 0 or (step is not None and gap != step):
            break
        step = gap
        run.append(b)
    return list(reversed(run))


def is_alarm_page(page_rows) -> bool:
    """Is the page on screen the alarm clock?

    Asked of the rows rather than remembered from the click that opened them, so
    it is still right when the player opened the page some other way. The alarm
    clock is the only page whose list starts at line 5.
    """
    return bool(page_rows) and page_rows[0].release == ALARM_ROW_FIRST


def rest_numbers(page_rows) -> Optional[List[int]]:
    """The `pipboy.msg` number of each rest option on screen, or None.

    The page lists message 302 upwards in order, dropping only the trailing
    "rest until party is healed" when you are travelling alone. That is a rule,
    not a reading, so it is checked before it is used: a row count the rule
    cannot account for means the rule is wrong for this build or this state, and
    the caller is told to fall back on naming rows by position.

    Refusing here is cheap. Naming them wrongly would have somebody rest six
    hours when they asked for ten minutes, in a game where time passes for
    everyone else too.
    """
    if not is_alarm_page(page_rows):
        return None
    if len(page_rows) not in REST_ROW_COUNTS:
        return None
    return [REST_FIRST + i for i in range(len(page_rows))]


class Pipboy:
    """Reads the Pip-Boy. Sends nothing; clicking lives in the watcher."""

    def __init__(self, proc, hwnd=None) -> None:
        self.proc = proc
        self.hwnd = hwnd
        self._messages: Optional[dict] = None
        self._lists: dict = {}
        self._quests: List[Quest] = []
        self._holodisks: List[Holodisk] = []

    def window(self):
        return window(self.proc)

    @property
    def showing(self) -> bool:
        return self.window() is not None

    def message(self, num: int) -> Optional[str]:
        """One of the Pip-Boy's own strings.

        Cached, because the list has over a thousand entries and this is asked
        on every arrival. **Only a real answer is cached**: the list exists only
        while the panel is open, so a read taken a frame early comes back empty,
        and remembering that empty would leave the mod unable to name anything
        for the rest of the session. The words themselves never change, so a
        cache filled once is good for the whole game.
        """
        from ..msg.memlist import read_message_list

        if not self._messages:
            lst = read_message_list(self.proc, MSG_PIPBOY)
            self._messages = lst.by_num() if lst else {}
        return self._messages.get(num)

    def name_of(self, code: int) -> str:
        """What to call a destination.

        Falls back on nothing: if the game's word cannot be read, the code is
        said instead. A destination that cannot be named is still a destination
        that can be reached, and "place 3 of 5" navigates perfectly well.
        """
        text = self.message(MSG_NAME.get(code, -1))
        if not text:
            return "Place {}".format(code - STATUS + 1)
        name = text.strip().rstrip(":").capitalize()
        does = DOES.get(code)
        return "{}, {}".format(name, does) if does else name

    def clock(self) -> Optional[Clock]:
        return clock(self.proc)

    def press(self, win, button) -> Tuple[bool, str]:
        """Click one of the panel's controls.

        Nothing on this screen answers to a key -- every code is above 256 and
        sits in the release field -- so a choice here is a pointer landing on a
        rectangle, and the rectangle is the engine's own.

        The same refusal that guards every other click in this mod applies: the
        pointer is driven until the engine agrees it is there, and if it will
        not agree, nothing is sent. There is less at stake here than on a hex --
        the worst a stray click on this panel does is open the wrong page -- but
        a click that silently lands somewhere else is exactly the failure a
        player cannot see, and one of these rows rests you for six hours.
        """
        import time as _time

        from ..input.send import guarded_click
        from .pointer import MenuMouse, aim_to

        if self.hwnd is None:
            return False, "not attached to the game"
        ok, _where, why = aim_to(self.proc, self.hwnd, *button.centre(win),
                                 reader=MenuMouse(self.proc))
        if not ok:
            return False, why or "could not put the pointer on it"
        # Let the arrival register before the button goes down. GNW decides
        # what the pointer is over on its own schedule, and a click sent in the
        # same breath as the last motion acts on where the pointer was -- the
        # same settle the save screen's page arrows need, for the same reason.
        _time.sleep(0.12)
        guarded_click(self.hwnd, "left", settle=0.3)
        return True, ""

    def rest_names(self, page_rows) -> Optional[List[str]]:
        """What each rest option says, or None if they cannot be vouched for."""
        numbers = rest_numbers(page_rows)
        if numbers is None:
            return None
        # The engine's own count of what it is offering. When it can be read it
        # decides, because it is a statement rather than an inference from how
        # many buttons happened to survive.
        stated = self.proc.read_i32(REST_OPTION_COUNT)
        if stated is not None and 0 < stated <= REST_COUNT:
            if stated != len(numbers):
                return None
        names = [self.message(n) for n in numbers]
        if not all(names):
            return None
        return [n.strip() for n in names]

    # -- the lists the other pages are made of -----------------------------

    def _msg(self, address: int) -> dict:
        """One of the game's message lists, cached once it has been read."""
        from ..msg.memlist import read_message_list

        cached = self._lists.get(address)
        if cached:
            return cached
        lst = read_message_list(self.proc, address)
        table = lst.by_num() if lst else {}
        if table:
            self._lists[address] = table
        return table

    def place_name(self, number: int) -> Optional[str]:
        return self._msg(MSG_MAP).get(number)

    def quest_text(self, number: int) -> Optional[str]:
        return self._msg(MSG_QUESTS).get(number)

    def _world(self):
        """The tables and the variables, or None if they cannot be read.

        Cached for the tables, never for the variables: the tables are the same
        two text files parsed again on every open, while the variables are the
        state of the game and change under you. Caching those would be the
        shadow state this project refuses everywhere else.
        """
        if not self._quests:
            self._quests = quests(self.proc)
        if not self._holodisks:
            self._holodisks = holodisks(self.proc)
        if not self._quests:
            return None, None, None
        highest = max([q.gvar for q in self._quests]
                      + [h.gvar for h in self._holodisks] + [0])
        values = globals_upto(self.proc, highest)
        if values is None:
            return None, None, None
        return self._quests, self._holodisks, values

    def status_entries(self) -> Optional[List[tuple]]:
        """What the Status page lists: ("place"|"disk", name, payload).

        Places first, then the holodisks you are carrying -- which is the order
        the engine draws them in, and it draws both on this one page.
        """
        table, disks, values = self._world()
        if table is None:
            return None
        out = []
        for location in shown_locations(table, values):
            name = self.place_name(location)
            if not name:
                return None
            out.append(("place", name.strip(), location))
        for disk in held_holodisks(disks, values):
            name = self.message(disk.name)
            if not name:
                return None
            out.append(("disk", name.strip(), disk))
        return out

    def quest_lines(self, location: int) -> List[str]:
        """The quests at one place, each said with whether it is finished."""
        table, _disks, values = self._world()
        if table is None:
            return []
        out = []
        for number, finished in quests_at(table, values, location):
            text = self.quest_text(number)
            if not text:
                continue
            text = text.strip()
            out.append("{} {}".format(text, "Done." if finished else "").strip())
        return out

    def disk_text(self, disk: Holodisk) -> List[str]:
        return disk_paragraphs(self.message, disk.text)

    def engine_drew(self, address: int) -> Optional[int]:
        """How many lines the engine says it drew, from one of its counters.

        The sharpest check available on a reconstruction: not "does my list
        have as many entries as there are buttons", but "does my list have as
        many entries as the engine counted". Only meaningful once the page has
        been drawn, which is the only time it is asked.
        """
        value = self.proc.read_i32(address)
        return value if value is not None and value >= 0 else None

    def archive_entries(self) -> Optional[List[str]]:
        """The films in the Video Archives, by name."""
        names = []
        for index in movies_seen(self.proc):
            name = self.message(MSG_MOVIE + index)
            if not name:
                return None
            names.append(name.strip())
        return names
