"""The accessibility loop: work out which screen is showing, announce what changed.

Two rules hold this together.

**Game memory is the only source of truth.** Nothing here remembers what it
thinks is selected; every tick re-reads real state and compares snapshots. That
makes desync structurally impossible, which is what the original attempt (a
hardcoded menu list counting arrow keys) could never manage.

**Only the screen you are actually on may speak.** Each screen is identified by
a flag read from the game, not by guessing from content -- the selection screen
looks exactly like the character editor if you go by content, because it leaves
the editor's selection index and SPECIAL array populated. An unrecognised
screen stays silent: a confident wrong announcement is worse than none to
someone who cannot check it against the display.

Adding a screen means adding a watcher and registering it. No new plumbing.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Optional

import os

from .game import screens
from .game.aim import Aimer
from .game.chargen import CharGen
from .game.combat import CombatWatcher
from .game.displaywin import DisplayWindow
from .game import (actions, itemactions, itemmove, slotscreen,
                   timerwin, uiwindow)
from .game import inventory
from .game.inventory import InventoryWatcher
from .game.premade import PremadeScreen
from .game.saves import SaveWatcher
from .game.slotscreen import Pager, SlotScreen
from .game.scanner import Scanner
from .game import worldlog
from .game.worldlog import HexReading, WorldLog
from .input.send import (
    FocusLost,
    find_game_window,
    guarded_click,
    guarded_tap,
    is_foreground,
)
from .memory.process import FALLOUT_EXE_NAMES, Process, ProcessNotFound
from .speech.backends import Speaker, get_speaker

POLL_HZ = 20.0
RECONNECT_SECONDS = 2.0

# The two screen flags are not updated atomically. Mid-transition they can read
# as a screen the game is not on -- switching between the menu and selection
# briefly looks like the character editor -- which fired a spurious "Character
# creation" every time the player changed screen. So a new screen must hold
# steady for several consecutive polls before it is believed. At 20Hz this
# costs 200ms, far below the time any real screen change takes.
SCREEN_STABLE_TICKS = 4

# Long enough for the in-game script's cursor-restore window (8 script ticks) to
# finish after the last world read. Reading the world changes the cursor mode,
# and the engine applies the change a frame late, so it cannot be put back
# instantly -- see the note in gl_world.ssl's calibrate.
CURSOR_SETTLE = 0.35

MAIN_MENU_HELP = (
    "Main menu. Press N for new game, L to load a game, I for the intro, "
    "O for options, C for credits, E to exit."
)
SELECT_HELP = (
    "Left and right arrows cycle characters. Press T to take this one, "
    "M to modify it, C to create your own, or B to go back."
)
HELP_NOTHING = "Nothing selected."


class Announcer:
    """Speaks, and decides what may cut off what.

    The rule is the one screen readers have always used: **what you asked for
    interrupts, what the world did queues up.**

    Pressing a key is a question, and the answer to your latest question should
    arrive immediately -- stepping the scanner five times fast should read the
    fifth item, not the first four and then the fifth. But events are a stream,
    and cutting one off with the next loses it entirely. Announcing everything
    as urgent left only the last line of any burst alive: a miss was reliably
    erased by the action-point count that followed it a moment later, so combat
    read as "3." "6." with no idea what had happened in between.
    """

    def __init__(self, speaker: Speaker) -> None:
        self.speaker = speaker
        self._last = ""

    def say(self, text: str, interrupt: bool = False, force: bool = False) -> None:
        """Queue `text`. Set interrupt=True only for something the player asked for."""
        text = " ".join(text.split())
        if not text or (text == self._last and not force):
            return
        self._last = text
        self.speaker.speak(text, interrupt=interrupt)

    def answer(self, text: str) -> None:
        """A reply to a keypress: cuts off whatever is still being said."""
        self.say(text, interrupt=True, force=True)

    def reset(self) -> None:
        self._last = ""


class Watcher:
    """One screen. Subclasses announce entry and changes."""

    key = "?"

    def reset(self) -> None:
        pass

    def enter(self, ann: Announcer) -> None:
        pass

    def poll(self, ann: Announcer) -> None:
        pass

    def repeat(self, ann: Announcer) -> None:
        pass

    def describe(self, ann: Announcer) -> None:
        pass

    def summary(self, ann: Announcer) -> None:
        pass


class MainMenuWatcher(Watcher):
    key = screens.MAIN_MENU

    def enter(self, ann: Announcer) -> None:
        ann.answer(MAIN_MENU_HELP)

    def repeat(self, ann: Announcer) -> None:
        ann.answer(MAIN_MENU_HELP)

    summary = repeat
    describe = repeat


class SelectWatcher(Watcher):
    """Premade character selection."""

    key = screens.SELECT

    def __init__(self, premade: PremadeScreen) -> None:
        self.premade = premade
        self._prev: Optional[tuple] = None

    def reset(self) -> None:
        self._prev = None

    def _key(self, info) -> tuple:
        return (info.name, info.slot, tuple(info.special))

    def enter(self, ann: Announcer) -> None:
        info = self.premade.read()
        if not info:
            ann.answer("Character selection.")
            return
        # Leave _prev unset: the premade data can still be settling a frame
        # after the screen appears, and seeding it here made the first poll
        # see a "change" and repeat the whole announcement.
        self._prev = None
        ann.answer("Character selection. {} {}".format(info.full(self.premade.stat_names()), SELECT_HELP
            ),
        )

    def poll(self, ann: Announcer) -> None:
        info = self.premade.read()
        if not info:
            return
        key = self._key(info)
        if self._prev is None:
            self._prev = key  # first poll after arriving: sync, don't speak
            return
        if key != self._prev:
            self._prev = key
            ann.answer(info.full(self.premade.stat_names()))

    def repeat(self, ann: Announcer) -> None:
        info = self.premade.read()
        if info:
            ann.answer(info.announce())

    def describe(self, ann: Announcer) -> None:
        info = self.premade.read()
        if info:
            ann.answer(info.full(self.premade.stat_names()))

    summary = describe


class CharGenWatcher(Watcher):
    key = screens.CHARGEN

    def __init__(self, chargen: CharGen) -> None:
        self.chargen = chargen
        self._prev: Dict[str, object] = {}

    def reset(self) -> None:
        self._prev = {}

    def snapshot(self) -> Optional[Dict[str, object]]:
        if not self.chargen.is_plausible():
            return None
        return {
            "selection": self.chargen.selection(),
            "special": tuple(self.chargen.special()),
            "points": self.chargen.char_points(),
            "tags": tuple(self.chargen.tags()),
            "traits": tuple(self.chargen.traits()),
        }

    def enter(self, ann: Announcer) -> None:
        self._prev = self.snapshot() or {}
        item = self.chargen.current()
        if item:
            ann.answer("Character creation. " + item.announce())
        else:
            ann.answer("Character creation.")

    def poll(self, ann: Announcer) -> None:
        snap = self.snapshot()
        if snap is None:
            return
        prev, self._prev = self._prev, snap
        if not prev:
            return

        # Tagging or picking a trait: say what it now is, and what's left.
        if prev.get("tags") != snap.get("tags"):
            used = len(snap.get("tags") or ())
            item = self.chargen.current()
            ann.answer("{}. {} of 3 tags used.".format(item.announce() if item else "", used
                ),
            )
            return
        if prev.get("traits") != snap.get("traits"):
            used = len(snap.get("traits") or ())
            item = self.chargen.current()
            ann.answer("{}. {} of 2 traits chosen.".format(item.announce() if item else "", used
                ),
            )
            return

        # A value changed under the cursor.
        if prev.get("special") != snap.get("special") or prev.get("points") != snap.get("points"):
            item = self.chargen.current()
            points = snap.get("points")
            text = item.announce() if item else ""
            if points is not None:
                text += ", {} points left".format(points)
            ann.answer(text)
            return

        if prev.get("selection") != snap.get("selection"):
            item = self.chargen.current()
            if item:
                ann.answer(item.announce())

    def repeat(self, ann: Announcer) -> None:
        item = self.chargen.current()
        if item:
            ann.answer(item.announce())

    def describe(self, ann: Announcer) -> None:
        item = self.chargen.current()
        if item and item.description:
            ann.answer("{}. {}".format(item.label, item.description))
        elif item:
            ann.answer("{}. No description.".format(item.label))

    def summary(self, ann: Announcer) -> None:
        ann.answer(self.chargen.summary())


# Kept in step with gl_world.ssl's on_key by hand, which is the only way -- the
# script owns these keys and cannot tell us what it bound them to. This string
# had been wrong since the keys were remapped: it still promised that numpad 8
# returned the cursor to you and that numpad 5 re-read the hex, when 5 had
# become the snap and 8 had become north. It is spoken on every entry to the
# world and on every summary, so it was the most-heard sentence in the mod and
# also one of the few untrue ones.
WORLD_HELP = (
    "Numpad 7 9 4 6 1 3 move the look cursor around the six hex directions, "
    "8 and 2 go north and south. Numpad 5 brings the cursor back to you. "
    "Numpad plus clicks the hex it is on. Brackets scan for things nearby, "
    "and slash moves the cursor to what you found."
)


# Script lines that must NOT be spoken. Everything else the script emits is,
# by default, said out loud -- see pump(). These are the ones that fire per
# keypress or per object and would bury the readings that matter.
WORLD_QUIET = (
    "WORLD:key",      # every keypress the hook sees
    "WORLD:obj",      # per-object pid/fid diagnostics behind a hex reading
    "WORLD:dbgLOS",   # line-of-sight trace
    "WORLD:ready",    # session handshake
    "WORLD:snap",     # always followed by the hex reading that explains it
    "WORLD:btn",      # mouse-button telemetry; read from the log, not aloud
    "WORLD:dude",     # the player's tile changed -- "Moved n hexes" covers it
    "WORLD:under",    # which hex the pointer is over; diagnostic
    "WORLD:prepare",  # the click setting its own cursor; internal
    "WORLD:skillused",  # the engine spent the armed skill
    "WORLD:art",      # art identifiers for a hex; collected, not spoken
    "WORLD:artobj",   # art identifier for one object; likewise
    "WORLD:quicksave",  # which slot F6 writes to; groundwork, read from the log
    "WORLD:oudbg",    # what the engine put under the pointer, before filtering
    # Calibration output. Numpad 2 is no longer a key anyone presses on
    # purpose -- the aimer presses it several times per click to find out where
    # the pointer is, and narrating that would bury the click in numbers.
    "WORLD:calib",
    "WORLD:uicalib",  # the same question with a panel up; read, never spoken
    "WORLD:win",
    "WORLD:mode",
)


class WorldWatcher(Watcher):
    """In-game map exploration, driven by gl_world.ssl through debug.log."""

    key = screens.WORLD

    def __init__(self, log: WorldLog, saves: Optional[SaveWatcher] = None,
                 proc=None) -> None:
        self.log = log
        self.saves = saves
        # Only for reading the engine's window structures. Optional so the
        # tests can drive this watcher with nothing but log lines.
        self.proc = proc
        self.finder = uiwindow.WindowFinder(proc) if proc is not None else None
        # Set by App once the game window is known. Asking the engine what can
        # be done to an object means putting the pointer on it and holding the
        # button, so this watcher needs the aimer -- but only for that one
        # question, and the tests drive everything else with log lines alone.
        self.aimer = None
        self.hwnd: Optional[int] = None
        # An item-menu choice waiting to be carried out.
        self.pending_item_action: Optional[str] = None
        # What the pointer was actually put on when the menu was built.
        # The script names the object it opened the menu for, and the two
        # must agree -- the action array is never cleared, only overwritten,
        # so a stale read is a confident list about the wrong thing.
        self._menu_aimed_at: Optional[str] = None
        self._dumped = False
        self.combat = CombatWatcher()
        self.scanner = Scanner()
        self.inventory = InventoryWatcher()
        self._queue: list = []
        self._mode: Optional[int] = None

    def reset(self) -> None:
        self._queue = []
        self.inventory.reset()

    def pump(self) -> None:
        """Consume script output. Runs every tick, whatever screen is active,
        because this is also what tells us a game session is live at all.

        Every line the script bothers to emit must land somewhere audible. An
        earlier version handled only hex readings and game modes and silently
        discarded the rest, which made numpad 0 (force the movement cursor) and
        numpad 2 (calibrate) look completely dead: the script ran, did its job,
        logged it, and no one ever said so.
        """
        for line in self.log.poll():
            # (text, urgent) -- urgent means "you pressed a key and this is
            # the answer", so it may cut off whatever is still being said.
            if line.startswith("SCAN:obj"):
                # Furniture survey: pid, flags and type for every object the
                # scanner considered. Logged so the filter can be derived from
                # real data instead of guessed at. Never spoken.
                continue
            elif line.startswith("SCAN:"):
                self._queue.extend((t, True) for t in self.scanner.handle(line))
            elif line.startswith("INVEN:rect"):
                self._queue.extend((t, True) for t in self.inventory.handle(line))
                self._dump_buttons()
            elif line.startswith("INVEN:menu"):
                said = inventory.menu_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("INVEN:do"):
                # Enter in the item menu. The script cannot do these -- they
                # need the pointer -- so it writes the choice down and the loop
                # picks it up on the next tick, off this parsing path.
                self.pending_item_action = line
            elif line.startswith("INVEN:"):
                # Urgent throughout: every one of these is the answer to
                # something the player just did -- a key that stepped the list,
                # or the click that opened the window. Stepping five items fast
                # should read the fifth, not all five.
                self._queue.extend((t, True) for t in self.inventory.handle(line))
            elif line.startswith("COMBAT:"):
                # Combat speaks even when the mod thinks another screen is up.
                # Being attacked is not something to withhold because a screen
                # detector is unsure.
                self._queue.extend((t, False) for t in self.combat.handle(line))
            elif line.startswith("WORLD:status"):
                # Urgent: the player pressed a key and this is the answer.
                said = worldlog.status_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("WORLD:useitem"):
                said = worldlog.use_item_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("WORLD:menu"):
                said = worldlog.menu_line(line, self._menu_aimed_at)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("WORLD:useobj"):
                said = worldlog.use_obj_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("WORLD:hex") and self.log.last_hex:
                self._queue.append((self.log.last_hex, True))
            elif line.startswith("WORLD:gamemode"):
                if self._mode is not None and self.log.game_mode != self._mode:
                    self._queue.append((screens.mode_name(self.log.game_mode), False))
                    # Arriving at the save or load screen, the slot list IS the
                    # question. Naming the screen and stopping there leaves the
                    # player on a list of ten identical-sounding nothings.
                    if self.saves and screens.is_save_screen(self.log.game_mode):
                        self._queue.append((self.saves.summary(), False))
                self._mode = self.log.game_mode
            elif line.startswith("WORLD:map"):
                # Changed map. Worth saying out loud on its own: an exit grid
                # moves you somewhere entirely different, and the only other
                # cue is the music changing.
                self._queue.append(("New area.", False))
            elif line.startswith("WORLD:arrive"):
                # You walked and stopped. This is the confirmation that a click
                # did what it was meant to -- and its absence was why a working
                # click read as a broken one: the mod said nothing at all while
                # the player walked three hexes across the map.
                parts = line.rstrip("|").split()
                dist = parts[3] if len(parts) > 3 else "?"
                self._queue.append(
                    ("Moved {} hex{}.".format(dist, "" if dist == "1" else "es"),
                     False)
                )
            elif line.startswith("WORLD:cursorok"):
                # Numpad 0 pressed when the cursor was already in that mode.
                # Confirm briefly rather than repeating the full explanation,
                # which is what it sounds like when you press it twice.
                self._queue.append(("Already the movement cursor.", True))
            elif line.startswith("WORLD:cursormode"):
                # Always announce. This is the state that decides whether a
                # click walks or fires off a skill, and it can change without
                # the player doing anything they would connect to it -- a
                # Skilldex pick stays armed until something clears it.
                what = screens.cursor_name(self.log.cursor_mode)
                if what:
                    self._queue.append((what, False))
            elif not any(line.startswith(p) for p in WORLD_QUIET):
                # Everything else is spoken verbatim. Note the direction of the
                # default: unrecognised script output is AUDIBLE, and silence
                # has to be asked for explicitly by adding a prefix to
                # WORLD_QUIET. The opposite default is what made numpad 0 and
                # numpad 2 look dead, and it would have done it again here --
                # calibrate emits a "WORLD:mode" line that an enumerated
                # allow-list did not cover.
                self._queue.append((line[len("WORLD:"):], False))

    def _dump_buttons(self) -> None:
        """Print the item window's button table to the console, off the loop.

        Never spoken -- this is for whoever is building the next piece. The worn
        slots down the middle of the inventory window are the one set of targets
        the mod cannot yet point at, and their rectangles are sitting in here
        waiting to be read off a real session rather than guessed at.

        Run ONCE per session and on its own thread. Run inline on every window
        open, it froze the mod solid for ten to twelve seconds at a time -- and
        a screen reader that goes silent is worse than one that says the wrong
        thing, because silence is indistinguishable from the key never arriving.
        Doing it in the background also warms the finder's cache, so the first
        actual move does not pay the search cost either.
        """
        if self.finder is None or self.inventory.rect is None or self._dumped:
            return
        self._dumped = True
        thread = threading.Thread(target=self._dump_buttons_now,
                                  args=(self.inventory.rect,), daemon=True)
        thread.start()

    def _dump_buttons_now(self, rect) -> None:
        try:
            win = self.finder.at(*rect)
        except Exception as exc:
            print("[inven] cannot read the window: {}".format(exc), flush=True)
            return
        if win is None:
            print("[inven] no window matching {}".format(rect), flush=True)
            return
        print("[inven] window id {} at {} with {} buttons".format(
            win.id, self.inventory.rect, len(win.buttons)), flush=True)
        for b in win.buttons:
            key = " KEY {!r}".format(chr(b.press)) if b.key and 32 <= b.press < 127 else ""
            print("[inven]   press={:<6} ({:>3},{:>3}) {:>3}x{:<3}{}".format(
                b.press, b.left, b.top, b.width, b.height, key), flush=True)

    def enter(self, ann: Announcer) -> None:
        ann.answer("Exploring. " + WORLD_HELP)

    def poll(self, ann: Announcer) -> None:
        while self._queue:
            item, urgent = self._queue.pop(0)
            text = item.announce() if isinstance(item, HexReading) else str(item)
            # force=True throughout: the Announcer suppresses a line identical
            # to the one before, which is right for a 20Hz memory poll and
            # wrong for anything that actually happened. Numpad 5 re-reads the
            # hex you are already on and so produces the identical string every
            # time; two neighbouring empty hexes at the same distance do too.
            # Pressing a key and hearing nothing is indistinguishable from the
            # key not arriving.
            ann.say(text, interrupt=urgent, force=True)

    def repeat(self, ann: Announcer) -> None:
        # A panel over the map takes the question with it. "Repeat" while the
        # loot window is open means the item under the list cursor, not the hex
        # the player last looked at before they opened it.
        if self.inventory.open:
            ann.answer(self.inventory.repeat() or HELP_NOTHING)
            return
        if self.log.last_hex:
            ann.answer(self.log.last_hex.announce())
        else:
            ann.answer("No hex read yet. Press numpad 5.")

    def describe(self, ann: Announcer) -> None:
        """What the engine will let you do to the selected object.

        This used to be a second copy of `repeat`, which made numpad dot say
        exactly what numpad slash already said. It now asks the engine the
        question a sighted player answers by holding the button and reading the
        icons -- the eye, the hand, the backpack, the skilldex.

        Read-only, deliberately. It opens the menu, reads what is on it, and
        cancels; nothing is chosen. Knowing an item can be used on a door is
        what was missing, and choosing to use one is a separate decision that
        stays with the player.
        """
        if self.inventory.open:
            # Same key, same idea, different list: on the map this asks what can
            # be done to the thing you are pointing at, and in the inventory it
            # asks what can be done to the item you have selected.
            if self.hwnd is None:
                ann.answer(self.inventory.repeat() or HELP_NOTHING)
                return
            guarded_tap(self.hwnd, "m", settle=0.2)
            return
        if self.aimer is None or self.proc is None:
            ann.answer("Not attached to the game.")
            return
        if not screens.is_map_mode(self.log.game_mode):
            ann.answer("{}.".format(
                screens.mode_name(self.log.game_mode).capitalize()))
            return

        # Say so first. Pointing at the object takes a few seconds, and silence
        # after a keypress reads as the key never having arrived -- the
        # misreading this project keeps designing against.
        ann.answer("Checking.")
        last = self.log.last_hex
        wanted = None
        if last and last.contents:
            first = last.contents.split(",")[0].strip()
            if first and first not in ("empty", "you"):
                wanted = first
        self._menu_aimed_at, why = actions.open_menu(
            self.proc, self.aimer, self.hwnd, wanted=wanted)
        if self._menu_aimed_at is None:
            ann.answer("Cannot check that: {}.".format(why or "no answer"))
            return
        # Nothing more is said here. The script announces the menu, and one
        # voice saying it once beats two saying it differently.

    def summary(self, ann: Announcer) -> None:
        # "Where am I" is answered by whatever currently owns the screen. Each
        # of these is a different question wearing the same key.
        if self.inventory.open:
            ann.answer("{}. {}".format(
                self.inventory.container or screens.mode_name(self.log.game_mode),
                self.inventory.repeat() or HELP_NOTHING))
            return
        # In a fight, "where am I" means AP and whose turn it is. The hex-cursor
        # key reminder is not what you need while something is biting you.
        if self.combat.in_combat:
            ann.answer(self.combat.summary())
            return
        cursor = screens.cursor_name(self.log.cursor_mode)
        ann.answer("{}. {}{}".format(screens.mode_name(self.log.game_mode),
                (cursor + ". ") if cursor else "",
                WORLD_HELP,
            ),
        )


class SlotScreenWatcher(Watcher):
    """The save and load screens.

    A save you cannot load is a slower way of losing an evening, so this is the
    screen that makes the rest of saving worth anything. It needs no pointer to
    navigate -- the arrow keys already move the highlight -- and never did. It
    only ever needed a voice.

    The one thing it must not get wrong is which slot a row IS. Everything here
    is arranged around that: the engine says whether a row holds a game, the
    savegame folder supplies the words, the page is counted rather than guessed,
    and the count is checked against the folder whenever the two can disagree.
    """

    key = screens.SLOTS

    def __init__(self, screen, saves: SaveWatcher, pager) -> None:
        self.screen = screen
        self.saves = saves
        self.pager = pager
        self._selection: Optional[int] = None

    def reset(self) -> None:
        self._selection = None

    def _saved(self):
        return {s.number: s for s in self.saves.scan()}

    def _row(self, index: int) -> str:
        occupied = self.screen.occupied()
        taken = occupied[index] if index < len(occupied) else False
        page = self.screen.page()
        if page is None:
            # The row is real and readable; which slot on disk it is, is not.
            # Say the honest half rather than a number that might be ninety out.
            return "Row {}, {}.".format(index + 1,
                                        "a saved game" if taken else "empty")
        _character, description = self.screen.header(index)
        return slotscreen.describe(self.screen.slot_number(page, index),
                                   taken, description or "")

    def enter(self, ann: Announcer) -> None:
        # Name the screen at once, then do the slow part. Walking to the page
        # holding the saves needs an aim and a few clicks, and the sentence
        # covers it -- silence after a screen change reads as the mod dying.
        ann.answer("{}.".format(self._title()))
        self._selection = self.screen.selection()
        moved = self._seek_saves()
        ann.say(" ".join(x for x in (moved, self._page_line(), self._current())
                         if x), interrupt=False, force=True)

    def _seek_saves(self) -> str:
        """On the load screen, go where the games are.

        A thousand pages exist and a player's saves live on one or two of them,
        so opening Load on page eight and being told ten empty slots is a true
        answer to a question nobody asked. This only ever runs for LOADING: on
        the save screen the page decides which slot gets overwritten, and moving
        that without being asked is the one mistake here that destroys work.
        """
        if not self.screen.loading:
            return ""
        here = self.screen.page()
        if here is None:
            return ""
        wanted = slotscreen.pages_holding(self._saved())
        if not wanted or here in wanted:
            return ""
        landed = self.pager.goto(self.screen, wanted[0])
        if landed != wanted[0]:
            return ""
        return "Went to the saved games."

    def _title(self) -> str:
        return "Load game" if self.screen.loading else "Save game"

    def _panel(self):
        return self.screen.panel

    def _page_line(self) -> str:
        page = self.screen.page()
        if page is None:
            # Read, not counted -- so failing to read it is a real answer and
            # not an excuse to fall back on a tally that might be anywhere.
            return "Page not known."
        return "Page {}.".format(page + 1)

    def _current(self) -> str:
        index = self.screen.selection()
        if index is None:
            return "Cannot read the selection."
        return self._row(index)

    def poll(self, ann: Announcer) -> None:
        index = self.screen.selection()
        if index is None or index == self._selection:
            return
        self._selection = index
        ann.answer(self._row(index))

    def repeat(self, ann: Announcer) -> None:
        ann.answer(self._current())

    describe = repeat

    def summary(self, ann: Announcer) -> None:
        taken = sum(1 for x in self.screen.occupied() if x)
        pages = slotscreen.pages_holding(self._saved())
        where = ""
        if pages:
            where = "Saved games on {} {}.".format(
                "page" if len(pages) == 1 else "pages",
                ", ".join(str(p + 1) for p in pages))
        ann.answer(" ".join(x for x in (
            "{}.".format(self._title()),
            "{} {} on this page.".format(taken, "game" if taken == 1 else "games"),
            self._page_line(), where, self._current()) if x))

    def page(self, ann: Announcer, delta: int) -> None:
        landed = self.pager.step(self.screen, delta)
        if landed is None:
            ann.answer("Could not change page.")
            return
        self._selection = self.screen.selection()
        ann.answer(self._page_line() + " " + self._current())


class TimerWatcher(Watcher):
    """The explosive countdown.

    The number on this window cannot be read -- it is not in the executable's
    globals, not in sfall's, and the one heap candidate turned out to be a tally
    of clicks that rose on BOTH buttons. So it is not read. It is caused: on
    arrival the countdown is driven to its minimum by pressing down more times
    than the range is long, and from there every value is arithmetic the mod
    controls.

    That is the same construction the save screen's page and the inventory's
    scroll position use, and it is better than a reading would be: nothing to
    find, nothing to drift, and no address a patch could move.
    """

    key = screens.TIMER

    def __init__(self, timer) -> None:
        self.timer = timer

    def reset(self) -> None:
        self.timer.steps = None

    def enter(self, ann: Announcer) -> None:
        # Say what the screen is before the slow part. Winding the countdown
        # down to its floor is twenty clicks, and silence after a screen change
        # reads as the mod having died.
        ann.answer("Explosive timer. Setting it to the shortest.")
        if not self.timer.rewind():
            ann.answer("Explosive timer. Cannot reach its controls, so the "
                       "countdown is unknown. Escape cancels.")
            return
        ann.say("{}. Numpad plus and minus change it, Enter arms it, "
                "Escape cancels.".format(self._time()),
                interrupt=False, force=True)

    def _time(self) -> str:
        if self.timer.steps is None:
            return "Countdown unknown"
        return timerwin.say_time(self.timer.steps).capitalize()

    def repeat(self, ann: Announcer) -> None:
        ann.answer(self._time() + ".")

    describe = repeat
    summary = repeat

    def adjust(self, ann: Announcer, delta: int) -> None:
        before = self.timer.steps
        now = self.timer.step(delta)
        if now is None:
            ann.answer("Could not change the countdown, so it is now unknown. "
                       "Escape cancels.")
            return
        if now == before:
            ann.answer("{}. That is as {} as it goes.".format(
                self._time(), "short" if delta < 0 else "long"))
            return
        ann.answer(self._time() + ".")


class App:
    def __init__(self, speaker: Optional[Speaker] = None, require_focus: bool = True) -> None:
        self.ann = Announcer(speaker or get_speaker())
        self.require_focus = require_focus
        self.proc: Optional[Process] = None
        self.hwnd: Optional[int] = None
        self.watchers: Dict[str, Watcher] = {}
        self.aimer = None
        self.screen: str = screens.UNKNOWN
        self._pending_screen: str = screens.UNKNOWN
        self._pending_ticks: int = 0
        self._pending: list = []  # hotkeys awaiting the main loop
        self._session_epoch: int = 0
        # (item name, list length before, deadline) while a move is awaiting
        # the script's re-read. Nothing is claimed until that comes back.
        self._moved: Optional[tuple] = None
        # The item marked by the first press: (name, side, index, total).
        # Nothing has been sent to the game while this is set -- it is the mod's
        # own note of what the player chose, not a state the game is in.
        self._holding: Optional[tuple] = None

    def connect(self) -> bool:
        try:
            self.proc = Process.attach(FALLOUT_EXE_NAMES)
        except (ProcessNotFound, OSError):
            self.proc = None
            return False
        self.hwnd = find_game_window(self.proc.pid)
        # debug.log lives beside the game's executable -- it is the game that
        # writes it. Ask the process where it lives rather than working it out
        # from where THIS file happens to sit: that worked only while the mod
        # lived inside the game folder, and broke silently the moment it moved
        # into a repo, attaching happily and then hearing nothing at all.
        game_dir = self.proc.directory
        if not game_dir:
            print("[app] cannot determine the game's folder; is it running?",
                  flush=True)
            return False
        log_path = os.path.join(game_dir, "debug.log")
        if not os.path.exists(log_path):
            # Not fatal: the game creates it on launch and truncates it each
            # time, so an absent file usually just means nothing has been
            # written yet. Worth saying once, because a missing DebugMode=2 in
            # ddraw.ini produces exactly this and is otherwise invisible.
            print("[app] no debug.log in {} yet -- if nothing is ever announced "
                  "in game, check DebugMode=2 in ddraw.ini".format(game_dir),
                  flush=True)
        self.saves = SaveWatcher(game_dir)
        self.world = WorldWatcher(WorldLog(log_path), self.saves, self.proc)
        self.aimer = Aimer(self.hwnd, log_path) if self.hwnd else None
        # The world watcher needs these for the one question that
        # requires a pointer: what can be done to the selected object.
        self.world.aimer = self.aimer
        self.world.hwnd = self.hwnd
        # The game's own prose. Located lazily: the beacon it keys off is only
        # printed once a game is actually loaded.
        self.display = DisplayWindow(self.proc)
        self._session_epoch = 0
        self.finder = uiwindow.WindowFinder(self.proc)
        self.slots = SlotScreen(self.proc, self.hwnd)
        pager = Pager(self.proc, self.hwnd, self.finder,
                      slotscreen.page_count(game_dir))
        self.watchers = {
            screens.TIMER: TimerWatcher(
                timerwin.Timer(self.proc, self.hwnd, self.finder)),
            screens.SLOTS: SlotScreenWatcher(self.slots, self.saves, pager),
            screens.MAIN_MENU: MainMenuWatcher(),
            screens.SELECT: SelectWatcher(PremadeScreen(self.proc)),
            screens.CHARGEN: CharGenWatcher(CharGen(self.proc)),
            screens.WORLD: self.world,
        }
        self.screen = screens.UNKNOWN
        self.ann.reset()
        print("[app] attached to pid {} in {}".format(self.proc.pid, game_dir),
              flush=True)
        return True

    def _connected(self) -> bool:
        return self.proc is not None and self.proc.alive

    def _active(self) -> bool:
        if not self.require_focus:
            return True
        return self.hwnd is not None and is_foreground(self.hwnd)

    def current_watcher(self) -> Optional[Watcher]:
        return self.watchers.get(self.screen)

    def click(self, button: str = "left") -> None:
        """Press a mouse button on the hex the look cursor is on.

        The mod moves the pointer, and sets the cursor mode to match what you
        have chosen. It would be tidier to leave the mode alone and let you set
        it yourself, and that was tried -- it cannot be made to work. Reading
        the world changes the cursor as a side effect, aiming reads the world
        several times, and the restore that undoes the engine's meddling also
        undoes yours. Your right click would be quietly reverted before the
        button ever went down.

        So the mode is derived from what you actually expressed: a skill you
        armed from the number row, or an enemy on the hex you selected, or
        neither, which means walking. That is the same choice a sighted player
        makes by looking at what they are pointing at.

        What does NOT change is the refusal to click on a maybe. If the look
        hex holds something and the engine will not confirm the pointer is on
        it, nothing is sent -- a misplaced click walks you somewhere you did not
        choose, or swings at empty ground and spends the turn.
        """
        if self.hwnd is None:
            return
        try:
            mode = self.world.log.game_mode
            if button == "left" and screens.is_item_window(mode):
                self.move_item()
                return
            if button == "left" and not screens.is_map_mode(mode):
                # Something is over the map, so there is no hex to aim at and
                # the click goes to whatever panel is up. Say which -- an escape
                # menu left open swallows every click in the world, and with no
                # way to see it the game simply appears to have stopped
                # responding. That cost a whole debugging round.
                self.ann.answer("{}.".format(screens.mode_name(mode).capitalize()))
                guarded_click(self.hwnd, button)
                return

            if button == "left":
                if self.aimer is None:
                    return
                ok, reading, why = self.aimer.aim()
                if not ok:
                    self.ann.answer(
                        "Cannot aim at that hex: {}.".format(why or "unknown reason")
                    )
                    return

                # Was something meant to be there? The hex readout is the
                # player's own last look at it.
                last = self.world.log.last_hex
                if last and last.contents == "blocked":
                    # Nothing nameable on it and no way to walk into it, so
                    # there is nothing a click could mean. Say the thing the
                    # player was already told rather than making them decode
                    # "cannot point at that", which is what they got when
                    # "blocked" was added to the readout and this test, which
                    # only knew "empty" and "you", was not told about it.
                    self.ann.answer("That hex is blocked.")
                    return
                expects_object = bool(
                    last and last.contents and last.contents not in ("empty", "you")
                )
                # Set the cursor for what this click is about to do, AFTER
                # aiming, because every read during the aim disturbs it. If the
                # hex holds something, walk the pointer up its sprite until the
                # engine agrees it is pointing at it -- Fallout picks objects by
                # the figure drawn above the tile, so a click dead centre on a
                # door's hex hits the floor in front of it and does nothing.
                # Name what the hex readout already told the player, so the
                # search keeps going until the engine agrees it is pointing at
                # THAT rather than at whatever taller thing is drawn over it.
                # Without this, an item lying beside a door answered
                # "Impenetrable Door" to every probe, the cursor was set up for
                # the door, and the click walked onto the item instead of
                # picking it up.
                wanted = None
                if expects_object and last and last.contents:
                    first = last.contents.split(",")[0].strip()
                    if first and first not in ("empty", "you"):
                        wanted = first
                name, _at = self.aimer.prepare(expects_object, wanted=wanted)
                if expects_object and not name:
                    self.ann.answer("Cannot point at that.")
                    return
                if not expects_object and name is False:
                    # Every part of the hex is underneath something else's
                    # sprite, so a click would act on that instead of walking.
                    self.ann.answer("That hex is behind something.")
                    return
                time.sleep(CURSOR_SETTLE)
            guarded_click(self.hwnd, button)
        except FocusLost:
            self.ann.answer("Game is not focused.")
        except Exception as exc:  # never let a hotkey kill the loop
            print("[app] click: {}".format(exc), flush=True)

    def move_item(self) -> None:
        """Move the item the list cursor is on, and say what actually moved.

        The click key means the same thing here as it does on the map: act on
        the thing you selected. On a hex that is walk or attack; in one of these
        windows it is move the item across.

        What differs is how it is checked. A hex can be verified BEFORE the
        click, because the engine will say which hex the pointer is over; a row
        cannot, because there is no such question to ask about a UI. So this
        verifies afterwards instead, by counting both lists -- which is a
        stronger claim anyway. It reports what happened rather than what was
        intended.
        """
        inv = self.world.inventory
        if not inv.open or inv.rect is None or inv.side is None:
            self.ann.answer("Nothing selected.")
            return
        if self.world.finder is None:
            self.ann.answer("Not attached to the game.")
            return
        # First press marks the item. Nothing is sent to the game at all: the
        # move is a drag, and a drag begun on one keypress and finished on
        # another would leave the game holding an item across however long the
        # player takes to navigate -- a state they cannot see and the mod cannot
        # reliably detect. So the whole drag happens on the second press.
        if self._holding is None:
            if not inv.selected:
                self.ann.answer("No item selected.")
                return
            self._holding = (inv.selected, inv.side, inv.index, inv.total)
            self.ann.answer(
                "{}. Choose where to put it and press numpad plus again."
                .format(inv.selected)
            )
            return

        name, side, index, total = self._holding
        before = inv.counts
        # Say so before starting. The drag aims twice and each aim asks the
        # game where the pointer is a dozen times, so this takes a few seconds
        # -- and a few seconds of silence after a keypress reads exactly like
        # the key never arrived, which is the misreading this whole project
        # keeps having to design against.
        self.ann.answer("Moving {}.".format(name))
        try:
            itemmove.drag(self.world.finder, self.hwnd, inv.rect,
                          (side, index, total),
                          (inv.side, inv.index, inv.total),
                          log_path=self.world.log.path)
        except itemmove.CannotMove as exc:
            self._holding = None
            self.ann.answer(str(exc).capitalize() + ".")
            return
        except FocusLost:
            self._holding = None
            self.ann.answer("Game is not focused.")
            return

        # Ask the script for the TOTALS, not for the selected item. An item
        # equipped from the carried list changes the carried count and nothing
        # at all about the slot it went into, so re-reading the selection --
        # which is what this used to do -- reported every successful equip as a
        # failure. Its reply arrives through the log on a later tick.
        try:
            guarded_tap(self.hwnd, "numpad0", settle=0.25)
        except Exception:
            pass
        self._holding = None
        self._moved = (name, before, time.time() + 1.5)

    def _settle_move(self) -> None:
        """Say what the click actually did, once the script has re-read the list.

        Deliberately says nothing until the count comes back. Announcing "moved
        the plastic explosives" straight after sending a click would be
        reporting an intention as a fact, and an item that did not move is
        exactly the case a player cannot see for themselves.

        A count that did not change does NOT mean nothing happened. Fallout's
        inventory picks an item up onto the cursor when it is clicked without
        the move modifier, and the list length is the same either way -- so the
        honest reading of "no change" is that the item is now being carried by
        the pointer, waiting to be put down. Saying "did not move" there would
        be worse than useless: it would leave the player holding something they
        had been told they were not.
        """
        if not self._moved:
            return
        name, before, deadline = self._moved
        inv = self.world.inventory
        # Compare the whole reading, not just the count. Dropping something into
        # an equipment slot changes no list length anywhere -- the slot's
        # contents change -- so a count test called every successful equip a
        # failure and told the player they were still holding it.
        if inv.counts is not None and inv.counts != before:
            self._moved = None
            self.ann.answer("Moved {}.".format(name))
        elif time.time() > deadline:
            self._moved = None
            # The drag ran and the reading did not change. Say so plainly. The
            # earlier version guessed "you must be holding it" here, which was
            # a story invented to explain silence -- and it was wrong, because
            # what silence actually meant was that the clicks did nothing.
            self.ann.answer("{} did not move.".format(name))

    def action(self, what: str) -> None:
        """Queue a hotkey. Called from the keyboard listener's thread.

        Nothing is done here. Hotkeys arrive on pynput's thread while the main
        loop is reading the script's log, and aiming a click reads that same log
        and sends its own keystrokes -- two threads doing that at once
        interleave keys and steal each other's lines. Queue it, run it in the
        loop.

        This is the mod's entire entry point from the keyboard. It went missing
        for several rounds during a refactor, and the failure was completely
        silent: the listener called a method that no longer existed, the
        AttributeError was caught as "never let a hotkey kill the listener",
        and the message went to a console the player cannot see. Every key
        press did nothing at all, without a sound.
        """
        self._pending.append((what, time.time()))

    def _run_item_action(self) -> None:
        """Carry out an item-menu choice, off the log-parsing path.

        Done here rather than where the line is read because these actions take
        seconds and drive the pointer, and doing that in the middle of parsing a
        batch of log lines would stall the rest of them behind it.
        """
        line = self.world.pending_item_action if self.world else None
        if not line:
            return
        self.world.pending_item_action = None
        m = inventory._DO.match(line)
        if not m:
            return
        what, name, side, index, total, active = (
            m.group(1).strip(), m.group(2).strip(), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), m.group(6) == "1")
        if self.proc is None or self.hwnd is None:
            self.ann.answer("Not attached to the game.")
            return

        self.ann.answer("{} {}.".format(what.capitalize(), name))
        if what.startswith("use"):
            done, why = itemactions.use(self.proc, self.hwnd, side, index, active)
        elif what.startswith("drop"):
            done, why = itemactions.drop(self.world.finder, self.proc,
                                         self.hwnd, side, index, total)
        else:
            done, why = False, "The mod has no way to do that yet."
        if not done:
            self.ann.answer(why or "That did not work.")

    def _run_pending(self) -> None:
        while self._pending:
            what, queued_at = self._pending.pop(0)
            # Drop anything stale. If the game lost focus the loop stops
            # ticking, and a click that fires when focus comes back lands in a
            # context the player has long since moved on from.
            if time.time() - queued_at > 1.0:
                continue
            self._do_action(what)

    def _do_action(self, what: str) -> None:
        if what in ("click", "rclick") and self.screen == screens.TIMER:
            # Nothing to point at here either: the two step buttons are the
            # only controls, and Enter and Escape are already the game's.
            watcher = self.current_watcher()
            if watcher:
                watcher.adjust(self.ann, 1 if what == "click" else -1)
            return
        if what in ("click", "rclick") and self.screen == screens.SLOTS:
            # There is nothing to click at on this screen -- the arrow keys
            # already move the highlight -- so the two mouse-button keys are
            # given to the one thing that does need pointing at: the pages.
            watcher = self.current_watcher()
            if watcher:
                watcher.page(self.ann, 1 if what == "click" else -1)
            return
        if what in ("click", "rclick"):
            self.click("left" if what == "click" else "right")
            return
        watcher = self.current_watcher()
        if watcher is None:
            self.ann.answer("No screen recognised.")
            return
        getattr(watcher, what, lambda _a: None)(self.ann)

    def pump_display(self) -> None:
        """Speak whatever the game has written along the bottom of the screen.

        These are the engine's own sentences, so they are preferred over
        anything the mod could assemble: already written, already translated,
        and describing exactly what a sighted player was told.
        """
        # A new game load reallocates the message ring, so the anchor from the
        # last one points at freed heap. The script announces each load, which
        # is the signal to go and find the buffer again. Until this existed,
        # loading a save silenced the game's own words for good -- and because
        # locating also switches the mod's own combat narration off, nothing
        # narrated a blow at all.
        if self.world.log.ready_count != self._session_epoch:
            first = self._session_epoch == 0
            self._session_epoch = self.world.log.ready_count
            self.display.reset()
            self.world.combat.narrate_damage = True
            # A session beginning again, when one has already begun, is a game
            # being loaded. F7 is the whole reason this matters: quick load
            # needs no screen and no pointer, so it already worked -- it just
            # made no sound, and a load that worked was indistinguishable from
            # a key that never arrived.
            if not first:
                self.ann.answer("Game loaded.")

        if not self.display.located:
            # Only worth looking once a session is live; before a game loads
            # the beacon has not been printed and the scan is wasted work.
            if not self.world.log.session_live:
                return
            if not self.display.locate():
                return
            print("[app] display window at 0x{:08X}".format(self.display.anchor),
                  flush=True)
            # The engine narrates its own blows now, so stop assembling ours.
            self.world.combat.narrate_damage = False
        for line in self.display.poll():
            self.ann.say(line, force=True)

    def tick(self) -> None:
        if not self.proc:
            return
        # Always pump the script log first: it is the only thing that can tell
        # us a game session is live, and memory alone mistakes the map for the
        # premade-character screen.
        self.world.pump()
        self._settle_move()
        self.pump_display()
        # A save is always worth hearing, whatever screen the mod thinks is up.
        # It is also the one announcement that must never be dropped: acting on
        # a save that did not happen is how an evening's play is lost.
        for line in self.saves.poll():
            self.ann.say(line, force=True)
        # The script's mode says whether this is Save or Load; before a game
        # loads there is no script, and the only way here is Load.
        self.slots.mode = self.world.log.game_mode if self.world.log.session_live else None
        detected = screens.detect(self.proc,
                                  in_game=self.world.log.session_live,
                                  mode=self.world.log.game_mode)

        if detected != self.screen:
            # Debounce: only believe a new screen once it has held steady.
            if detected == self._pending_screen:
                self._pending_ticks += 1
            else:
                self._pending_screen = detected
                self._pending_ticks = 1
            if self._pending_ticks < SCREEN_STABLE_TICKS:
                return
            self.screen = detected
            self._pending_ticks = 0
            print("[app] screen: {}".format(detected), flush=True)
            watcher = self.current_watcher()
            if watcher:
                watcher.reset()
                watcher.enter(self.ann)
            return

        self._pending_screen = detected
        self._pending_ticks = 0
        watcher = self.current_watcher()
        if watcher:
            watcher.poll(self.ann)
        # Hotkeys last: an aimed click sends its own keystrokes and reads the
        # same log, so it must not run half way through a screen transition.
        self._run_pending()
        self._run_item_action()

    def run(self, on_tick: Optional[Callable[[], None]] = None) -> None:
        period = 1.0 / POLL_HZ
        last_try = 0.0
        print("[app] waiting for Fallout 2 ...", flush=True)
        while True:
            if not self._connected():
                now = time.time()
                if now - last_try >= RECONNECT_SECONDS:
                    last_try = now
                    if self.connect():
                        self.ann.say("Fallout 2 accessibility connected.", force=True)
                time.sleep(RECONNECT_SECONDS)
                continue
            try:
                if self._active():
                    self.tick()
            except OSError:
                pass
            if on_tick:
                on_tick()
            time.sleep(period)
