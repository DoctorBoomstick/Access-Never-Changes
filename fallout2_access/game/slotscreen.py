"""The save and load screens: which slot is highlighted, and what is in it.

These are the same screen twice, and the pair matter more than they look. A save
you cannot load is a slower way of losing an evening, and until now the mod
could read the savegame folder while the one screen that acts on it said
nothing at all.

**It was never a mouse problem.** The arrow keys already move the highlight --
measured, by watching a value rise on down and fall on up. The screen has been
navigable all along and simply silent, which is the failure this project keeps
meeting: a working thing that makes no sound is indistinguishable from a broken
one.

**Whether the screen is showing is asked of GNW's window list**, not of a flag,
and the difference is the most expensive lesson in this file. There was a flag,
0x00614858, "confirmed" by reading non-zero with the screen up and zero at the
main menu -- which is all the evidence you can gather from a screen you have
never closed. It does not clear on the way out. Since `screens.detect` tests
this screen before any other, one stuck flag did not mis-name one screen: it
hid every screen in the game behind it for the rest of the session.

That test has to work before a game is loaded, since no in-game script is
running at the main menu and there is no game mode to ask for. An open window is
a fact available in both places; `showing()` below finds the panel by its page
buttons, because at this resolution the character sheet and the Pipboy are
640x480 too.

`SELECTION` is the highlighted row, 0 to 9, clamping at both ends rather than
wrapping. The first candidate for this was wrong in an instructive way: it rose
on *both* arrows, because it counted keypresses rather than tracking a position.
Watching it rise and fall in opposite directions is what separated them.

`OCCUPIED` is ten flags saying whether each visible row holds a game. With five
quick saves in slots 11 to 15 it read all zeros on the first page and
[1,1,1,1,1,0,0,0,0,0] on the second -- the engine stating exactly what the
screen shows.

`SLOT_HEADERS` is the ten rows the screen is *displaying*, each one a verbatim
copy of that save's `SAVE.DAT` header -- same layout, so the same two offsets
read the character name and the description. Ten of them at 0x88 apart end at
exactly `OCCUPIED`, which is what confirms the stride rather than a guess about
it.

Reading those beats going to disk. It removes the step that was wrong for weeks:
the mod used to work out a slot number from a page it had counted, then look up
that number in the savegame folder. Read the row instead and there is no
arithmetic to be wrong about -- what is announced is what is on screen.

**The page is read, not counted, and this file used to say the opposite.** It
claimed the page number lived only on the heap and had to be caused by clicking.
That was wrong, and expensively: it lives in sfall's own data, because extra
pages are sfall's feature and not the engine's. The reason it went unfound is
that the search looked inside `C:\\WINDOWS\\SysWOW64\\ddraw.dll` -- sfall's
ddraw.dll loads Windows' ddraw.dll to forward to, two modules share the name,
and the lookup returned the wrong one.

The cost of counting instead of reading was not just clumsiness. Counting made
the mod announce "Slot 1" through "Slot 10" while the screen was showing slots
81 to 90, and report "Could not change page" on a page control that was working
perfectly -- the evidence it used for "did the page turn?" was the occupancy
flags, and stepping between two empty pages changes nothing. A page it could
read would have settled all of that immediately.
"""

from __future__ import annotations

import os
from typing import List, Optional
from ..i18n import tr
from .. import codepage

# The screen is recognised by its own window being OPEN, not by a flag.
#
# There was a flag here -- 0x00614858 -- and it was wrong in the way that costs
# the most: it read non-zero with the screen up and zero at a freshly launched
# main menu, which is exactly the evidence you get from testing a screen you
# have never closed. Once the save screen had been opened and left, it kept
# reading non-zero, and since `detect` consults this first and before anything
# else, every other screen in the game became unreachable -- the mod answered
# "load game" to the map, to character selection, to everything.
#
# The window is the honest test. It exists while the screen is up and is taken
# out of GNW's list when it closes, and the page buttons identify it among the
# other 640x480 panels.
def showing(proc) -> bool:
    """Is the save or load screen on screen right now?"""
    from . import uiwindow
    return uiwindow.live_window_with(
        proc, PANEL_WIDTH, PANEL_HEIGHT, PAGE_NEXT) is not None

# lsgame.msg, the save and load screen's own words.
#
# Found by scanning the executable's data for MessageList structures and
# keeping the one that contains "Save game already exists, overwrite?". It
# confirms itself structurally: a MessageList is {int count; item* entries},
# eight bytes, and this sits exactly eight bytes before SLOT_HEADERS below. The
# screen's text and the screen's slot table are neighbours, which is what you
# would expect and is a great deal better evidence than one lucky string match.
MSG_LSGAME = 0x00613D28
MSG_OVERWRITE = 131        # "Save game already exists, overwrite?"

# The confirmation box the screen puts over itself.
#
# Measured, both cases, on a live save screen: an empty slot raises a 290x85
# box and an occupied one raises a 302x127 box -- taller because the overwrite
# question runs to two lines. Both carry two buttons, and both are dismissed by
# Escape and confirmed by Enter, which was checked by watching slot 17 appear on
# disk after the second Enter.
#
# Matched by shape rather than by exact size, because the size follows the text
# and the text follows the translation. What does not vary is that it is a small
# panel with one or two buttons sitting over a 640x480 screen: one button is a
# notice, two is a question. The escape menu is 164x217 with five buttons and is
# excluded by both bounds.
CONFIRM_MIN_WIDTH = 200
CONFIRM_MAX_WIDTH = 520
CONFIRM_MIN_HEIGHT = 50
CONFIRM_MAX_HEIGHT = 200
CONFIRM_MAX_BUTTONS = 2


def confirm_box(proc):
    """The little dialog over the save or load screen, or None.

    Returned as the window itself, because the number of buttons is the one
    honest signal about what it wants: two means a question with a cancel, one
    means a notice that can only be acknowledged.
    """
    from . import uiwindow

    for win in uiwindow.live_windows(proc, buttons=True):
        if not CONFIRM_MIN_WIDTH <= win.width <= CONFIRM_MAX_WIDTH:
            continue
        if not CONFIRM_MIN_HEIGHT <= win.height <= CONFIRM_MAX_HEIGHT:
            continue
        if 1 <= len(win.buttons) <= CONFIRM_MAX_BUTTONS:
            return win
    return None


# The highlighted row on the visible page: 0..9, clamped at both ends.
SELECTION = 0x005193B8

# Ten flags, one per visible row: does that row hold a saved game?
OCCUPIED = 0x00614280

# The ten headers the screen is displaying, one per row, each a copy of that
# save's SAVE.DAT header. Ten at HEADER_SIZE apart land exactly on OCCUPIED,
# which is the check that makes the stride a measurement and not a guess.
SLOT_HEADERS = 0x00613D30
HEADER_SIZE = 0x88

SLOTS_PER_PAGE = 10

# The page controls, by the event code each raises. All four measured, by
# clicking each one and watching sfall's page offset: an earlier version of this
# file guessed at the outer two and said so, and the guess was wrong -- they are
# not "first" and "last" but ten-page jumps.
PAGE_PREV = 1355          # -1 page
PAGE_NEXT = 1357          # +1 page
PAGE_BACK_TEN = 1353      # -10 pages
PAGE_FORWARD_TEN = 1361   # +10 pages

# Where sfall keeps the first slot number the page is showing, less one: page 0
# reads 0, page 1 reads 10. An offset into the slots rather than a page number,
# which is why a search for a small page-sized integer never turned it up.
#
# An offset from sfall's module base, never an absolute address -- a DLL can be
# relocated, and the absolute 0x110EF4B8 it happened to load at is a fact about
# one launch.
PAGE_OFFSET_RVA = 0xEF4B8

# The control wraps: stepping forward from the last page reaches the first.
# Measured -- the offset went 9990 -> 0 -> 10 across two forward steps.
MAX_PAGES = 1000

# The window is a fixed 640x480 panel, centred. Computed from the client size
# rather than hardcoded, so another resolution moves it correctly.
PANEL_WIDTH = 640
PANEL_HEIGHT = 480


def panel_rect(client_width: int, client_height: int):
    """Where the save/load panel sits, given the game's client area."""
    return ((client_width - PANEL_WIDTH) // 2,
            (client_height - PANEL_HEIGHT) // 2,
            PANEL_WIDTH, PANEL_HEIGHT)


def pages_holding(saved_numbers) -> List[int]:
    """The pages that hold at least one saved game, in order.

    With a thousand pages available and a player's saves usually on one or two
    of them, stepping blindly is not navigation. This is what lets the mod say
    where the games are and go straight there.
    """
    return sorted({(n - 1) // SLOTS_PER_PAGE for n in saved_numbers})


# get_game_mode's SAVEGAME bit. Spelled out rather than imported, because
# screens.py imports this file to detect the screen and the cycle is not worth
# untangling for one constant.
MODE_SAVEGAME = 0x10


def page_count(game_dir: str) -> int:
    """How many pages of slots the screen offers.

    `ExtraSaveSlots` is a switch, not a count -- "Set to 1 to add additional
    pages of save slots", in sfall's own words. Reading it as a number of extra
    pages gave two, and two was wrong in the worst way available: it made the
    mod refuse to step forward past the second page, and it let a page be
    "identified" by elimination when the real answer was page 8.
    """
    path = os.path.join(game_dir, "ddraw.ini")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                name, _, value = line.partition("=")
                if name.strip().lower() == "extrasaveslots":
                    return MAX_PAGES if int(value.strip() or 0) else 1
    except (OSError, ValueError):
        pass
    return 1


def page_offset_address(proc) -> Optional[int]:
    """Where sfall keeps the page offset in this particular process.

    Asked for by path, not by name. Two modules in this process are called
    "ddraw.dll" -- sfall's, and the Windows one it forwards to -- and taking
    whichever a name lookup returned is how this variable stayed hidden.
    """
    directory = proc.directory
    if not directory:
        return None
    mod = proc.module_at("ddraw.dll", directory)
    if mod is None or not mod.base:
        return None
    return mod.base + PAGE_OFFSET_RVA


class SlotScreen:
    """Reads the save/load screen. Sends nothing and changes nothing."""

    def __init__(self, proc, hwnd: Optional[int] = None) -> None:
        self.proc = proc
        self.hwnd = hwnd
        # The script's game mode, when there is a script. None before a game is
        # loaded, which is itself informative: the only way to this screen from
        # the main menu is Load.
        self.mode: Optional[int] = None
        # Resolved once. sfall's base does not move while the process lives, and
        # the module walk is far too slow to repeat on every keypress.
        self._page_addr: Optional[int] = None
        self._page_looked = False
        self._messages: Optional[dict] = None

    def page_address(self) -> Optional[int]:
        if not self._page_looked:
            self._page_looked = True
            self._page_addr = page_offset_address(self.proc)
        return self._page_addr

    def page(self) -> Optional[int]:
        """Which page is showing, straight from sfall. None if unreadable.

        None means unreadable, and callers must treat it as such rather than
        falling back on a guess. The whole cost of the previous design was a
        page the mod believed without being able to check.
        """
        addr = self.page_address()
        if addr is None:
            return None
        value = self.proc.read_i32(addr)
        if value is None or value < 0 or value % SLOTS_PER_PAGE:
            return None
        page = value // SLOTS_PER_PAGE
        return page if page < MAX_PAGES else None

    def header(self, index: int):
        """(character, description) for a visible row, as the screen has them.

        Read from the engine's own copy of the save header rather than from the
        savegame folder, so no slot number has to be worked out to find it.
        """
        from .saves import OFF_CHARACTER, OFF_DESCRIPTION, SIGNATURE

        blob = self.proc.read_chunked(
            SLOT_HEADERS + HEADER_SIZE * index, HEADER_SIZE)
        if not blob or not blob.startswith(SIGNATURE):
            return None, None

        def text(at: int) -> str:
            end = blob.find(b"\x00", at)
            raw = blob[at:end if end >= 0 else len(blob)]
            return raw.decode(codepage.game(), "replace").strip()

        return text(OFF_CHARACTER), text(OFF_DESCRIPTION)

    @property
    def loading(self) -> bool:
        if self.mode is None:
            return True
        return not (self.mode & MODE_SAVEGAME)

    @property
    def panel(self):
        """The panel's rectangle, from the game's own client size."""
        if self.hwnd is None:
            return None
        from ..input.send import client_size
        width, height = client_size(self.hwnd)
        if width <= 0 or height <= 0:
            return None
        return panel_rect(width, height)

    @property
    def showing(self) -> bool:
        return showing(self.proc)

    def selection(self) -> Optional[int]:
        """The highlighted row, or None if it reads implausibly.

        Bounds-checked rather than trusted. This is the number that decides
        which saved game gets overwritten, and a stale or wrong read here is
        the one mistake in this project that destroys something.
        """
        value = self.proc.read_i32(SELECTION)
        if value is None or not (0 <= value < SLOTS_PER_PAGE):
            return None
        return value

    def occupied(self) -> List[bool]:
        """Which of the ten visible rows hold a game, straight from the engine.

        Preferred over deciding from the savegame folder alone: this is what the
        screen is actually displaying, and if the two ever disagree the screen
        is what the player is about to act on.
        """
        out: List[bool] = []
        for i in range(SLOTS_PER_PAGE):
            value = self.proc.read_i32(OCCUPIED + 4 * i)
            out.append(bool(value))
        return out

    def slot_number(self, page: int, index: int) -> int:
        """Which slot on disk a row is. Rows are 0-based, slots are 1-based."""
        return page * SLOTS_PER_PAGE + index + 1

    def message(self, num: int) -> Optional[str]:
        """One of the save screen's own strings, or None.

        Read from the game rather than written here, so the overwrite warning
        arrives already translated. Cached, because the list is on the heap and
        walking it is not free at twenty polls a second.
        """
        from ..msg.memlist import read_message_list

        if self._messages is None:
            lst = read_message_list(self.proc, MSG_LSGAME)
            self._messages = lst.by_num() if lst else {}
        return self._messages.get(num)

    def confirm(self):
        """The confirmation box over this screen, or None."""
        return confirm_box(self.proc)


class Pager:
    """Moves the list between pages, checking the page after every click.

    Every move is confirmed against sfall's page offset, which is the whole
    difference from the version before it. That one read the occupancy flags to
    decide whether a click had worked -- and stepping between two empty pages
    changes no flag, so a page control that was working perfectly was reported
    as "could not change page" every single time. The flags say what is on the
    page; only the offset says which page it is.
    """

    # Four buttons, four strides. Ordered biggest first so `goto` spends its
    # clicks on the ten-page jumps before walking the remainder.
    STRIDES = ((10, PAGE_FORWARD_TEN), (-10, PAGE_BACK_TEN),
               (1, PAGE_NEXT), (-1, PAGE_PREV))

    # How long to let the engine redraw before calling a click lost.
    SETTLE = 1.0

    def __init__(self, proc, hwnd, finder, pages: int) -> None:
        self.proc = proc
        self.hwnd = hwnd
        self.finder = finder
        self.pages = max(1, pages)

    def _click(self, code) -> bool:
        from ..input.send import guarded_click
        from .pointer import MenuMouse, aim_to

        win = self.finder.sized(PANEL_WIDTH, PANEL_HEIGHT)
        if win is None:
            return False
        button = win.by_press(code)
        if button is None:
            return False
        ok, _where, _why = aim_to(self.proc, self.hwnd, *button.centre(win),
                                  reader=MenuMouse(self.proc))
        if not ok:
            return False
        # Let the arrival register before the button goes down. The engine
        # decides what the pointer is over on its own schedule, and a click sent
        # in the same breath as the last motion acts on where the pointer was --
        # the same settle the inventory drag needs, for the same reason.
        import time as _time
        _time.sleep(0.12)
        guarded_click(self.hwnd, "left", settle=0.3)
        return True

    def _await(self, screen, before):
        """Wait for the page to actually change, then report it.

        The page does not move in the same breath as the click -- reading it
        immediately gives the old one, which reads exactly like a click that
        did nothing.
        """
        import time as _time
        deadline = _time.time() + self.SETTLE
        while _time.time() < deadline:
            now = screen.page()
            if now != before:
                return now
            _time.sleep(0.03)
        return screen.page()

    def press(self, screen, code) -> Optional[int]:
        """Click one page control and return the page it landed on.

        None if it did not move. Retried once, because a click that goes astray
        is cheap to repeat and a page the player did not ask for is not.
        """
        before = screen.page()
        if before is None:
            return None
        for _ in range(2):
            if not self._click(code):
                return None
            after = self._await(screen, before)
            if after is not None and after != before:
                return after
        return None

    def step(self, screen, delta: int) -> Optional[int]:
        """Move by whole pages. Returns the new page, or None if it did not."""
        for stride, code in self.STRIDES:
            if stride == delta:
                return self.press(screen, code)
        return None

    def goto(self, screen, page: int, budget: int = 60) -> Optional[int]:
        """Drive the list to a specific page, the short way round.

        The control wraps, so the distance between two pages is whichever way
        round is shorter, and the ten-page jumps carry most of it. Bounded by
        `budget`: with a thousand pages a pathological target would otherwise
        click for a minute, and giving up honestly beats a screen that appears
        to have hung.
        """
        for _ in range(budget):
            here = screen.page()
            if here is None:
                return None
            if here == page:
                return here
            gap = (page - here) % self.pages
            if gap > self.pages // 2:
                gap -= self.pages          # shorter the other way round
            stride = 10 if gap >= 10 else -10 if gap <= -10 else (1 if gap > 0 else -1)
            if self.step(screen, stride) is None:
                return None
        return screen.page()


def describe(number: int, taken: bool, description: str = "") -> str:
    """What to say about one row.

    Both halves come from the engine now: `taken` from the occupancy flags,
    `description` from the header the screen is displaying. Nothing here is
    looked up on disk, so there is no slot number to compute wrongly and no way
    for the words to belong to a different save than the one on screen.

    A row the engine calls occupied but whose header will not parse is still a
    row that will be overwritten, so it is announced as holding a game without
    claiming to know which. Saying "empty" there would be the most expensive
    wrong sentence this mod could produce.
    """
    if not taken:
        return tr("slots.empty", "Slot {slot}, empty.", slot=number)
    if not description:
        return tr("slots.unnamed", "Slot {slot}, a saved game.", slot=number)
    return tr("slots.named", "Slot {slot}, {name}.", slot=number, name=description)
