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
from typing import Callable, Dict, Optional, Tuple

import os

from .game import screens
from .game.aim import Aimer
from .game.chargen import CharGen, MSG_EDITOR, POINTER_SECTIONS
from .game import perkpick
from . import words

# editor.msg's own title for the perk window: "PICK A PERK".
MSG_PICK_A_PERK = 152
from .game.combat import CombatWatcher
from . import controls
from .controls import Binding
from .i18n import tr, tr_text
from .game import calledshot, pausemenu, prefs
from .game.displaywin import DisplayWindow
from .game import (actions, barter, charsheet, dialogue, itemactions, itemmove,
                   pipboy, quantity, slotscreen, timerwin, uiwindow)
from .game import floattext, history, inventory
from .game.inventory import InventoryWatcher
from .game.premade import PremadeScreen
from .game.saves import SaveWatcher
from .game.slotscreen import Pager, SlotScreen
from .game.scanner import Scanner
from .game import worldlog
from .game import worldcursor, worldmap, worldtravel
from .game.worldlog import HexReading, WorldLog
from .input.send import (
    FocusLost,
    find_game_window,
    fullscreen_complaint,
    guarded_click,
    guarded_tap,
    is_foreground,
)
from . import sound
from .memory import resolve
from .memory.process import FALLOUT_EXE_NAMES, Process, ProcessNotFound
from .speech.backends import Speaker, get_speaker

POLL_HZ = 20.0
# A tick this slow is logged with where its time went. Queued keys are thrown
# away after a second, so half that is already worth knowing about.
SLOW_TICK_SECONDS = 0.5
RECONNECT_SECONDS = 2.0

# How long a game process may run with no window before the mod connects to it
# anyway and says why it cannot point. See `connect`.
WINDOW_WAIT_SECONDS = 60.0

# The two screen flags are not updated atomically. Mid-transition they can read
# as a screen the game is not on -- switching between the menu and selection
# briefly looks like the character editor -- which fired a spurious "Character
# creation" every time the player changed screen. So a new screen must hold
# steady for several consecutive polls before it is believed. At 20Hz this
# costs 200ms, far below the time any real screen change takes.
SCREEN_STABLE_TICKS = 4

# Leaving the character editor and arriving at character selection are the same
# three flags, and only time tells them apart.
#
# Pressing DONE closes the editor's window and clears the menu flag, which is
# character selection exactly as the flags describe it -- and it stays that way
# for the whole of the map load that follows. So finishing a character announced
# the premade screen in full, stat block, trait list, "press T to take this
# one", at a player who was on their way into the game, and the announcement was
# still going when the map arrived and cut it off. It read as the mod being
# confused about where it was, which is the one impression this project can
# least afford, and it was worse than that: it delayed the only announcement
# that mattered.
#
# Cancelling out of the editor reaches the same flags and IS the selection
# screen, so the reading cannot simply be refused. What separates the two is
# what happens next: DONE is followed within a second or two by a live game
# session, and CANCEL is followed by nothing at all. So this one transition
# waits and sees. Three seconds of quiet after backing out of the editor, and
# then the screen is read; against announcing the wrong screen entirely, that is
# a cheap trade -- and it costs nothing on the path players take far more often.
SELECT_AFTER_EDITOR_TICKS = 60

# Main menu straight to the character editor, which the game never does: New
# Game always passes through character selection first. But opening Load from
# the main menu briefly reads as the editor -- the editor's window handle goes
# live before the load screen's window has its buttons -- and four polls was
# not always long enough for the load screen to claim the reading, so "Load"
# was sometimes announced as "Character creation" (owner, 0.2.36). Two seconds
# outlasts the load screen's arrival and still lets a real editor through.
EDITOR_FROM_MENU_TICKS = 40

# The same idea, for a conversation. The engine writes the NPC's line and
# rebuilds the list of replies on different frames, so a reading taken between
# the two pairs this line with the previous one's answers. That is not a
# garbled announcement, which a player would notice -- it is a fluent and
# entirely wrong one, which they could not. Two polls at 20Hz costs 100ms.
DIALOGUE_STABLE_TICKS = 2

# Long enough for the in-game script's cursor-restore window (8 script ticks) to
# finish after the last world read. Reading the world changes the cursor mode,
# and the engine applies the change a frame late, so it cannot be put back
# instantly -- see the note in gl_world.ssl's calibrate.
CURSOR_SETTLE = 0.35

def main_menu_help() -> str:
    return tr("mainmenu.help", "Main menu. Press N for new game, L to load a "
              "game, I for the intro, O for options, C for credits, E to exit.")


def select_help() -> str:
    return tr("select.help", "Left and right arrows cycle characters. Press T "
              "to take this one, M to modify it, C to create your own, or B to "
              "go back.")


def nothing_selected() -> str:
    return tr("inventory.nothing_selected", "Nothing selected.")

# How soon after Control and X a question box is taken to be the one it opened.
QUIT_KEY_SECONDS = 3.0

# How long a second press of O has to confirm an offer the mod asked about.
OFFER_CONFIRM_SECONDS = 6.0


def _unsafe_scripting(game_dir) -> bool:
    """Is AllowUnsafeScripting on in the game's ddraw.ini?

    Read here as well as from the script's WORLD:unsafe line, which is only
    printed when a game loads -- start the mod after that and the line has
    already gone by.
    """
    import os
    import re as _re

    try:
        with open(os.path.join(game_dir, "ddraw.ini"), encoding="latin-1") as fh:
            text = fh.read()
    except (OSError, TypeError):
        return False
    m = _re.search(r"^\s*AllowUnsafeScripting\s*=\s*(\d+)", text, _re.M)
    return bool(m and int(m.group(1)) > 0)


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
        # Everything spoken goes in the log too. Without it, "that was never
        # read" could not be told apart from "that was read and cut off" or
        # "that was read and missed" -- which is how the character sheet's
        # points went undiagnosed with every other line it needed in hand.
        print("[say{}] {}".format("!" if interrupt else "", text), flush=True)
        self.speaker.speak(text, interrupt=interrupt)

    def answer(self, text: str) -> None:
        """A reply to a keypress: cuts off whatever is still being said."""
        self.say(text, interrupt=True, force=True)

    def reset(self) -> None:
        self._last = ""


class Watcher:
    """One screen. Subclasses announce entry and changes.

    `KEYS` is the screen's keyboard, in the grammar of controls.py: it is what
    the keys do, what F1 says, and what tests/test_controls.py checks.
    """

    key = "?"
    # Said by F1 before the keys: what this screen is called.
    TITLE = ""
    KEYS: tuple = ()

    def help_keys(self) -> tuple:
        """The keys F1 reads. A screen whose keys depend on what is open on it
        answers for the moment; most just have the one list."""
        return self.KEYS

    def help_title(self) -> str:
        return tr_text("screen", self.TITLE) if self.TITLE else ""

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
    TITLE = "Main menu"
    KEYS = (
        Binding("N", "new game", controls.GAME),
        Binding("L", "load a game", controls.GAME),
        Binding("O", "options", controls.GAME),
        Binding("E or Escape", "exit", controls.GAME),
    )

    def enter(self, ann: Announcer) -> None:
        ann.answer(main_menu_help())

    def repeat(self, ann: Announcer) -> None:
        ann.answer(main_menu_help())

    summary = repeat
    describe = repeat


class SelectWatcher(Watcher):
    """Premade character selection."""

    key = screens.SELECT
    TITLE = "Character selection"
    KEYS = (
        Binding("Left and Right", "the three ready-made characters", controls.GAME),
        Binding("T", "take this one", controls.GAME),
        Binding("M", "change this one", controls.GAME),
        Binding("C", "make your own", controls.GAME),
        Binding("B or Escape", "back", controls.GAME),
    )

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
            ann.answer(tr("select.title", "Character selection."))
            return
        # Leave _prev unset: the premade data can still be settling a frame
        # after the screen appears, and seeding it here made the first poll
        # see a "change" and repeat the whole announcement.
        self._prev = None
        ann.answer("{} {} {}".format(tr("select.title", "Character selection."),
                                     info.full(self.premade.stat_names()),
                                     select_help()))

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


def _wait_for_shift_up(limit: float = 1.0) -> None:
    """Wait for Shift to be let go, so a Tab sent now is not a Shift and Tab."""
    import ctypes

    user32 = ctypes.WinDLL("user32")
    deadline = time.time() + limit
    while time.time() < deadline and user32.GetAsyncKeyState(0x10) & 0x8000:
        time.sleep(0.02)


class CharGenWatcher(Watcher):
    key = screens.CHARGEN
    TITLE = "Character screen"
    KEYS = (
        Binding("Tab", "the next section", controls.GAME),
        Binding("Shift and Tab", "the previous section", controls.GAME),
        Binding("Up and Down", "move in the section", controls.GAME),
        Binding("Left and Right, or plus and minus", "lower or raise it",
                controls.GAME),
        Binding("D or Enter", "done", controls.GAME),
        Binding("C or Escape", "cancel", controls.GAME),
    )

    def __init__(self, chargen: CharGen, log=None) -> None:
        self.chargen = chargen
        # The in-game character screen is the same panel as the creation editor,
        # so the same watcher narrates it -- but its numbers come from a live
        # character rather than from the editor's working copy. Handing the
        # reader the script's report is what makes it say 6 where the sheet says
        # 6, instead of the 8 sitting in the base stat table.
        self.log = log
        self._prev: Dict[str, object] = {}
        # A row moved onto whose words come from the engine's label pointers,
        # waiting for them to settle before it is read. See `poll`.
        self._settling = False
        # The last plus or minus already logged. See `poll`.
        self._push_seen = None
        # The order Tab walks the sections in, learned the first time Shift
        # and Tab is pressed on a visit. See `back_section`.
        self._tab_cycle: Optional[list] = None

    def reset(self) -> None:
        self._prev = {}
        self._settling = False
        self._tab_cycle = None

    # How long one Tab may take to show in the selection, and the most a loop
    # of sections can hold before something is wrong.
    TAB_SETTLE = 0.4
    TAB_LIMIT = 12

    def _place(self, selection=None):
        """Where the editor is, as Tab sees it: the section, and inside the
        folder box which folder -- Tab steps through those too."""
        from .game.chargen import _SECTION_OF

        if selection is None:
            selection = self.chargen.selection()
        section = _SECTION_OF.get(selection, (None,))[0]
        if section == "folder":
            return (section, self.chargen.folder())
        return (section, None)

    def back_section(self, ann: Announcer, hwnd) -> None:
        """Shift and Tab: the previous section, which the editor does not have.

        The editor answers Tab and nothing else, and no script runs on this
        screen to add a key -- so the previous section is reached forwards: the
        order Tab walks is learned once per visit by going round the loop, then
        Tab is pressed as many times as it takes to land one short of where the
        player was. Only where it lands is said. The order is learned rather
        than written down because it differs between making a character and
        the sheet of a live one, and with sfall's race and style rows.
        """
        if hwnd is None or self.chargen.dialog():
            self.quiet_until = 0.0
            return
        from .input.send import FocusLost, guarded_tap

        # **The game reads Shift and Tab as a Tab**, so by now it has already
        # moved one section on. Where the player was is the section before
        # this one, and where they want to be is the one before that --
        # measured: counting from the place the key left them landed one
        # section short, every time.
        _wait_for_shift_up()
        time.sleep(0.15)

        def tab_and_read(was):
            guarded_tap(hwnd, "tab", settle=0.02)
            deadline = time.time() + self.TAB_SETTLE
            now = self._place()
            while now == was and time.time() < deadline:
                time.sleep(0.03)
                now = self._place()
            return now

        try:
            here = self._place()
            if not self._tab_cycle or here not in self._tab_cycle:
                order = [here]
                for _ in range(self.TAB_LIMIT):
                    here = tab_and_read(here)
                    if here == order[0]:
                        break
                    order.append(here)
                else:
                    return          # never came round: not a loop to trust
                self._tab_cycle = order
            cycle = self._tab_cycle
            if here not in cycle:
                return
            target = cycle[(cycle.index(here) - 2) % len(cycle)]
            for _ in range(len(cycle)):
                if here == target:
                    break
                here = tab_and_read(here)
        except FocusLost:
            self.quiet_until = 0.0
            ann.answer(tr("app.game_is_not_focused", "Game is not focused."))
            return
        # Said once, from where it landed, and not again by the next poll. The
        # folder rows' words come a frame after the row; give them that frame.
        time.sleep(0.15)
        self.quiet_until = 0.0
        self._prev = self.snapshot() or {}
        item = self.chargen.current()
        if item:
            ann.answer(item.announce())

    def _sync(self) -> None:
        """Hand the reader the engine's report, if there is one.

        Called from every entry point rather than just the poll, because
        "repeat that" and "describe that" read the same item and must not
        answer with the creation-time formulas while the poll answers with the
        live ones.
        """
        self.chargen.sheet = self.log.sheet if self.log is not None else None

    def snapshot(self) -> Optional[Dict[str, object]]:
        self._sync()
        if not self.chargen.is_plausible():
            return None
        return {
            "selection": self.chargen.selection(),
            "special": tuple(self.chargen.special()),
            "points": self.chargen.char_points(),
            "tags": tuple(self.chargen.tags()),
            "traits": tuple(self.chargen.traits()),
            # The name buffer was readable all along and simply never watched.
            # It COMMITS rather than tracks: typing into the dialog does not
            # touch it, and it changes in one step when the name is accepted.
            # Measured -- typing "catnip" into the field left this reading
            # "None", and a scan of the whole module found the text nowhere, so
            # the in-progress string is a stack local and not something any
            # address can follow. Character echo while typing therefore belongs
            # to the screen reader, which already offers it; what belongs here
            # is saying what the name ended up as.
            "name": self.chargen.name(),
            # Name, age and sex are not rows in the editor's list -- they are
            # three small dialogs behind the N, A and S keys, which is why no
            # selection index was ever found for them.
            "dialog": self.chargen.dialog(),
            "age": self.chargen.age(),
            "sex": self.chargen.sex(),
            # sfall's race and style. Left and Right on those rows are sfall's
            # keys, and they change nothing the engine watches.
            "appearance": self.chargen.appearance_choice(),
            # What the current row actually says.
            #
            # The selection index is not always the thing that moves. The Kills
            # and Karma lists scroll a row at a time while the index sits still,
            # so a watcher keyed on the index alone heard nothing and said
            # nothing -- three rows of a list reported as one, and the others
            # silent even of a number.
            "label": self._row_text(),
            # Which folder the box shows. Tab inside the box switches folders
            # and leaves the row where it is, so this is movement too.
            "folder": self.chargen.folder(),
            "card": self.chargen.card(),
            # Spending skill points changes these and nothing else.
            "skills": tuple(self.chargen.skills()),
            "unspent": self._unspent(),
            # The windows open, to notice the engine's refusal box arriving.
            "windows": self._windows(),
            # The perk being looked at, while the Pick a Perk window is up.
            "perk": self._perk(),
        }

    def _perk(self):
        proc = getattr(self.chargen, "proc", None)
        if proc is None:
            return None
        try:
            return perkpick.current(proc)
        except Exception:
            return None

    def _windows(self) -> tuple:
        proc = getattr(self.chargen, "proc", None)
        if proc is None:
            return ()
        try:
            return tuple(uiwindow.live_window_addresses(proc))
        except Exception:
            return ()

    def _unspent(self) -> Optional[int]:
        sheet = self.chargen.sheet
        return sheet.unspent if sheet is not None and sheet.ready else None

    def _row_text(self) -> Optional[str]:
        item = self.chargen.current()
        return item.announce() if item else None

    def enter(self, ann: Announcer) -> None:
        self._sync()
        self.chargen.reset()
        self._settling = False
        self._prev = self.snapshot() or {}
        # The same panel serves two purposes and they are not the same screen.
        # Announcing "character creation" over a character who has been played
        # for an hour is simply wrong, and it is the first thing said on the way
        # in, so it is the first thing that sounds broken.
        title = (tr("chargen.sheet_title", "Character sheet.")
                 if self.chargen.sheet is not None and self.chargen.sheet.ready
                 else tr("chargen.title", "Character creation."))
        item = self.chargen.current()
        ann.answer("{} {}".format(title, item.announce()) if item else title)

    def poll(self, ann: Announcer) -> None:
        snap = self.snapshot()
        if snap is None:
            return
        prev, self._prev = self._prev, snap
        if not prev:
            return
        # Shift and Tab is on its way: the game has taken it as a Tab and
        # moved, and the step back is about to be made. Say neither.
        if time.time() < getattr(self, "quiet_until", 0.0):
            return

        sheet = self.chargen.sheet
        push = getattr(sheet, "adjust", None) if sheet is not None else None
        if push is not None and push != self._push_seen:
            # One line per plus or minus, logged before anything below can
            # return early: what the sheet saw change after it. Spending points
            # went silent and nothing recorded why.
            self._push_seen = push
            opened = set(snap.get("windows") or ()) - set(prev.get("windows") or ())
            print("[chargen] push {} on row {}: windows opened {}, skills "
                  "changed {}, unspent {} -> {}, dialog {}, perk {}, "
                  "current {}".format(
                      push[0], push[1], len(opened),
                      prev.get("skills") != snap.get("skills"),
                      prev.get("unspent"), snap.get("unspent"),
                      snap.get("dialog"), snap.get("perk"),
                      self.chargen.current()), flush=True)

        # One of the three dialogs opening. Said before anything else, because
        # while one is up it is the entire screen as far as the player is
        # concerned -- and it is the announcement that tells them the key they
        # pressed did something at all.
        if prev.get("dialog") != snap.get("dialog"):
            opened = snap.get("dialog")
            if opened:
                ann.answer(self._dialog_opened(opened))
                return
            # Closing says nothing on its own. Escape reverts the value, and the
            # revert is announced below as the change it is, which tells the
            # player what they are back to rather than merely that they left.

        # Typing in the name field. Said before anything else remaining, because
        # while it is being typed nothing else on this screen is changing.
        if prev.get("name") != snap.get("name"):
            ann.answer(self._name_change(prev.get("name"), snap.get("name")))
            return

        if prev.get("age") != snap.get("age"):
            ann.answer("{}.".format(snap.get("age")))
            return

        if prev.get("sex") != snap.get("sex"):
            ann.answer("{}.".format(self.chargen.sex_name()
                                    or tr("chargen.sex_changed", "sex changed")))
            return

        # A new race or style. Said only from its own rows: changing sex
        # swaps the pack too, and that was answered just above.
        if prev.get("appearance") != snap.get("appearance"):
            item = self.chargen.current()
            if item is not None and item.section == "appearance":
                ann.answer(item.announce())
                return

        # Tagging or picking a trait: say what it now is, and what's left.
        if prev.get("tags") != snap.get("tags"):
            used = len(snap.get("tags") or ())
            item = self.chargen.current()
            ann.answer("{}. {}.".format(item.announce() if item else "",
                                        tr("chargen.tags_used", "{used} of {most} tags used",
                                           used=used, most=3)))
            return
        if prev.get("traits") != snap.get("traits"):
            used = len(snap.get("traits") or ())
            item = self.chargen.current()
            ann.answer("{}. {}".format(item.announce() if item else "",
                                       tr("chargen.traits_chosen",
                                          "{used} of {most} traits chosen.",
                                          used=used, most=2)))
            return

        # A value changed under the cursor.
        if prev.get("special") != snap.get("special") or prev.get("points") != snap.get("points"):
            item = self.chargen.current()
            points = snap.get("points")
            text = item.announce() if item else ""
            if points is not None:
                text += ", " + tr("chargen.special_left", "{points} points left",
                                  points=points)
            ann.answer(text)
            return

        # **The Pick a Perk window.** It opens over the sheet the first time
        # the sheet is opened after a level that grants one, and while it is up
        # it is the whole screen: the arrows walk its list, Enter takes the
        # perk and Escape leaves it for later. Those are its own keys.
        perk, was = snap.get("perk"), prev.get("perk")
        if perk != was:
            if perk is not None and was is None:
                title = (self.chargen._msg(MSG_EDITOR).get(MSG_PICK_A_PERK)
                         or tr("perks.title", "Pick a perk")).capitalize()
                ann.answer(tr("perks.opened", "{title}. {count} to choose from. "
                              "{first} Enter takes it, Escape leaves it for later.",
                              title=title, count=perk.total, first=perk.announce()))
            elif perk is not None:
                ann.answer(perk.announce())
            return
        if perk is not None:
            return

        # The engine refusing a plus or a minus. It opens a box and waits for
        # Escape, and the box was silent -- so the push was heard as nothing
        # happening, and the screen as stuck. A window that was not there a
        # moment ago, straight after a push, is that box.
        sheet = self.chargen.sheet
        push = getattr(sheet, "adjust", None) if sheet is not None else None
        opened = set(snap.get("windows") or ()) - set(prev.get("windows") or ())
        if push is not None and opened and time.time() - push[2] < 2.0:
            sheet.adjust = None
            said = self.chargen.adjust_refused(push[0])
            if said:
                ann.answer("{} {}".format(said, tr("chargen.escape_closes",
                                                   "Escape to close.")))
                return

        # Skill points spent or taken back. Said with what is left, because
        # "how many more can I put in" is the question being asked while doing
        # it -- the same reason SPECIAL says its points left.
        if (prev.get("skills") != snap.get("skills")
                or prev.get("unspent") != snap.get("unspent")):
            item = self.chargen.current()
            if item is not None and item.section in ("skill", "points"):
                text = item.announce()
                unspent = snap.get("unspent")
                if item.section == "skill" and unspent is not None:
                    text += ", " + tr("chargen.skill_points_left",
                                      "{points} skill points left", points=unspent)
                ann.answer(text)
                return

        moved = (prev.get("selection") != snap.get("selection")
                 or prev.get("folder") != snap.get("folder"))
        if moved:
            item = self.chargen.current()
            if item is not None and item.section in POINTER_SECTIONS:
                # **Not yet.** The words for these rows live in pointers the
                # engine sets when it redraws the box, a frame after the row
                # moves. Read now, a folder row says whatever the PREVIOUS row
                # was called -- the measured walk caught "Kills" on a perks row
                # and "SKILL POINTS" on Agility. So wait for them to settle.
                self._settling = True
                return
            self._settling = False
            if item:
                ann.answer(item.announce())
            else:
                # A row outside the map. Say the number rather than nothing: a
                # confident wrong label would be worse than silence, but silence
                # is what makes a screen feel broken. It goes to the console
                # too, so the next measuring session knows where to look.
                index = snap.get("selection")
                print("[chargen] no entry for editor row {}".format(index),
                      flush=True)
                ann.answer(tr("chargen.unknown_row", "Item {number}, not covered yet.",
                              number=index))
            return

        # Settled: the label and the card have held still for a whole poll.
        if self._settling:
            if (prev.get("label") == snap.get("label")
                    and prev.get("card") == snap.get("card")):
                self._settling = False
                item = self.chargen.current()
                if item:
                    ann.answer(item.announce())

    def _dialog_opened(self, which: str) -> str:
        """Name the dialog and read its current value.

        The value, not the controls. A player who has just pressed S wants to
        know what the sex currently IS -- that is the thing they cannot see and
        the thing they are about to change. Left and right work here the way
        they work everywhere else in this game, and reciting that every time is
        the habit the control readout was removed for.
        """
        if which == "name":
            name = self.chargen.name()
            return tr("chargen.name_dialog", "Name. {name}",
                      name=name if name and name != "None"
                      else tr("chargen.empty", "Empty."))
        if which == "age":
            return tr("chargen.age_dialog", "Age {age}.", age=self.chargen.age())
        if which == "sex":
            return tr("chargen.sex_dialog", "Sex. {sex}.",
                      sex=self.chargen.sex_name() or tr("chargen.not_known", "not known"))
        return which.capitalize() + "."

    @staticmethod
    def _name_change(before, after) -> str:
        """What to say when the name buffer changed.

        In practice this fires once, when the name is accepted, because the
        buffer commits rather than tracking the keystrokes -- see `snapshot`.
        From an empty field that is the append case, so accepting "Chosen One"
        says "Chosen One", which is exactly right.

        The incremental cases are still handled, and cheaply, because they are
        what the announcement should be if the buffer ever does move a letter at
        a time: hearing "C", "Ch", "Cho" is how you follow your own typing, and
        hearing the whole field back on every letter is how you stop being able
        to. Anything that is neither an append nor a deletion -- a field cleared
        and refilled -- reads the lot, because then the whole thing is the news.
        """
        before, after = before or "", after or ""
        if not after:
            return tr("chargen.name_cleared", "Name cleared.")
        if after.startswith(before):
            # Includes the very first letter, where `before` is empty and the
            # whole of `after` is what was just typed.
            return after[len(before):]
        if before.startswith(after):
            return "{}, {}".format(before[len(after):], after)
        return tr("chargen.summary_name", "Name {name}", name=after)

    def repeat(self, ann: Announcer) -> None:
        self._sync()
        perk = self._perk()
        if perk is not None:
            ann.answer(perk.announce())
            return
        item = self.chargen.current()
        if item:
            ann.answer(item.announce())

    def describe(self, ann: Announcer) -> None:
        self._sync()
        perk = self._perk()
        if perk is not None:
            # What the perk does: the card beside the list, in perk.msg's words.
            text = perkpick.description(self.chargen.proc, perk.perk)
            ann.answer("{}. {}".format(perk.name, text or tr("words.no_description",
                                                             "No description.")))
            return
        item = self.chargen.current()
        if item and item.description:
            ann.answer("{}. {}".format(item.label, item.description))
        elif item:
            ann.answer(tr("inventory.no_description", "{name}. No description.",
                          name=item.label))

    def summary(self, ann: Announcer) -> None:
        self._sync()
        ann.answer(self.chargen.summary())


# The key list that used to be spoken here is gone, on the owner's instruction:
# it was said on every entry to the world AND on every summary, which made it
# the most-heard sentence in the mod, and a player who has read the readme is
# being told what they already know every time they load a game. The keys are
# documented in the manual (docs/manual.html), where they can be consulted once
# rather than recited forever.
#
# Note what went with it, since it was the argument for keeping it: this string
# had to be maintained by hand against gl_world.ssl's on_key, because the script
# owns those keys and cannot report what it bound them to. It had already been
# wrong once for a whole release -- promising that numpad 8 returned the cursor
# to you when 8 had become north -- so the mod's most-repeated sentence was also
# one of its few untrue ones. A document that is read deliberately can be fixed;
# a recital nobody asked for is just a lie repeated at volume.


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
    # Who you are. Absorbed by the log, which puts it into the hex readout in
    # place of the word "you". Listed in its own right rather than left to the
    # prefix above: it is only silent by accident of sharing four letters with
    # a different line, and nobody wants their own name announced on every map.
    "WORLD:dudename",
    "WORLD:miscobj",  # every MISC object the exits scanner considered
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
    TITLE = "Map"
    # The message log, set by App. Floating text goes into it from here.
    history = None
    # The map's keys are almost all read by gl_world.ssl itself, so these are
    # listed for F1 rather than dispatched -- except the two mouse buttons,
    # which only exist here.
    KEYS = (
        Binding("Numpad 7, 9, 4, 6, 1 and 3", "move the look cursor; 5 comes back to you",
                controls.GAME),
        Binding("Numpad plus", "left click on the look cursor's hex", "mouse",
                ("click",)),
        Binding("Numpad minus", "right click there", "mouse", ("rclick",)),
        Binding("Numpad dot", "what can I do to this", controls.GAME),
        Binding("Square brackets", "the scanner: next and previous kind of "
                "thing, with Shift which one, with Control the category",
                controls.GAME),
        Binding("Slash", "go to the thing the scanner is on", controls.GAME),
        Binding("Shift and slash", "the way to the look cursor", controls.GAME),
        Binding("Control and slash", "walk all the way there; again to stop",
                controls.GAME),
        Binding("Semicolon", "how you are doing; with Shift, what you hold",
                controls.GAME),
        Binding("N and B", "attack mode and hands", controls.GAME),
        Binding("U", "use what is in your hand", controls.GAME),
        Binding("Shift and 1", "how much light is on the look cursor's hex",
                controls.GAME),
        Binding("F6 and F7", "quick save and quick load", controls.GAME),
    )
    TALK_KEYS = (
        Binding("Up and Down", "the replies", "previous", ("dlg_prev",),
                "dlg_step", (-1,)),
        Binding("Up and Down", "the replies", "next", ("dlg_next",),
                "dlg_step", (1,)),
        # Dispatched by App._do_action, which has the window to type into.
        Binding("Enter", "say the reply you are on", "choose", ("enter",)),
        Binding("Numpad 5", "that reply again", "repeat", ("dlg_say",),
                "dlg_say"),
        Binding("The number row", "say a reply by its number", controls.GAME),
    )
    ITEM_KEYS = (
        Binding("Up and Down", "the items", controls.GAME),
        Binding("Left and Right", "the lists", controls.GAME),
        Binding("Enter", "move the item: once to pick it up, once where it "
                "goes", controls.GAME),
        Binding("Numpad dot", "what can I do with this item", controls.GAME),
        Binding("A", "take everything, in a container", controls.GAME),
        Binding("O", "offer, when trading", controls.GAME),
        Binding("Escape", "close it", controls.GAME),
    )

    def help_keys(self) -> tuple:
        if self.talking():
            return self.TALK_KEYS
        if self.inventory.open:
            return self.ITEM_KEYS
        return self.KEYS

    def help_title(self) -> str:
        if self.talking():
            return tr("screen.conversation", "Conversation")
        if self.inventory.open:
            return tr("screen.item_window", "Item window")
        return super().help_title()

    def __init__(self, log: WorldLog, saves: Optional[SaveWatcher] = None,
                 proc=None, ticker=None) -> None:
        self.log = log
        self.saves = saves
        # One short tick per hex walked. Defaulted rather than required so the
        # tests, which drive this watcher with nothing but log lines, do not
        # have to hand it anything -- and a disabled Ticker plays nothing and
        # loads nothing, so constructing one costs a test nothing either.
        self.ticker = ticker if ticker is not None else sound.Ticker(enabled=False)
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
        # Enter in an item window: gl_inven.ssl takes the key and says so, and
        # the App moves the item off the parsing path.
        self.pending_move = False
        # Set from WORLD:unsafe: the scripts can call the engine's own actions.
        self.engine_actions = False
        # What the pointer was actually put on when the menu was built.
        # The script names the object it opened the menu for, and the two
        # must agree -- the action array is never cleared, only overwritten,
        # so a stale read is a confident list about the wrong thing.
        self._menu_aimed_at: Optional[str] = None
        self._dumped = False
        self.combat = CombatWatcher()
        self.scanner = Scanner()
        self.inventory = InventoryWatcher()
        # A conversation is read straight out of memory rather than reported by
        # a script, because it is all static globals and Python can see them --
        # the same reason the character editor never needed a script either.
        # The scripts exist for what only the engine knows.
        self.dialogue = dialogue.Dialogue(proc) if proc is not None else None
        # Lines said over characters' heads. The script names who; this reads
        # what, out of the bitmap the engine drew it into. Built now rather
        # than on the first line, because it loads the game's font and text
        # from disk on a thread and the first line should not wait for that.
        self.floats = None
        game_dir = getattr(proc, "directory", None) if proc is not None else None
        if game_dir:
            self.floats = floattext.FloatReader(proc, game_dir)
        self._dlg_said: Optional[tuple] = None   # last reading announced
        self._dlg_seen: Optional[tuple] = None   # last reading observed
        self._dlg_ticks = 0
        self._dlg_open = False
        # Which reply the list cursor is on. The mod's own idea, not the
        # engine's -- Fallout has no selected reply, only whichever one the
        # mouse happens to be over. It is reset by every new thing the NPC
        # says, because the replies are new too.
        self.dlg_index = 0
        self._queue: list = []
        self._mode: Optional[int] = None
        # skill.msg, resolved lazily -- see _skill_names.
        self._skills: dict = {}

    def _float_said(self, line: str) -> Optional[str]:
        """What to say for a WORLD:float line: who said it, and what.

        Your own lines are said bare. Hearing your own name before something
        you said is noise; hearing Torr's before something Torr said is the
        whole point.
        """
        parsed = floattext.float_line(line)
        if parsed is None or self.floats is None:
            return None
        ptr, created, yours, who = parsed
        text = self.floats.read(ptr, created)
        if not text:
            return None
        if yours or not who:
            return text
        return "{}: {}".format(who, text)

    def _skill_names(self):
        """skill.msg, read out of the running game and cached.

        Not cached when empty: the list is only loaded once a game is, so
        asking too early and keeping the answer would leave every skill in the
        Skilldex called "skill 9" for the rest of the session.
        """
        if not self._skills and self.proc is not None:
            # One dot, not two. This module is fallout2_access.app, not one of
            # its game submodules, and the two-dot version reaches past the top
            # of the package -- an ImportError raised on the first Skilldex line
            # and, because the loop only caught OSError, took the whole mod with
            # it. See the note in run().
            from .msg.memlist import read_message_list
            from .game.chargen import MSG_SKILL

            lst = read_message_list(self.proc, MSG_SKILL)
            if lst:
                self._skills = lst.by_num()
        return self._skills

    def reset(self) -> None:
        self._queue = []
        # **Not the item window, when the item window has not gone anywhere.**
        #
        # This runs whenever the mod comes back to the map from a screen of its
        # own, and the "Move Items" window made that a screen of its own for the
        # first time. It is a panel drawn OVER the inventory, loot or barter
        # window: the item window's mode bit never clears, so gl_inven.ssl never
        # sees a change and will never announce the window again. Throwing the
        # reading away here was therefore permanent for the rest of the trade.
        #
        # What it cost is worth writing down, because none of it looks like an
        # inventory bug from the outside. `open` false makes `talking()` true,
        # so up and down started walking the conversation's reply list -- the
        # replies waiting for the player AFTER the barter -- while left and
        # right still stepped the item lists, because those are the in-game
        # script's own keys and never come through here at all. And `rect` and
        # `side` being None make `move_item` answer "Nothing selected." to
        # every press, so the trade could not be finished either.
        #
        # The game mode is the thing to ask: it is the engine stating which
        # window is up, where `open` is only the mod's memory of having been
        # told once.
        if not screens.is_item_window(self.log.game_mode):
            self.inventory.reset()
        self._dlg_said = None
        self._dlg_seen = None
        self._dlg_ticks = 0
        self._dlg_open = False

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
            elif line.startswith("INVEN:enter"):
                self.pending_move = True
            elif line.startswith("INVEN:menu"):
                said = inventory.menu_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("INVEN:look"):
                # The one item action that arrives finished. Use and drop are
                # deferred to the loop below because they drive the pointer and
                # take seconds; a description is already a string, so holding it
                # back would only delay it.
                said = inventory.look_line(line)
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
                # The attack bar's selection is the exception: it is the answer
                # to N or B, and pressing N three times should say the third.
                urgent = line.startswith("COMBAT:bar")
                self._queue.extend((t, urgent) for t in self.combat.handle(line))
            elif line.startswith("WORLD:float"):
                # Not urgent: nobody pressed a key for it, and a character
                # talking should not cut off whatever is being said.
                said = self._float_said(line)
                if said:
                    if self.history is not None:
                        self.history.add(said)
                    self._queue.append((said, False))
            elif line.startswith("WORLD:status"):
                # Urgent: the player pressed a key and this is the answer.
                said = worldlog.status_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("WORLD:ammo"):
                # Not urgent: nobody pressed anything the mod knows about, and
                # a reload arriving mid-sentence should not cut the sentence.
                said = worldlog.ammo_line(line)
                if said:
                    self._queue.append((said, False))
            elif line.startswith("WORLD:route"):
                # Urgent: each is the answer to a key, or the end of a walk
                # the player is waiting on.
                said = worldlog.route_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("WORLD:light"):
                # Urgent: shift and 1 was pressed and this is the answer.
                said = worldlog.light_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("WORLD:weapon"):
                # Urgent: shift-semicolon was pressed and this is the answer.
                said = worldlog.weapon_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("WORLD:useitem"):
                said = worldlog.use_item_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("WORLD:useactive"):
                got = worldlog.use_active_line(line)
                if got:
                    name, _weapon, said = got
                    if said:
                        self._queue.append((said, True))
                    # Arming the item needs the pointer, so it goes to the loop.
                    # A weapon is not excluded: the slot does attack with one
                    # live, and that is what it does for a sighted player
                    # pressing the same control.
                    if name:
                        self.pending_item_action = "useactive"
            elif line.startswith("WORLD:unsafe"):
                # Whether the scripts may call the engine's action functions,
                # which is what lets the action menu reach things no pointer
                # can. Printed once per load.
                self.engine_actions = line.startswith("WORLD:unsafe 1")
            elif line.startswith("SKILLDEX:sneak"):
                said = charsheet.sneak_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("SKILLDEX:"):
                said = charsheet.skilldex_line(line, self._skill_names())
                if said:
                    self._queue.append((said, True))
            elif line.startswith("WORLD:pick"):
                said = worldlog.pick_line(line)
                if said:
                    self._queue.append((said, True))
            elif line.startswith("WORLD:attack"):
                said = worldlog.attack_line(line)
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
                    # Not for a conversation. The mode's registered name is the
                    # bare word "dialogue", and it was landing a beat ahead of
                    # the conversation itself -- so clicking on somebody to talk
                    # to them read as "dialogue. Conversation. Greetings, Chosen
                    # One!". Two announcements of the same event, the first of
                    # which says less than the second and arrives first.
                    # _pump_dialogue names the screen and reads it, which is the
                    # whole announcement rather than a trailer for it.
                    # Nor for the pause menu and preferences, which are
                    # screens of their own now and say what they are on
                    # arrival -- this said "escape menu" over the top of that,
                    # or a beat later on the way back to the map.
                    if not (screens.is_dialogue(self.log.game_mode)
                            or self.log.game_mode & (screens.MODE_ESCMENU
                                                     | screens.MODE_OPTIONS)):
                        self._queue.append(
                            (screens.mode_name(self.log.game_mode), False))
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
                self._queue.append((tr("app.new_area", "New area."), False))
            elif line.startswith("WORLD:dude "):
                # One hex, and a tick rather than a sentence.
                #
                # This line has always been here and has always been silenced,
                # correctly: twelve "moved 1 hex" across one room is why the
                # arrival is announced at the end instead. What that left was
                # several seconds of nothing in the middle of a walk -- and
                # nothing is also what a mod that has stopped working sounds
                # like, which is exactly how players read it.
                #
                # A sound is what speech could not be here. It does not
                # interrupt, does not queue, and does not have to be listened
                # to; its rhythm is the pace, the way footsteps are for a
                # sighted player. The trailing space in the prefix matters --
                # "WORLD:dudename" is a different line entirely.
                self.ticker.step()
            elif line.startswith("WORLD:arrive"):
                # You walked and stopped. This is the confirmation that a click
                # did what it was meant to -- and its absence was why a working
                # click read as a broken one: the mod said nothing at all while
                # the player walked three hexes across the map.
                parts = line.rstrip("|").split()
                dist = parts[3] if len(parts) > 3 else "?"
                self._queue.append(
                    (tr("app.moved", "Moved {distance}.",
                        distance=words.hexes(int(dist)) if dist.isdigit() else dist),
                     False)
                )
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
        ann.answer(tr("app.exploring", "Exploring."))

    def poll(self, ann: Announcer) -> None:
        while self._queue:
            item, urgent = self._queue.pop(0)
            text = (item.announce(self.log.player_name)
                    if isinstance(item, HexReading) else str(item))
            # force=True throughout: the Announcer suppresses a line identical
            # to the one before, which is right for a 20Hz memory poll and
            # wrong for anything that actually happened. Numpad 5 re-reads the
            # hex you are already on and so produces the identical string every
            # time; two neighbouring empty hexes at the same distance do too.
            # Pressing a key and hearing nothing is indistinguishable from the
            # key not arriving.
            ann.say(text, interrupt=urgent, force=True)
        self._pump_dialogue(ann)

    def talking(self) -> bool:
        """Is a conversation the thing on screen?

        The barter window is a conversation's child, and while it is up it is
        what the player is looking at -- gl_inven.ssl owns it and is already
        describing both lists. Two voices narrating different halves of the
        same screen is worse than either on its own.

        **Asked of the game mode as well as of the mod's own note.** `open` is a
        latch: it is set when the script says a window opened and cleared when
        the script says it closed, so anything that clears it while the window
        is still there hands the conversation a screen it is not on. That
        happened -- see `reset` -- and the symptom was up and down walking the
        reply list in the middle of a trade. The engine's mode says which window
        is up as a fact, so it is what decides, and the latch only narrows it
        further.
        """
        return (self.dialogue is not None
                and screens.is_dialogue(self.log.game_mode)
                and not screens.is_item_window(self.log.game_mode)
                and not self.inventory.open)

    def _pump_dialogue(self, ann: Announcer) -> None:
        """Say what was said, and what can be said back.

        Runs off the memory poll rather than off a script line, because there
        is no script line: the whole screen is static globals. That also makes
        this the one watcher that cannot fall behind -- it reports what is on
        screen at the moment it speaks, not what a log said a moment ago.
        """
        if self.dialogue is None:
            return
        if not self.talking():
            if self._dlg_open:
                # Nothing is said. The mode change back to the map is announced
                # on its own -- "exploring" -- which is a statement about where
                # the player now is rather than a note about what just stopped.
                self.reset_dialogue()
            return

        reading = self.dialogue.read()
        if reading is None:
            return

        # A conversation on its way out is not a conversation saying something.
        #
        # Choosing [Done] tears the screen down in stages: the reply list is
        # emptied while the NPC's last line is still sitting in memory and the
        # game mode still reads DIALOG. That transient is a perfectly stable
        # reading with a new identity, so it was announced -- which is why
        # ending a conversation repeated the last thing said back at you on the
        # way out. There is nothing left to answer, so there is nothing to say.
        if self._dlg_open and not reading.options:
            return
        key = reading.key()
        if key != self._dlg_seen:
            self._dlg_seen = key
            self._dlg_ticks = 1
            return
        self._dlg_ticks += 1
        if self._dlg_ticks < DIALOGUE_STABLE_TICKS or key == self._dlg_said:
            return

        opening = not self._dlg_open
        self._dlg_open = True
        self._dlg_said = key
        self.dlg_index = 0
        # Entering a conversation interrupts: the player clicked on somebody
        # and the map may still be mid-sentence about the hex they clicked.
        # A line spoken later in the conversation does not -- it queues behind
        # whatever is still being said, because losing it would lose the
        # conversation itself.
        ann.say(dialogue.say_reading(reading, opening=opening, hint=opening),
                interrupt=opening, force=True)

    def reset_dialogue(self) -> None:
        self._dlg_open = False
        self._dlg_said = None
        self._dlg_seen = None
        self._dlg_ticks = 0
        self.dlg_index = 0

    def dlg_step(self, ann: Announcer, delta: int) -> None:
        """Walk the reply list. Up and down, as everywhere else in the mod.

        Clamped, not wrapped -- the same choice the action menu made, and for
        the same reason: a list that wraps is one you can walk off the end of
        without noticing, and every entry on this one is something you are
        about to say to somebody.
        """
        reading = self.read_dialogue()
        if reading is None or not reading.options:
            ann.answer(tr("app.no_replies_offered", "No replies offered."))
            return
        self.dlg_index = max(0, min(self.dlg_index + delta,
                                    len(reading.options) - 1))
        ann.answer(dialogue.say_option(self.dlg_index, reading.options))

    def dlg_say(self, ann: Announcer) -> None:
        """Re-read the reply the list cursor is on."""
        reading = self.read_dialogue()
        if reading is None:
            ann.answer(tr("app.cannot_read_the_replies", "Cannot read the replies."))
            return
        ann.answer(dialogue.say_option(self.dlg_index, reading.options))

    def read_dialogue(self):
        return self.dialogue.read() if self.dialogue is not None else None

    def repeat(self, ann: Announcer) -> None:
        # A panel over the map takes the question with it. "Repeat" while the
        # loot window is open means the item under the list cursor, not the hex
        # the player last looked at before they opened it.
        if self.inventory.open:
            ann.answer(self.inventory.repeat() or nothing_selected())
            return
        # In a conversation the question this key asks is "what can I say?".
        # The hex the player was last looking at is not what is on screen.
        if self.talking():
            reading = self.read_dialogue()
            ann.answer(dialogue.say_options(reading.options) if reading
                       else tr("app.cannot_read_the_replies", "Cannot read the replies."))
            return
        if self.log.last_hex:
            ann.answer(self.log.last_hex.announce(self.log.player_name))
        else:
            ann.answer(tr("app.no_hex_read_yet_press_numpad_5", "No hex read yet. Press numpad 5."))

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
            #
            # gl_inven.ssl reads numpad dot itself now, so the key has already
            # reached the script and the list is already opening. This used to
            # synthesise an `m`, and that round trip could lose the press
            # entirely -- a queued hotkey runs only on a settled tick and is
            # discarded after a second. The map's menu is where that was caught,
            # but the fault was in the journey, not the destination, and this
            # list took the same journey.
            #
            # The no-process fallback stays: with nothing attached there is no
            # script to have read the key, so this is the only thing that can
            # answer at all.
            if self.hwnd is None:
                ann.answer(self.inventory.repeat() or nothing_selected())
            return
        # And here it asks the third question this key has been given: what did
        # they just say? A long reply is a paragraph, and one a player wants to
        # hear again without the list of answers after it every time.
        if self.talking():
            reading = self.read_dialogue()
            if reading is None:
                ann.answer(tr("app.cannot_read_what_they_said", "Cannot read what they said."))
            else:
                ann.answer(reading.reply or tr("app.they_have_said_nothing", "They have said nothing."))
            return
        if self.hwnd is None:
            ann.answer(tr("app.not_attached_to_the_game", "Not attached to the game."))
            return
        if not screens.is_map_mode(self.log.game_mode):
            ann.answer("{}.".format(
                screens.mode_name(self.log.game_mode).capitalize()))
            return

        # **No aiming, and no keystroke either.** This used to say "Checking",
        # then spend several seconds driving the pointer onto the object,
        # holding the button down for the engine to build its icon strip, and
        # stepping away again -- and it could still come back with the wrong
        # object, or none, because it was inferring which thing the player
        # meant from where a pointer landed. The script reads the hex directly
        # with tile_get_objs instead and offers what is on it.
        #
        # What is left here is only the bookkeeping. gl_world.ssl now binds
        # numpad dot itself, so the key the player pressed has already reached
        # the script by the time this runs and the menu is already opening. It
        # used to synthesise an `m` at this point, which was the mod pressing a
        # key it had taken from the game in order to give itself back the thing
        # it had taken -- and that round trip is what made the menu
        # intermittent, because a queued hotkey only runs on a settled tick and
        # is discarded after a second.
        #
        # The reset stays, and has to. It is the note that says nothing was
        # aimed at, so the cross-check on the menu line does not compare the
        # script's answer against a target left over from some earlier aim and
        # announce a perfectly good menu as the wrong thing.
        self._menu_aimed_at = None

    def summary(self, ann: Announcer) -> None:
        # "Where am I" is answered by whatever currently owns the screen. Each
        # of these is a different question wearing the same key.
        if self.inventory.open:
            said = "{}. {}".format(
                self.inventory.container or screens.mode_name(self.log.game_mode),
                self.inventory.repeat() or nothing_selected())
            # In a trade the two totals are the other thing on screen that a
            # sighted player keeps an eye on without asking.
            totals = self.inventory.totals()
            if totals:
                said = "{} {}".format(said, totals)
            ann.answer(said)
            return
        if self.talking():
            reading = self.read_dialogue()
            ann.answer(dialogue.say_reading(reading, opening=True, hint=True)
                       if reading else tr("app.cannot_read_the_conversation", "Cannot read the conversation."))
            return
        # In a fight, "where am I" means AP and whose turn it is. The hex-cursor
        # key reminder is not what you need while something is biting you.
        if self.combat.in_combat:
            ann.answer(self.combat.summary())
            return
        cursor = screens.cursor_name(self.log.cursor_mode)
        ann.answer("{}.{}".format(screens.mode_name(self.log.game_mode),
                (" " + cursor + ".") if cursor else ""))


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
    TITLE = "Save and load"
    KEYS = (
        Binding("Up and Down", "the slots", controls.GAME),
        Binding("Left and Right", "the pages", controls.GAME),
        Binding("Enter", "save or load the slot", controls.GAME),
        Binding("Escape", "back", controls.GAME),
    )

    def __init__(self, screen, saves: SaveWatcher, pager) -> None:
        self.screen = screen
        self.saves = saves
        self.pager = pager
        self._selection: Optional[int] = None
        self._page: Optional[int] = None
        # Which confirmation box is up, as (address, size, buttons), or None.
        # Tracked so each box is announced once on arrival rather than twenty
        # times a second -- and by identity rather than as a yes or no,
        # because saving over a game is two boxes back to back, and a flag
        # that was already set when the second replaced the first said
        # nothing about it.
        self._confirm = None
        # An overwrite was asked about on this slot, so the box after it is
        # the one that takes the save's description.
        self._overwrite_asked = False

    def reset(self) -> None:
        self._selection = None
        self._page = None
        self._confirm = None
        self._overwrite_asked = False

    def _saved(self):
        return {s.number: s for s in self.saves.scan()}

    def _confirm_line(self, box) -> str:
        """What to say about the confirmation box the screen just put up.

        This is the screen's last step and it was completely silent: Enter on a
        slot raised a small window, nothing said so, and the save appeared to
        hang. Measured on a live save screen -- a box, two buttons, Escape
        cancels, a second Enter writes the file.

        The question is described rather than transcribed, and the difference
        matters. Its text is drawn into the window and cannot be read back, so
        what is said here is assembled from things that CAN be read: which slot
        the highlight is on, whether the engine says that slot holds a game, and
        whether this screen saves or loads. For the overwrite case the game's
        own sentence is used, so it arrives translated.

        One button means a notice rather than a question -- there is nothing to
        cancel. That is said plainly instead of being guessed at, because an
        unreadable message is exactly the thing not to invent words for.
        """
        if len(box.buttons) < 2:
            return (tr("app.the_game_is_showing_a_message_that_cannot_be_read_press_ente", "The game is showing a message that cannot be read. "
                    "Press Enter to dismiss it."))

        index = self.screen.selection()
        page = self.screen.page()
        where = tr("saves.this_slot", "this slot")
        if index is not None and page is not None:
            where = tr("saves.slot", "slot {slot}",
                       slot=self.screen.slot_number(page, index))

        occupied = self.screen.occupied()
        taken = bool(index is not None and index < len(occupied)
                     and occupied[index])
        described = ""
        if taken and index is not None:
            _character, description = self.screen.header(index)
            if description:
                described = ", {}".format(description)

        if self.screen.loading:
            question = tr("saves.load_question", "Load {slot}{description}?",
                          slot=where, description=described)
        elif self._overwrite_asked:
            # **The second Enter.** Saving over a game is two boxes: the
            # overwrite question, then the description, which the engine
            # fills with the old one and takes the next Enter to accept. It
            # came straight in on top of the first box and nothing said so,
            # so the save seemed to need a mystery extra keypress.
            self._overwrite_asked = False
            return tr("saves.description", "Description for the save. Type a "
                      "new one, or press Enter to keep it. Escape cancels.")
        elif taken:
            # The game's own words for the one case it has words for.
            self._overwrite_asked = True
            question = self.screen.message(slotscreen.MSG_OVERWRITE) or \
                tr("app.save_game_already_exists_overwrite", "Save game already exists, overwrite?")
            question = "{} {}{}.".format(question, where.capitalize(), described)
        else:
            question = tr("saves.save_question", "Save to {slot}?", slot=where)
        return "{} {}".format(question, tr("saves.confirm",
                                           "Enter to confirm, Escape to cancel."))

    def _row(self, index: int) -> str:
        occupied = self.screen.occupied()
        taken = occupied[index] if index < len(occupied) else False
        page = self.screen.page()
        if page is None:
            # The row is real and readable; which slot on disk it is, is not.
            # Say the honest half rather than a number that might be ninety out.
            if taken:
                return tr("saves.row_taken", "Row {row}, a saved game.", row=index + 1)
            return tr("saves.row_empty", "Row {row}, empty.", row=index + 1)
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
        return tr("app.went_to_the_saved_games", "Went to the saved games.")

    def _title(self) -> str:
        return tr("app.load_game", "Load game") if self.screen.loading else tr("app.save_game", "Save game")

    def _panel(self):
        return self.screen.panel

    def _page_line(self) -> str:
        page = self.screen.page()
        if page is None:
            # Read, not counted -- so failing to read it is a real answer and
            # not an excuse to fall back on a tally that might be anywhere.
            return tr("app.page_not_known", "Page not known.")
        return tr("saves.page", "Page {page}.", page=page + 1)

    def _current(self) -> str:
        index = self.screen.selection()
        if index is None:
            return tr("app.cannot_read_the_selection", "Cannot read the selection.")
        return self._row(index)

    def poll(self, ann: Announcer) -> None:
        # The confirmation box first, and while it is up nothing else speaks.
        # It is a modal: the row list behind it is not what the player is
        # answering, and narrating a highlight they can no longer move would be
        # actively misleading.
        box = self.screen.confirm()
        if box is not None:
            seen = (box.addr, box.width, box.height, len(box.buttons))
            if seen != self._confirm:
                self._confirm = seen
                ann.answer(self._confirm_line(box))
            return
        if self._confirm:
            self._confirm = None
            # Nothing is said on the way out. Confirming produces a save, which
            # the savegame watcher announces from the folder; cancelling puts
            # the highlight back, which the row poll below announces anyway.
            self._selection = None

        # The page, before the row. Left and right are the game's own page
        # controls and the mod had no idea they existed: it watched the
        # highlight, which does not move when the page does, so paging with the
        # arrows changed all ten rows under a player in complete silence. That
        # was survivable only while numpad + and - were the paging keys the mod
        # knew about, and they are gone -- the arrows do it better and without a
        # pointer.
        #
        # Reading the page rather than counting the presses, as everywhere else
        # on this screen: on a screen that overwrites saved games, a page number
        # nobody checked is worse than none.
        page = self.screen.page()
        if page != self._page:
            first = self._page is None
            self._page = page
            if not first:
                # The row comes with it. Landing on a new page means a different
                # slot under the highlight, and that is the thing about to be
                # saved over or loaded.
                ann.answer(self._page_line() + " " + self._current())
                self._selection = self.screen.selection()
                return

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
            listed = ", ".join(str(p + 1) for p in pages)
            if len(pages) == 1:
                where = tr("saves.on_page", "Saved games on page {pages}.", pages=listed)
            else:
                where = tr("saves.on_pages", "Saved games on pages {pages}.", pages=listed)
        if taken == 1:
            here = tr("saves.one_here", "1 game on this page.")
        else:
            here = tr("saves.here", "{count} games on this page.", count=taken)
        ann.answer(" ".join(x for x in (
            "{}.".format(self._title()), here,
            self._page_line(), where, self._current()) if x))

    # There is no `page` here any more. Stepping the pages by driving their
    # buttons with the pointer was the mod's answer before anybody tried the
    # arrow keys, which do it outright. The Pager itself stays: `_seek_saves`
    # still uses it to walk to the page your games are actually on, and that is
    # a move nobody asked for and so has to be made rather than suggested.


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
    TITLE = "Explosive timer"
    KEYS = (
        Binding("Up and Right", "longer", "more", ("dlg_prev", "num8", "right"),
                "adjust", (1,)),
        Binding("Down and Left", "shorter", "less", ("dlg_next", "num2", "left"),
                "adjust", (-1,)),
        Binding("Home", "the shortest", "least", ("home",), "adjust",
                (-timerwin.MAX_STEPS,)),
        Binding("End", "the longest", "most", ("end",), "adjust",
                (timerwin.MAX_STEPS,)),
        Binding("Enter", "arm it", "choose"),
        Binding("Escape", "cancel", "back"),
        Binding("Numpad 5", "say it again", "repeat", ("dlg_say",), "repeat"),
    )

    def __init__(self, timer) -> None:
        self.timer = timer

    def reset(self) -> None:
        self.timer.steps = None

    def enter(self, ann: Announcer) -> None:
        # It opens on the engine's own starting value, so there is nothing to
        # do first -- see timerwin.START_STEPS.
        self.timer.start()
        ann.answer(tr("timer.opened", "Explosive timer. {time}. Up and down change "
                      "it, Enter arms it, Escape cancels.", time=self._time()))

    def _time(self) -> str:
        if self.timer.steps is None:
            return tr("app.countdown_unknown", "Countdown unknown")
        return timerwin.say_time(self.timer.steps).capitalize()

    def repeat(self, ann: Announcer) -> None:
        ann.answer(self._time() + ".")

    describe = repeat
    summary = repeat

    def adjust(self, ann: Announcer, delta: int) -> None:
        before = self.timer.steps
        now = self.timer.step(delta)
        if now is None:
            ann.answer(tr("app.could_not_change_the_countdown_so_it_is_now_unknown_escape_c", "Could not change the countdown, so it is now unknown. "
                       "Escape cancels."))
            return
        if now == before:
            if delta < 0:
                ann.answer(tr("timer.shortest", "{time}. That is as short as it goes.",
                              time=self._time()))
            else:
                ann.answer(tr("timer.longest", "{time}. That is as long as it goes.",
                              time=self._time()))
            return
        ann.answer(self._time() + ".")


def _say_count(n: int, thing: str) -> str:
    """"1 page", "3 tasks" -- for the few things the Pip-Boy counts."""
    one = n == 1
    if thing == "page":
        return tr("count.one_page", "1 page") if one else tr(
            "count.pages", "{count} pages", count=n)
    if thing == "task":
        return tr("count.one_task", "1 task") if one else tr(
            "count.tasks", "{count} tasks", count=n)
    if thing == "place":
        return tr("count.one_place", "1 place") if one else tr(
            "count.places", "{count} places", count=n)
    if thing == "holodisk":
        return tr("count.one_holodisk", "1 holodisk") if one else tr(
            "count.holodisks", "{count} holodisks", count=n)
    return tr("count.one_film", "1 film") if one else tr(
        "count.films", "{count} films", count=n)


def _say_span(minutes: int) -> str:
    """How long a rest lasted, in the units a person would use.

    "Rested 480 minutes" is a number to convert while you are trying to work out
    whether to rest again, which is exactly what the countdown window taught.
    """
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(tr("count.one_hour", "1 hour") if hours == 1
                     else tr("count.hours", "{count} hours", count=hours))
    if rest or not hours:
        parts.append(tr("timer.one_minute", "1 minute") if rest == 1
                     else tr("timer.minutes", "{minutes} minutes", minutes=rest))
    return " ".join(parts)


class PipboyWatcher(Watcher):
    """The Pip-Boy 2000.

    Two lists, and only one of them is on screen at a time in any useful sense:
    the five **destinations** down the left of the panel, and the **rows** of
    whichever page you opened. Up and down walk whichever list you are in,
    numpad plus chooses, numpad minus comes back out to the destinations. The
    arrows are the keys to reach for; the panel is mouse-only in the engine, so
    nothing is being taken away from anybody.

    **The cursor belongs to the mod here, and that is a departure worth being
    explicit about.** Everywhere else this project refuses to remember what is
    selected, because the engine has a selection and remembering one alongside
    it is how the speech drifts out of sync. The Pip-Boy has no selection to
    read: it is a mouse screen, and what is "highlighted" is whatever the
    pointer happens to be over. So there is nothing to desync *from*. What is
    still read every time is the list itself -- the destinations and rows come
    off the engine's buttons on every keypress, and the index is clamped to what
    is really there rather than trusted.
    """

    key = screens.PIPBOY
    TITLE = "Pip-Boy"
    KEYS = (
        Binding("Up and Down", "move", "previous", ("dlg_prev", "num8"),
                "step", (-1,)),
        Binding("Up and Down", "move", "next", ("dlg_next", "num2"),
                "step", (1,)),
        Binding("Enter", "choose", "choose", ("enter",), "choose"),
        Binding("Backspace", "back to the Pip-Boy's main list", "back",
                ("back",), "back"),
        Binding("Escape", "close the Pip-Boy", "back"),
        Binding("Numpad 5", "say it again", "repeat", ("num5", "dlg_say"),
                "repeat"),
    )

    # How long to let the panel rebuild after a page is opened, before reading
    # its rows. A page swap is a click and a redraw, and reading in the same
    # breath returns the previous page's rows -- which reads as the key not
    # having worked.
    SETTLE = 0.9

    # `page` holds the destination whose page is open. This stands in for one
    # that is open but was not opened from here -- `Z` arrives straight on the
    # alarm clock, and a page nobody chose is still a page you are on. Nothing
    # reads the value except the test for "am I on a page at all"; it is a
    # marker, not an address.
    OTHER_PAGE = -1

    def __init__(self, pip) -> None:
        self.pip = pip
        self.index = 0
        self._announced = False
        # None while on the destination list; otherwise the destination whose
        # page is open. This is the mod's note of where it took you, not a
        # reading -- but `_rows()` never trusts it, and `pipboy.is_alarm_page`
        # asks the engine instead when it matters.
        self.page: Optional[int] = None

    # -- reading -----------------------------------------------------------

    def reset(self) -> None:
        self.index = 0
        self.page = None
        self._announced = False

    def _window(self):
        return self.pip.window()

    def _entries(self, win) -> list:
        """(name, button, code) for whichever list the cursor is in.

        The code travels with the entry rather than being looked up by
        position afterwards. A destination the engine is not offering is not in
        this list, so an index into it is not an index into `DESTINATIONS` --
        which is the kind of quiet off-by-one that would open Archives when you
        asked for Automaps.
        """
        if self.page is None:
            return [(self.pip.name_of(code), b, code)
                    for code, b in pipboy.destinations(win)]
        rows = pipboy.rows(win)
        names = self.pip.rest_names(rows)
        if names is not None:
            return [(n, b, b.release) for n, b in zip(names, rows)]
        listed = self._listed(rows)
        if listed is not None:
            return listed
        # A page whose words cannot be read is still a page that can be walked
        # and clicked. Numbering them says the one thing that is certainly
        # true, and it is a great deal more than the silence this screen used
        # to answer with.
        return [(tr("pipboy.entry", "Entry {number}", number=i + 1), b, b.release)
                for i, b in enumerate(rows)]

    def _listed(self, rows) -> Optional[list]:
        """The Status and Archives pages, named from the engine's own tables.

        These two are not read off the panel -- nothing on it can be read --
        they are rebuilt from the tables the engine parsed and the global
        variables it gates them on, using the rule taken from the engine's own
        drawing loop.

        **And the rebuild is checked against the panel before it is trusted.**
        The Status page draws one more row button than it has entries, which is
        the engine's own spare; Archives draws exactly as many as it lists. If
        the count the mod computes does not fit, the rule is wrong for this
        state and the rows are numbered instead of named. That check is the
        whole reason this is allowed to speak at all: a reconstruction that
        cannot be compared with anything is just a guess with more steps.
        """
        if self.page == pipboy.STATUS:
            entries = self.pip.status_entries()
            if entries is None:
                return None
            places = sum(1 for kind, _n, _p in entries if kind == "place")
            # Checked against the engine's own counters and **not against the
            # row buttons**. The engine already creates one button past the end
            # of this list, and sfall's `UseScrollingQuestsList` adds controls
            # of its own on top of that -- so how many rows there are is a fact
            # about the install, not about the list. Nothing is clicked on this
            # page anyway; the entries are read out.
            if self.pip.engine_drew(pipboy.LINES_QUEST_LOCATIONS) != places:
                return None
            if (self.pip.engine_drew(pipboy.LINES_STATUS_HOLODISKS)
                    != len(entries) - places):
                return None
            return [(name, None, payload) for _kind, name, payload in entries]
        if self.page == pipboy.ARCHIVES:
            names = self.pip.archive_entries()
            # This page **is** clicked -- choosing a film plays it -- so each
            # name has to line up with the button that plays it, and the row
            # count is part of the check rather than noise.
            if names is None or len(names) != len(rows):
                return None
            if self.pip.engine_drew(pipboy.LINES_ARCHIVES) != len(names):
                return None
            return [(n, b, None) for n, b in zip(names, rows)]
        return None

    def _clamp(self, entries) -> int:
        if not entries:
            self.index = 0
        else:
            self.index = max(0, min(self.index, len(entries) - 1))
        return self.index

    def _current(self, win=None) -> str:
        win = win or self._window()
        if win is None:
            return tr("app.the_pip_boy_is_not_open", "The Pip-Boy is not open.")
        entries = self._entries(win)
        if not entries:
            return tr("app.nothing_on_this_page", "Nothing on this page.")
        i = self._clamp(entries)
        return "{}, {}.".format(entries[i][0], words.of(i + 1, len(entries)))

    def _names(self, win) -> list:
        return [entry[0] for entry in self._entries(win)]

    def _time(self) -> str:
        reading = self.pip.clock()
        return reading.say() if reading else tr("app.the_time_cannot_be_read", "The time cannot be read.")

    def _read_out(self, ann: Announcer, name: str, payload) -> None:
        """Say what a Status entry holds: a place's tasks, or a disk's text."""
        if isinstance(payload, pipboy.Holodisk):
            paragraphs = self.pip.disk_text(payload)
            if not paragraphs:
                ann.answer(tr("pipboy.disk_unreadable", "{name}. Nothing on it that "
                              "can be read.", name=name))
                return
            ann.answer(tr("pipboy.disk", "{name}. {pages} of text.", name=name,
                          pages=_say_count(len(paragraphs), "page")))
            for n, text in enumerate(paragraphs):
                # Queued rather than announced. A holodisk runs to several
                # paragraphs and each one interrupting the last would leave
                # only the final sentence alive -- the failure that made combat
                # read as two numbers and nothing in between.
                ann.say(tr("pipboy.disk_page", "Page {page}. {text}", page=n + 1,
                           text=text),
                        interrupt=False, force=True)
            return

        lines = self.pip.quest_lines(payload)
        if not lines:
            ann.answer(tr("pipboy.no_quests", "{place}. Nothing to do there.",
                          place=name))
            return
        ann.answer("{}. {}.".format(name, _say_count(len(lines), "task")))
        for n, text in enumerate(lines):
            ann.say("{}. {}".format(n + 1, text), interrupt=False, force=True)

    def _rested(self, before) -> str:
        """What resting actually did, measured off the clock.

        **Reported from what moved, not from what was sent**, which is the rule
        every click in this mod follows and which happens to solve a problem
        that looked unsolvable here. The engine's refusal -- "You cannot rest at
        this location!" -- is painted onto the panel like everything else on it,
        so there is no way to read it. But a refused rest is a clock that did
        not move, and the clock can be read exactly.

        So the mod does not say what it asked for. It says what happened, and
        the case where nothing happened is the one a player most needs told.
        """
        after = self.pip.clock()
        if before is None or after is None:
            return self._time()
        minutes = self._minutes_between(before, after)
        if minutes <= 0:
            return tr("pipboy.no_rest", "The clock has not moved, so no time "
                      "passed. Either you cannot rest here, or there was nothing "
                      "to rest for. It is still {time}", time=self._time())
        return tr("pipboy.rested", "Rested {span}. {time}",
                  span=_say_span(minutes), time=after.say())

    @staticmethod
    def _minutes_between(before, after) -> int:
        days = (after.date - before.date).days
        return ((days * 24 + after.hour - before.hour) * 60
                + after.minute - before.minute)

    def _page_line(self, win) -> str:
        """What to say about the page that just opened."""
        rows = pipboy.rows(win)
        if not rows:
            return tr("app.nothing_on_this_page", "Nothing on this page.")
        if self.pip.rest_names(rows) is not None:
            return tr("pipboy.ways_to_rest", "{count} ways to rest.", count=len(rows))
        listed = self._listed(rows)
        if listed is not None:
            if self.page == pipboy.STATUS:
                places = sum(1 for e in listed if not isinstance(e[2],
                                                                pipboy.Holodisk))
                disks = len(listed) - places
                parts = [_say_count(places, "place")]
                if disks:
                    parts.append(_say_count(disks, "holodisk"))
                return tr("pipboy.read_one", "{things}. Enter reads one out.",
                          things=(" " + tr("words.and", "and") + " ").join(parts))
            return "{}.".format(_say_count(len(listed), "film"))
        # Said once, on arrival, and never per row. The player needs to know
        # that the blank names are the mod's limit rather than an empty page --
        # otherwise a working list reads as a broken one.
        return tr("pipboy.pictures", "{count} entries. The Pip-Boy paints this "
                  "page as a picture, so they can be counted and chosen but not "
                  "read out.", count=len(rows))

    # -- announcing --------------------------------------------------------

    def enter(self, ann: Announcer) -> None:
        self.page = None
        self.index = 0
        self._announced = False
        # A box up on arrival can only be Z's: the alarm clock it opens on,
        # refusing.
        self._boxed = False
        self._resting_asked = True
        self.poll(ann)

    def _box_words(self) -> str:
        said = (self.pip.message(pipboy.MSG_CANNOT_REST)
                if getattr(self, "_resting_asked", False) else None)
        return "{} {}".format(
            said or tr("app.a_message_is_up_on_the_pip_boy", "A message is up on the Pip-Boy."),
            tr("pipboy.enter_closes", "Enter closes it."))

    def _box_check(self, ann: Announcer) -> bool:
        """Say a message box arriving or going. True while one is up."""
        boxed = pipboy.box_over(self.pip.proc)
        if boxed and not getattr(self, "_boxed", False):
            self._boxed = True
            ann.answer(self._box_words())
        elif not boxed and getattr(self, "_boxed", False):
            self._boxed = False
            self._resting_asked = False
            # Nothing under it changed: the page that was refused never drew.
            self.page = None
            self.index = 0
            ann.answer(tr("pipboy.main_list", "Pip-Boy main list. {current}",
                          current=self._current()))
        return boxed

    def _close_box(self, ann: Announcer) -> None:
        """Enter on a box: close it the way the box takes. The script keeps
        Enter from the Pip-Boy, which closes on it, so Escape is sent -- the
        box answers both, and with nothing to say yes or no to they are the
        same."""
        from .input.send import guarded_tap
        if self.pip.hwnd is None:
            return
        try:
            guarded_tap(self.pip.hwnd, "escape", settle=0.2)
        except (FocusLost, OSError):
            ann.answer(tr("app.game_is_not_focused", "Game is not focused."))

    def poll(self, ann: Announcer) -> None:
        """Announce the panel, once, as soon as it is really there.

        The engine sets the PIPBOY mode a frame or two before the window
        exists, so `enter` can arrive to nothing. That is the only thing this
        poll is for -- the panel changes only when this class clicks it, and
        the click already says what it did, so re-reading the buttons twenty
        times a second would be watching for an event that cannot happen
        without us causing it.
        """
        if self._window() is not None and self._box_check(ann):
            # The box is the whole screen while it is up: it is modal.
            self._announced = True
            return
        if self._announced:
            return
        win = self._window()
        if win is None:
            return
        self._announced = True

        # **You do not always arrive on the main list.** `Z` is the engine's
        # own key for the alarm clock and it opens the panel already on that
        # page -- measured, thirteen rows and no clicking involved. Landing
        # there and being read the five destinations instead would be the mod
        # describing a screen the player is not looking at, and would hide the
        # one thing they pressed Z to get to.
        if pipboy.rows(win):
            self.page = (pipboy.ALARM_CLOCK
                         if pipboy.is_alarm_page(pipboy.rows(win))
                         else self.OTHER_PAGE)
            ann.answer(tr("pipboy.page_opened", "Pip-Boy. {time} {page} {current} "
                          "Backspace goes to the Pip-Boy's main list.",
                          time=self._time(), page=self._page_line(win),
                          current=self._current(win)))
            return

        names = self._names(win)
        ann.answer(tr("pipboy.opened", "Pip-Boy. {time} {entries} Up and down "
                      "move, Enter chooses, Backspace comes back here.",
                      time=self._time(),
                      entries=". ".join(names) + "." if names else ""))

    def repeat(self, ann: Announcer) -> None:
        ann.answer(self._current())

    def describe(self, ann: Announcer) -> None:
        """The whole list, which is what a sighted player takes in at once."""
        win = self._window()
        if win is None:
            ann.answer(tr("app.the_pip_boy_is_not_open", "The Pip-Boy is not open."))
            return
        entries = self._entries(win)
        if not entries:
            ann.answer(tr("app.nothing_on_this_page", "Nothing on this page."))
            return
        i = self._clamp(entries)
        ann.answer("{}. {}".format(
            words.of(i + 1, len(entries)),
            " ".join("{}, {}.".format(n + 1, entry[0])
                     for n, entry in enumerate(entries))))

    def summary(self, ann: Announcer) -> None:
        ann.answer(tr("pipboy.summary", "Pip-Boy. {time} {current}",
                      time=self._time(), current=self._current()))

    # -- keys --------------------------------------------------------------

    def step(self, ann: Announcer, delta: int) -> None:
        win = self._window()
        if win is None:
            ann.answer(tr("app.the_pip_boy_is_not_open", "The Pip-Boy is not open."))
            return
        if getattr(self, "_boxed", False):
            ann.answer(self._box_words())
            return
        entries = self._entries(win)
        if not entries:
            ann.answer(tr("app.nothing_on_this_page", "Nothing on this page."))
            return
        before = self._clamp(entries)
        self.index = max(0, min(before + delta, len(entries) - 1))
        if self.index == before:
            # Clamped rather than wrapped, and said so. A list that silently
            # wraps is a list you can walk off the end of without noticing.
            ann.answer("{} {}".format(
                tr("app.top", "Top.") if delta < 0 else tr("app.bottom", "Bottom."), self._current(win)))
            return
        ann.answer(self._current(win))

    def back(self, ann: Announcer) -> None:
        """Out of a page and back to the five destinations.

        The mod's own cursor moving, not a click: the destination lights are
        drawn on every page, so leaving a page's rows means nothing has to be
        sent to the game at all.
        """
        if getattr(self, "_boxed", False):
            self._close_box(ann)
            return
        if self.page is None:
            ann.answer(tr("pipboy.already_main", "Already at the Pip-Boy's main "
                          "list. {current}", current=self._current()))
            return
        self.page = None
        self.index = 0
        ann.answer(tr("pipboy.main_list", "Pip-Boy main list. {current}",
                      current=self._current()))

    def choose(self, ann: Announcer) -> None:
        win = self._window()
        if win is None:
            ann.answer(tr("app.the_pip_boy_is_not_open", "The Pip-Boy is not open."))
            return
        if getattr(self, "_boxed", False) or pipboy.box_over(self.pip.proc):
            self._close_box(ann)
            return
        entries = self._entries(win)
        if not entries:
            ann.answer(tr("app.nothing_to_choose_here", "Nothing to choose here."))
            return
        i = self._clamp(entries)
        name, button, code = entries[i]
        opening_page = self.page is None

        # A Status entry is read out, not clicked. The mod already knows what
        # the page would draw -- it computed the list -- so there is nothing to
        # gain by aiming at a rectangle and a second of pointer-driving to lose.
        # It is the same choice the world's action menu makes: act on the thing
        # you picked, by identity, rather than by pointing at it.
        if button is None:
            self._read_out(ann, name, code)
            return

        resting = not opening_page and pipboy.is_alarm_page(pipboy.rows(win))
        before = self.pip.clock() if resting else None

        # Say it before doing it. Driving the pointer onto a rectangle takes
        # the better part of a second, and silence after a keypress is this
        # project's most persistent misreading -- it is what a mod that has
        # stopped working sounds like.
        ann.answer("{}.".format(name))
        self._resting_asked = (code == pipboy.ALARM_CLOCK) or resting
        ok, why = self.pip.press(win, button)
        if not ok:
            ann.answer(tr("pipboy.not_chosen", "Could not choose {name}: {why}.",
                          name=name, why=why))
            return
        if opening_page and code == pipboy.CLOSE:
            return          # the panel is going away; the screen change speaks
        # The game said no with a box. Say what it said and stop: the page
        # did not change, so describing it would describe the wrong one.
        time.sleep(self.SETTLE)
        if self._box_check(ann):
            return

        if not opening_page:
            if not pipboy.showing(self.pip.proc):
                return
            if resting:
                ann.say(self._rested(before), interrupt=False, force=True)
            else:
                # Any other page has moved to something that cannot be read, so
                # say where the cursor is rather than pretending to describe it.
                ann.say(self._current(), interrupt=False, force=True)
            return

        # A destination was opened. It has had its time to draw, above.
        self.page = code
        self.index = 0
        again = self._window()
        if again is None:
            self.page = None
            return
        ann.say(self._page_line(again) + " " + self._current(again),
                interrupt=False, force=True)


class QuantityWatcher(Watcher):
    """The "Move Items" window: how many of a stack.

    It appears whenever a stack of more than one is dragged, which in a shop is
    constantly -- every pile of caps, every handful of stimpaks. Before this it
    was invisible, and worse than invisible: it is the same 259x162 panel as the
    explosive countdown, with the same step buttons, so the mod announced
    "Explosive timer. Setting it to the shortest." over a player who was moving
    bottle caps, and then wound the count down twenty times.

    Done and Cancel are keyboard codes -- 13 and 27 -- so Enter and Escape are
    the game's own keys here and the mod does not take them away. The count
    itself is typed rather than clicked, which is the engine's own second route
    into this window: see quantity.py.
    """

    key = screens.QUANTITY
    TITLE = "How-many window"
    KEYS = (
        Binding("Up and Right", "one more, ten with Control", "more",
                ("dlg_prev", "num8", "right"), "step", (1,)),
        Binding("Down and Left", "one fewer, ten with Control", "less",
                ("dlg_next", "num2", "left"), "step", (-1,)),
        Binding("Home", "just one", "least", ("home",), "fewest"),
        Binding("End", "all of them", "most", ("end",), "take_all"),
    ) + tuple(
        Binding("The number row", "type the amount", "type",
                ("digit{}".format(d),), "digit", (d,)) for d in range(10)
    ) + (
        Binding("Enter", "take it", "choose"),
        Binding("Escape", "cancel", "back"),
        Binding("Numpad 5", "say it again", "repeat", ("dlg_say",), "repeat"),
    )
    # Ten at a time while Control is held; set by App before each key.
    big = 1

    def __init__(self, counter, inventory=None) -> None:
        self.counter = counter
        self.inventory = inventory
        self._announced = False

    def reset(self) -> None:
        # How many there are of the thing being moved. Without it the window
        # can only count up from one and never say what it is counting towards.
        #
        # The item being DRAGGED, which is not the one under the list cursor:
        # a move is two presses and the cursor ends on the destination.
        # Sizing the window from the cursor put a maximum of 24 on a stack of
        # 203 caps because 24 rounds sat where they were going. The selected
        # count is only the fallback, for a window this mod did not open.
        most = None
        if self.inventory is not None:
            most = self.inventory.moving()
            if most is None:
                most = getattr(self.inventory, "selected_count", None)
        self.counter.reset(most if most and most > 1 else None)
        self._announced = False

    def enter(self, ann: Announcer) -> None:
        self.reset()
        self._announced = True
        ann.answer(
            tr("quantity.opened", "How many? {count} Type a number, or up and down "
               "change it, Control for tens. End for all of them. Enter takes it, "
               "Escape cancels.", count=self.counter.say()))

    def step(self, ann: Announcer, delta: int) -> None:
        said = self.counter.step(delta * self.big)
        ann.answer(said if said else tr("app.that_did_not_work", "That did not work."))

    def fewest(self, ann: Announcer) -> None:
        if not self.counter._type(1):
            ann.answer(tr("app.that_did_not_work", "That did not work."))
            return
        self.counter.count = 1
        self.counter.typed = ""
        ann.answer(self.counter.say())

    def digit(self, ann: Announcer, d: int) -> None:
        said = self.counter.digit(d)
        ann.answer(said if said else tr("app.that_did_not_work", "That did not work."))

    def take_all(self, ann: Announcer) -> None:
        said = self.counter.all()
        ann.answer(said if said else tr("app.that_did_not_work", "That did not work."))

    def cancel(self, ann: Announcer) -> None:
        """Numpad minus, which is the right mouse button everywhere else.

        It has to mean something here. Left to fall through it was a real right
        click sent at wherever the pointer had been left -- over a modal window,
        onto the barter screen underneath -- which is the one thing this screen
        must never do. Cancelling is what the mod's other panels put on this
        key, and it is what the window's own Cancel button does.
        """
        ann.answer(tr("app.cancelled", "Cancelled.") if self.counter.cancel()
                   else tr("app.nothing_to_cancel", "Nothing to cancel."))

    def repeat(self, ann: Announcer) -> None:
        ann.answer(tr("app.how_many", "How many?") + " " + self.counter.say())

    def describe(self, ann: Announcer) -> None:
        self.repeat(ann)

    def summary(self, ann: Announcer) -> None:
        self.repeat(ann)


class CalledShotWatcher(Watcher):
    """The called-shot window: which body part an aimed attack goes for.

    A modal loop of the engine's own, so every key the mod has falls in here
    while it is up -- the same rule as the "how many" window. Escape is the
    window's own and already cancels.
    """

    key = screens.CALLED_SHOT
    TITLE = "Aimed shot"
    KEYS = (
        Binding("Up and Down", "choose a body part", "previous",
                ("dlg_prev", "num8"), "step", (-1,)),
        Binding("Up and Down", "choose a body part", "next",
                ("dlg_next", "num2"), "step", (1,)),
        Binding("Enter", "fire", "choose", ("enter",), "choose"),
        Binding("Escape", "cancel", "back"),
        Binding("Numpad 5", "say it again", "repeat", ("num5", "dlg_say"),
                "repeat"),
    )

    def __init__(self, shot) -> None:
        self.shot = shot

    def reset(self) -> None:
        self.shot.reset()

    def enter(self, ann: Announcer) -> None:
        self.shot.reset()
        target = getattr(self.shot.combat, "aim_target", None)
        keys = tr("calledshot.keys", "Up and down choose, Enter fires, Escape cancels.")
        if target:
            ann.answer(tr("calledshot.at", "Aimed shot at {target}. {part} {keys}",
                          target=target, part=self.shot.say(), keys=keys))
        else:
            ann.answer(tr("calledshot.opened", "Aimed shot. {part} {keys}",
                          part=self.shot.say(), keys=keys))

    def step(self, ann: Announcer, delta: int) -> None:
        ann.answer(self.shot.step(delta))

    def choose(self, ann: Announcer) -> None:
        label = self.shot.label()
        if not self.shot.choose():
            ann.answer(tr("app.could_not_reach_that_part_of_the_window_escape_cancels", "Could not reach that part of the window. Escape "
                       "cancels."))
            return
        # What the attack did arrives as a hit or a miss a moment later.
        ann.answer(label.split(",")[0] + ".")

    def cancel(self, ann: Announcer) -> None:
        ann.answer(tr("app.cancelled", "Cancelled.") if self.shot.cancel() else tr("app.nothing_to_cancel", "Nothing to cancel."))

    def repeat(self, ann: Announcer) -> None:
        ann.answer(self.shot.say())

    describe = repeat
    summary = repeat


class PauseWatcher(Watcher):
    """The pause menu. The game's own letters work it; the mod says them.

    And says the one question it can ask: Exit puts up "are you sure?" as a
    box with no words anywhere the mod can read, so it is noticed as a window
    that was not there when the menu opened.
    """

    key = screens.PAUSE
    TITLE = "Pause menu"
    KEYS = (
        Binding("S", "save", controls.GAME),
        Binding("L", "load", controls.GAME),
        Binding("P", "preferences", controls.GAME),
        Binding("E", "exit to the main menu; it asks first", controls.GAME),
        Binding("Escape", "back to the game", controls.GAME),
    )

    def __init__(self, proc) -> None:
        self.proc = proc
        self._before = set()
        self._asking = False

    def reset(self) -> None:
        self._before = pausemenu.live_ids(self.proc)
        self._asking = False

    def enter(self, ann: Announcer) -> None:
        self.reset()
        ann.answer(tr("app.menu_s_saves_l_loads_p_for_preferences_e_exits_to_the_main_m", "Menu. S saves, L loads, P for preferences, E exits to the "
                   "main menu, Escape goes back to the game."))

    def poll(self, ann: Announcer) -> None:
        new = pausemenu.live_ids(self.proc) - self._before
        if new and not self._asking:
            self._asking = True
            ann.answer("{} {}".format(pausemenu.quit_question(self.proc),
                                      tr("pausemenu.yes_no",
                                         "Y or Enter for yes, N or Escape for no.")))
        elif not new and self._asking:
            self._asking = False
            ann.answer(tr("app.menu", "Menu."))

    def repeat(self, ann: Announcer) -> None:
        if self._asking:
            ann.answer("{} {}".format(pausemenu.quit_question(self.proc),
                                      tr("pausemenu.yes_no",
                                         "Y or Enter for yes, N or Escape for no.")))
            return
        ann.answer(tr("app.menu_s_saves_l_loads_p_for_preferences_e_exits_escape_goes_b", "Menu. S saves, L loads, P for preferences, E exits, "
                   "Escape goes back."))

    describe = repeat
    summary = repeat


class PrefsWatcher(Watcher):
    """Preferences, as a list: Up and Down for the setting, Left and Right to
    change it. Enter and Escape are the screen's own Done and Cancel."""

    key = screens.PREFS
    TITLE = "Preferences"
    KEYS = (
        Binding("Up and Down", "the settings", "previous", ("dlg_prev", "num8"),
                "step", (-1,)),
        Binding("Up and Down", "the settings", "next", ("dlg_next", "num2"),
                "step", (1,)),
        Binding("Left and Right", "change it", "less", ("left",), "change",
                (-1,)),
        Binding("Left and Right", "change it", "more", ("right",), "change",
                (1,)),
        Binding("Home", "the lowest", "least", ("home",), "extreme", (False,)),
        Binding("End", "the highest", "most", ("end",), "extreme", (True,)),
        Binding("Enter", "save and close", "choose"),
        Binding("Escape", "close without saving", "back"),
        Binding("Numpad 5", "say it again", "repeat", ("dlg_say",), "repeat"),
    )

    def __init__(self, settings) -> None:
        self.prefs = settings

    def reset(self) -> None:
        self.prefs.reset()

    def enter(self, ann: Announcer) -> None:
        self.prefs.reset()
        ann.answer(tr("prefs.opened", "Preferences. {setting} Up and down move, left "
                      "and right change, Enter saves, Escape cancels.",
                      setting=self.prefs.say()))

    def step(self, ann: Announcer, delta: int) -> None:
        ann.answer(self.prefs.step(delta))

    def change(self, ann: Announcer, delta: int) -> None:
        ann.answer(self.prefs.change(delta))

    def extreme(self, ann: Announcer, top: bool) -> None:
        ann.answer(self.prefs.extreme(top))

    def repeat(self, ann: Announcer) -> None:
        ann.answer(self.prefs.say())

    describe = repeat
    summary = repeat


class WorldMapWatcher(Watcher):
    """Travelling between places.

    The one screen the mod reads entirely for itself. Everywhere else in a
    loaded game the in-game scripts are the source of truth, because only a
    script can ask the engine what is on a hex; here every answer -- the
    player's position, the places, the ground, the fog, the destination -- is a
    plain structure in memory. So there is no log to tail and nothing to wait
    for, and this watcher reads the game directly on every tick.

    **What it watches for, rather than what it was told.** Three things move
    without the mod touching them: the view scrolls when the arrow keys or Home
    are pressed, the journey advances, and it ends -- sometimes because you
    arrived and sometimes because something walked out of the desert at you.
    All three are noticed by comparing this tick's reading against last tick's,
    which is the same discipline the rest of the mod keeps and the reason the
    speech cannot claim a journey that is not happening.
    """

    key = screens.WORLDMAP
    TITLE = "World map"
    KEYS = tuple(
        Binding("Numpad 1 to 9", "move the cursor a square", "cursor",
                ("wm_" + d,), "wm_" + d)
        for d in ("n", "s", "e", "w", "ne", "nw", "se", "sw")
    ) + (
        Binding("Numpad 5", "back to where you are", "cursor", ("wm_snap",),
                "wm_snap"),
        Binding("Square brackets", "the places you know", "scan",
                ("wm_scan_prev",), "wm_scan_prev"),
        Binding("Square brackets", "the places you know", "scan",
                ("wm_scan_next",), "wm_scan_next"),
        Binding("Slash", "put the cursor on that place", "scan",
                ("wm_scan_jump",), "wm_scan_jump"),
        Binding("Enter", "travel to the cursor, or go in", "choose",
                ("enter",), "travel"),
        Binding("T", "the town map", "watch", ("wm_town",), "wm_town"),
    )

    # How far the view must scroll before it is worth mentioning. A press of an
    # arrow key moves it tens of pixels; anything smaller is the engine nudging
    # the view to keep the player's marker in sight while they travel, which is
    # not a thing anybody did and not worth a sentence.
    SCROLL_NOTICE = 8

    # How often the journey may be reported, in seconds. Travel takes in-game
    # days and real seconds, and a progress line on every one of twenty ticks a
    # second is not information, it is a wall.
    PROGRESS_SECONDS = 3.0

    def __init__(self, proc, hwnd=None, log_path: Optional[str] = None,
                 ticker=None) -> None:
        self.proc = proc
        self.hwnd = hwnd
        self.log_path = log_path
        self.ticker = ticker if ticker is not None else sound.Ticker(enabled=False)
        self.cursor = worldcursor.WorldCursor()
        self._scroll: Optional[Tuple[int, int]] = None
        self._travelling = False
        self._dest: Optional[Tuple[int, int]] = None
        self._area: Optional[int] = None
        self._town: Optional[int] = None
        self._spoke_at = 0.0

    def reset(self) -> None:
        self.cursor.reset()
        self._scroll = None
        self._travelling = False
        self._dest = None
        self._area = None
        self._town = None
        self._spoke_at = 0.0

    # -- arriving ------------------------------------------------------------

    def enter(self, ann: Announcer) -> None:
        if self.proc is None:
            return
        self.cursor.snap(self.proc)
        self._scroll = worldmap.scroll(self.proc)
        self._travelling = worldmap.travelling(self.proc)
        self._dest = worldmap.destination(self.proc)
        self._area = worldmap.current_area(self.proc)
        ann.answer(tr("app.world_map", "World map.") + " " + self._where())

    def _where(self) -> str:
        """Where the player is standing, in one sentence."""
        if self.proc is None:
            return ""
        table = worldmap.areas(self.proc)
        index = worldmap.current_area(self.proc)
        if index is not None and 0 <= index < len(table):
            return tr("worldmap.at", "At {place}.", place=table[index].name)
        here = worldmap.player_subtile(self.proc)
        if here is None:
            return ""
        square = worldmap.subtile(self.proc, *here)
        names = worldmap.terrain_names(self.proc)
        ground = names.get(square.terrain) if square else None
        return tr("worldmap.open_country", "In open country. {ground}.",
                  ground=ground) if ground else tr("app.in_open_country", "In open country.")

    # -- the cursor ----------------------------------------------------------

    def _step(self, ann: Announcer, dx: int, dy: int) -> None:
        if self.proc is None:
            return
        moved, why = self.cursor.step_by(self.proc, dx, dy)
        if not moved:
            ann.answer(why)
            return
        self.ticker.step()
        said = self.cursor.say_step(self.proc)
        if said:
            ann.answer(said)

    def wm_nw(self, ann: Announcer) -> None: self._step(ann, -1, -1)
    def wm_n(self, ann: Announcer) -> None: self._step(ann, 0, -1)
    def wm_ne(self, ann: Announcer) -> None: self._step(ann, 1, -1)
    def wm_w(self, ann: Announcer) -> None: self._step(ann, -1, 0)
    def wm_e(self, ann: Announcer) -> None: self._step(ann, 1, 0)
    def wm_sw(self, ann: Announcer) -> None: self._step(ann, -1, 1)
    def wm_s(self, ann: Announcer) -> None: self._step(ann, 0, 1)
    def wm_se(self, ann: Announcer) -> None: self._step(ann, 1, 1)

    def wm_snap(self, ann: Announcer) -> None:
        """Numpad 5: the cursor comes back to you."""
        if self.proc is None or not self.cursor.snap(self.proc):
            return
        said = self.cursor.say_step(self.proc)
        if said:
            ann.answer(said)

    # -- the scanner ---------------------------------------------------------

    def wm_scan_next(self, ann: Announcer) -> None:
        self._scan(ann, 1)

    def wm_scan_prev(self, ann: Announcer) -> None:
        self._scan(ann, -1)

    def _scan(self, ann: Announcer, delta: int) -> None:
        if self.proc is None:
            return
        said = self.cursor.scan(self.proc, delta)
        if said:
            ann.answer(said)

    def wm_town(self, ann: Announcer) -> None:
        """T was pressed. Explain it only when the engine is going to ignore it.

        The key is not sent from here -- it is the engine's own and it already
        works, so pressing it again would open the town view twice. What this
        adds is the sentence the engine does not say when it declines.
        """
        if self.proc is None:
            return
        why = worldtravel.town_key_explanation(self.proc)
        if why:
            ann.answer(why)

    def wm_scan_jump(self, ann: Announcer) -> None:
        """Slash: put the cursor on the place being read out."""
        if self.proc is None:
            return
        complaint = self.cursor.scan_jump(self.proc)
        if complaint:
            ann.answer(complaint)
            return
        said = self.cursor.say_step(self.proc)
        if said:
            ann.answer(said)

    # -- the three readout keys ----------------------------------------------

    def repeat(self, ann: Announcer) -> None:
        said = self.cursor.repeat()
        ann.answer(said if said else tr("app.nothing_read_yet_press_numpad_5", "Nothing read yet. Press numpad 5."))

    def describe(self, ann: Announcer) -> None:
        if self.proc is None:
            return
        said = self.cursor.say_full(self.proc)
        ann.answer(said if said else tr("app.nothing_to_describe", "Nothing to describe."))

    def summary(self, ann: Announcer) -> None:
        """Where you are, what the day is, and whether you are going anywhere.

        The date and time are on this screen for a sighted player -- the panel
        down the right prints both -- so they belong here rather than being
        something only the Pip-Boy will say.
        """
        if self.proc is None:
            return
        parts = [self._where()]
        clock = pipboy.clock(self.proc)
        if clock is not None:
            parts.append(clock.say())
        if worldmap.travelling(self.proc):
            parts.append(self._journey())
        ann.answer(" ".join(p for p in parts if p))

    def _journey(self) -> str:
        """How far there is left to go, in the cursor's own units."""
        if self.proc is None:
            return ""
        dest = worldmap.destination(self.proc)
        here = worldmap.player(self.proc)
        if dest is None or here is None:
            return ""
        dx = dest[0] // worldmap.SUBTILE - here[0] // worldmap.SUBTILE
        dy = dest[1] // worldmap.SUBTILE - here[1] // worldmap.SUBTILE
        name = self._area_name_at(dest)
        left = worldcursor.steps_away(dx, dy)
        if left == 1:
            away = tr("worldmap.one_square", "1 square")
        else:
            away = tr("worldmap.squares", "{count} squares", count=left)
        if name:
            return tr("travel.to_away", "Travelling to {place}, {distance} away.",
                      place=name, distance=away)
        return tr("travel.away", "Travelling, {distance} away.", distance=away)

    def _area_name_at(self, world: Tuple[int, int]) -> str:
        for area in worldmap.areas(self.proc):
            if area.on_map and (area.x, area.y) == world:
                return area.name
        return ""

    # -- setting off ---------------------------------------------------------

    def travel(self, ann: Announcer) -> None:
        """Numpad plus: go to the square the cursor is on.

        Three cases, and only the last of them involves the pointer.

        The cursor on your own square means "go into this place", which is what
        clicking your own marker does in the engine -- so that is what it does
        here, through the engine's own T rather than through a click.

        The cursor on a place you know goes through the list of places down the
        right of the panel, whose buttons never move and whose destination comes
        back as that place's exact coordinates.

        Anywhere else is a click on the map, scrolled into view first.
        """
        if self.proc is None or self.hwnd is None:
            ann.answer(tr("app.not_attached_to_the_game", "Not attached to the game."))
            return
        if not self.cursor.ensure(self.proc):
            ann.answer(tr("app.cannot_read_the_world_map", "Cannot read the world map."))
            return
        if worldmap.travelling(self.proc):
            ann.answer(tr("app.already_travelling", "Already travelling."))
            return

        sx, sy = self.cursor.x, self.cursor.y
        here = worldmap.player_subtile(self.proc)
        if here == (sx, sy):
            ok, said = worldtravel.enter_here(
                self.proc, self.hwnd, self.log_path)
            if said:
                ann.answer(said)
            elif not ok:
                ann.answer(tr("app.nothing_to_go_into_here", "Nothing to go into here."))
            # Either way the view may have been centred to reach the marker,
            # so take a fresh note of it rather than announcing a scroll the
            # player did not ask for.
            self._scroll = worldmap.scroll(self.proc)
            return

        area = worldmap.area_at(self.proc, sx, sy)
        if area is not None:
            ok, said = worldtravel.travel_to_area(
                self.proc, self.hwnd, area, self.log_path)
            if ok:
                self._begin(ann, said)
                return
            if said:
                ann.answer(said)
                return
            # Not in the engine's list. Fall through to the map click.

        centre = (sx * worldmap.SUBTILE + worldmap.SUBTILE // 2,
                  sy * worldmap.SUBTILE + worldmap.SUBTILE // 2)
        ok, said = worldtravel.travel_to_point(
            self.proc, self.hwnd, centre[0], centre[1], self.log_path)
        if not ok:
            ann.answer(said or tr("app.that_did_not_work", "That did not work."))
            return
        if not said:
            reading = self.cursor.read(self.proc)
            said = tr("travel.travelling", "Travelling. {where}",
                      where=reading.step() if reading else "").strip()
        self._begin(ann, said)

    def _begin(self, ann: Announcer, said: str) -> None:
        """Note that a journey started, so `poll` does not announce it twice."""
        self._travelling = True
        self._dest = worldmap.destination(self.proc)
        self._spoke_at = time.time()
        ann.answer(said)

    # -- watching ------------------------------------------------------------

    def poll(self, ann: Announcer) -> None:
        if self.proc is None:
            return
        self._watch_town_view(ann)
        self._watch_scroll(ann)
        self._watch_travel(ann)

    def _watch_town_view(self, ann: Announcer) -> None:
        """Read the town picture out when it opens.

        There is no game mode for this -- the engine stays in WORLDMAP -- so it
        is recognised by the buttons it creates, one per entrance, with codes
        from 0x31. Those codes are below 256, which in GNW means they are
        keyboard codes: entrance one answers to the "1" key, entrance two to
        "2", and so on. So this panel needs no pointer at all, exactly like the
        conversation screen, and all the mod has to do is say what is on it.
        """
        showing = self._town_entrances()
        if showing is None:
            if self._town is not None:
                self._town = None
                ann.say(tr("app.back_to_the_world_map", "Back to the world map."), interrupt=True, force=True)
            return
        area, ways = showing
        if self._town == area.index:
            return
        self._town = area.index
        listed = ", ".join(
            "{} {}".format(e.key, e.name) for e in ways if e.key and e.name)
        ann.say(tr("worldmap.town_map", "{place} map. {entrances}. Escape to go back.",
                   place=area.name, entrances=listed),
                interrupt=True, force=True)

    def _town_entrances(self):
        """The town view's area and its offered ways in, or None if it is shut."""
        win = worldtravel.panel(self.proc)
        if win is None:
            return None
        index = worldmap.current_area(self.proc)
        if index is None:
            return None
        table = worldmap.areas(self.proc)
        if not 0 <= index < len(table):
            return None
        area = table[index]
        ways = area.ways_in
        if not ways:
            return None
        # The view is open only while the engine has built a button for the
        # first entrance. Asked of the window rather than remembered, because
        # the player can leave this panel with Escape and the mod never sees it.
        if win.by_code(worldmap.ENTRANCE_KEY_BASE + ways[0].index) is None:
            return None
        return area, ways

    def _watch_scroll(self, ann: Announcer) -> None:
        """Say where the view went when the engine's own keys move it.

        The arrow keys and Home scroll the map, and the mod does not bind any of
        them -- they are the engine's and they work. What was missing is that
        scrolling is a purely visual act, so a player who cannot see the map got
        no answer at all. Noticing the offset moved covers every cause at once:
        the arrow keys, Home, and the view being dragged along by a journey.
        """
        now = worldmap.scroll(self.proc)
        if now is None:
            return
        was, self._scroll = self._scroll, now
        if was is None or worldmap.travelling(self.proc):
            return
        dx, dy = now[0] - was[0], now[1] - was[1]
        if max(abs(dx), abs(dy)) < self.SCROLL_NOTICE:
            return
        ann.say(tr("worldmap.view", "View {where}.", where=self._view_says(now, dx, dy)),
                interrupt=True, force=True)

    def _view_says(self, offset: Tuple[int, int], dx: int, dy: int) -> str:
        """Which way the view moved, and what is in the middle of it now."""
        way = worldcursor.bearing(dx, dy)
        middle = ((offset[0] + worldmap.VIEW_W // 2) // worldmap.SUBTILE,
                  (offset[1] + worldmap.VIEW_H // 2) // worldmap.SUBTILE)
        area = worldmap.area_at(self.proc, middle[0], middle[1])
        if area is not None:
            return tr("worldmap.centred_on", "{direction}, centred on {place}",
                      direction=way, place=area.name).lstrip(", ")
        here = worldmap.player_subtile(self.proc)
        if here is not None:
            gap = worldcursor.steps_away(middle[0] - here[0], middle[1] - here[1])
            if gap == 0:
                if way:
                    return tr("worldmap.centred_on_you_way", "{direction}, centred on you",
                              direction=way)
                return tr("worldmap.centred_on_you", "centred on you")
            return tr("worldmap.from_you", "{direction}, {count} squares from you",
                      direction=way, count=gap).lstrip(", ")
        return way

    def _watch_travel(self, ann: Announcer) -> None:
        """Set off, keep going, and stop -- reported from the engine's state.

        The end of a journey is the part worth getting right. It has two very
        different causes: you arrived, or something interrupted you. The engine
        does not distinguish them in one flag, but it does not need to -- if the
        destination is reached the journey finished, and if the flag drops while
        the player is nowhere near it, something stopped them. Saying which is
        the difference between "you are at Klamath" and "you have stopped, and
        you are not where you were going", and a player who cannot see the map
        has no other way to find out.
        """
        travelling = worldmap.travelling(self.proc)
        dest = worldmap.destination(self.proc)

        if travelling and not self._travelling:
            self._travelling = True
            self._dest = dest
            self._spoke_at = time.time()
            return

        if travelling:
            self._dest = dest or self._dest
            if time.time() - self._spoke_at >= self.PROGRESS_SECONDS:
                self._spoke_at = time.time()
                said = self._journey()
                if said:
                    ann.say(said, interrupt=False, force=True)
            return

        if self._travelling:
            self._travelling = False
            ann.say(self._stopped(), interrupt=True, force=True)
            self._dest = None
            self.cursor.snap(self.proc)

        # Arriving at a place is worth saying even when nothing was travelling
        # -- walking out of a location puts you on its marker.
        area = worldmap.current_area(self.proc)
        if area != self._area:
            self._area = area
            if area is not None:
                table = worldmap.areas(self.proc)
                if 0 <= area < len(table):
                    ann.say(tr("worldmap.at_town", "At {place}. Press T for its map.",
                               place=table[area].name),
                            interrupt=False, force=True)

    def _stopped(self) -> str:
        here = worldmap.player(self.proc)
        want = self._dest
        if here is None:
            return tr("app.stopped", "Stopped.")
        name = self._area_name_at(here) or self._area_name_at(want or here)
        if want is not None:
            gap = max(abs(want[0] - here[0]), abs(want[1] - here[1]))
            # The engine stops the marker when it is within three pixels of the
            # destination -- its own test, at 0x004C0688 -- so anything inside
            # that arrived, and anything outside it was interrupted.
            if gap > 3:
                left = worldcursor.steps_away(
                    (want[0] - here[0]) // worldmap.SUBTILE,
                    (want[1] - here[1]) // worldmap.SUBTILE)
                return tr("travel.stopped_short", "Stopped short, {count} squares from "
                          "where you were going.", count=left)
        return tr("travel.arrived_at", "Arrived at {place}.", place=name) if name else tr("app.arrived", "Arrived.")


class App:
    def __init__(self, speaker: Optional[Speaker] = None, require_focus: bool = True,
                 step_sound: bool = True) -> None:
        self.ann = Announcer(speaker or get_speaker())
        self.require_focus = require_focus
        self.ticker = sound.Ticker(enabled=step_sound)
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
        # Set when a move ended with the "How many?" window on screen, so the
        # key that asks the script for the new totals still has to be sent once
        # that window has gone. It cannot be sent while it is up: that window
        # reads numpad 0 as the digit zero -- see `_ask_totals`.
        self._owed_totals: bool = False
        # The item marked by the first press: (name, side, index, total).
        # Nothing has been sent to the game while this is set -- it is the mod's
        # own note of what the player chose, not a state the game is in.
        self._holding: Optional[tuple] = None
        # The last fault spoken, so a fault that recurs every tick is reported
        # to the console each time but announced only once.
        self._last_fault: Optional[str] = None
        # What address resolution found, from the last connect. Held so the
        # greeting can say what is missing without resolving a second time.
        self._offsets = None

    def connect(self) -> bool:
        try:
            self.proc = Process.attach(FALLOUT_EXE_NAMES)
        except (ProcessNotFound, OSError):
            self.proc = None
            return False
        # **Not before the game has a window.** Started by the launcher, the mod
        # found the process in its first instant, before the game had opened
        # its window -- so it had no window to call the game's, decided the
        # game was never in front, and stayed silent for the whole session
        # while saying it was connected. Wait for the window, then connect. A
        # window that never comes (some broken full-screen setup) still gets a
        # connection after WINDOW_WAIT_SECONDS, and the complaint below.
        if find_game_window(self.proc.pid) is None:
            pid = self.proc.pid
            since = getattr(self, "_windowless", None)
            if since is None or since[0] != pid:
                since = self._windowless = (pid, time.time())
            if time.time() - since[1] < WINDOW_WAIT_SECONDS:
                self.proc.close()
                self.proc = None
                return False
        else:
            # Waited for and found. Forgotten, so a game that is closing --
            # still listed, its window already gone -- is waited on afresh
            # rather than connected to as if its wait had run out.
            self._windowless = None
        # Find the engine's globals before anything reads one. On the build the
        # mod was measured against this recognises the executable by hash and
        # changes nothing; on any other it locates them by signature, and says
        # by name what it could not find rather than reading a plausible number
        # out of the wrong place.
        #
        # Said out loud when something is missing, not merely printed. The
        # console is not somewhere a blind player can look, and the symptom of
        # an unresolved address is a screen that goes quiet -- which reads as
        # the whole mod being broken rather than as one thing being unavailable.
        # Once per connect, never per tick: a fault that recurs every poll must
        # not become a stutter.
        try:
            self._offsets = resolve.bind(self.proc)
        except Exception as exc:  # never let address resolution stop the mod
            self._offsets = None
            print("[offsets] resolution failed: {}".format(exc), flush=True)
        self.hwnd = find_game_window(self.proc.pid)
        # Full screen breaks every click the mod makes, and it breaks it
        # silently: DirectX parks the game's real window off screen behind its
        # own, so aims are computed against a window at -25600 and simply grind
        # until they give up. Say so, out loud and once, for the same reason an
        # unresolved address is said out loud -- the symptom is indistinguishable
        # from the mod being slow, and that is exactly how it got reported.
        self._window_complaint = fullscreen_complaint(self.hwnd, self.proc.pid)
        if self._window_complaint:
            print("[app] {}".format(self._window_complaint), flush=True)
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
        # Everything the game said, for Shift with comma and period.
        self.history = history.History()
        self.world = WorldWatcher(WorldLog(log_path), self.saves, self.proc,
                                  ticker=self.ticker)
        self.world.engine_actions = _unsafe_scripting(game_dir)
        self.world.history = self.history
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
            screens.QUANTITY: QuantityWatcher(
                quantity.Quantity(self.proc, self.hwnd),
                self.world.inventory),
            screens.SLOTS: SlotScreenWatcher(self.slots, self.saves, pager),
            screens.PIPBOY: PipboyWatcher(
                pipboy.Pipboy(self.proc, self.hwnd)),
            screens.PAUSE: PauseWatcher(self.proc),
            screens.PREFS: PrefsWatcher(prefs.Prefs(self.proc)),
            screens.CALLED_SHOT: CalledShotWatcher(
                calledshot.CalledShot(self.proc, self.hwnd, self.world.combat,
                                      log_path)),
            screens.MAIN_MENU: MainMenuWatcher(),
            screens.SELECT: SelectWatcher(PremadeScreen(self.proc)),
            screens.CHARGEN: CharGenWatcher(CharGen(self.proc), self.world.log),
            screens.WORLD: self.world,
            # The world map reads the game for itself, so unlike every other
            # in-game watcher it is handed the process rather than the log.
            screens.WORLDMAP: WorldMapWatcher(self.proc, self.hwnd, log_path,
                                              ticker=self.ticker),
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
            # Never click in a conversation. There is nothing here worth
            # pointing at -- the replies are chosen by their numbers -- and a
            # click would land wherever the pointer happens to have been left,
            # which means picking a reply at random and saying it to somebody.
            # Of all the misplaced clicks this mod guards against, this is the
            # only one that cannot be walked back.
            if self.world.talking():
                self.ann.answer(dialogue.hint_text())
                return
            if not screens.is_map_mode(mode):
                # Something is over the map, so there is no hex to aim at:
                # click nothing. This used to click wherever the pointer had
                # been left, on whatever panel was up; the mouse buttons are
                # the map's, and a panel has its own keys (F1).
                #
                # And say nothing. It used to explain the mouse keys every
                # time, which on the inventory -- where + is an easy key to
                # reach for -- was a lecture on every press (owner, 0.2.36).
                return

            if button == "left":
                if self.aimer is None:
                    return
                ok, reading, why = self.aimer.aim()
                if not ok and reading is not None and reading.pinned():
                    # The hex is beyond the edge of the view, not merely hard
                    # to land on. Walk the part of the way that is on screen:
                    # the view follows you, so the next press can reach it.
                    # Never in a fight, where a walk nobody chose costs action
                    # points, and never with a skill armed, which is not a walk.
                    armed = self.world.log.cursor_mode
                    walking = (mode is not None
                               and not mode & screens.MODE_COMBAT
                               and armed not in screens.SKILL_CURSORS
                               and armed != screens.CURSOR_USE_ITEM)
                    if walking and self.aimer.walk_toward() is not None:
                        time.sleep(CURSOR_SETTLE)
                        guarded_click(self.hwnd, button)
                        self.ann.answer(tr("app.that_hex_is_out_of_view_walking_towards_it_press_again_when_", "That hex is out of view. Walking "
                                        "towards it; press again when you stop."))
                        return
                    self.ann.answer(tr("app.that_hex_is_out_of_view", "That hex is out of view."))
                    return
                if not ok:
                    self.ann.answer(
                        tr("aim.cannot", "Cannot aim at that hex: {why}.",
                           why=why or tr("aim.unknown_reason", "unknown reason"))
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
                    self.ann.answer(tr("app.that_hex_is_blocked", "That hex is blocked."))
                    return
                # Is there anything on this hex a click could be aimed at?
                #
                # Asked of `names()` rather than of the raw string. The old test
                # compared the whole readout against "empty" and "you", which
                # worked only while those were the entire line -- and the moment
                # your own hex started reporting which way you are facing, "you,
                # facing north east" was neither of them, so the click set off
                # hunting for an object called "you" that the engine will never
                # confirm a pointer is over.
                #
                # `names()` already knows every word the mod appends and every
                # word it says instead of a name, because the same question is
                # asked of it three lines further down. One list, in one place.
                expects_object = bool(last and last.names())
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
                # Everything the readout named, not just the first of them --
                # see HexReading.names(). Naming only the first is what made
                # every door in the game unclickable.
                wanted = last.names() if (expects_object and last) else None
                # **Using something on yourself, which was aiming at the
                # floor.**
                #
                # Your own hex reports "you", and "you" is one of the words that
                # means the hex holds nothing to point at -- deliberately, since
                # every other click wants the ground you are standing on rather
                # than your own body. So the aim settled dead centre on the hex,
                # which is where your FEET are, and Fallout picks what a click
                # hits by the sprite drawn over that pixel. Measured live with
                # Healing Powder armed and the cursor snapped to the player: the
                # engine reported "Wooden Wall" at the hex centre and "Tara"
                # fifty-six pixels higher up.
                #
                # So when a click is going to act on something -- an item armed
                # by the reload key, or a skill armed from the Skilldex -- and
                # the cursor is on you, then YOU are the thing to point at, and
                # the aimer already knows how to walk up a sprite until the
                # engine agrees. It could not do it here before, for the plain
                # reason that the script asked the engine to ignore the player.
                myself = worldlog.aim_at_yourself(
                    last, self.world.log.cursor_mode,
                    self.world.log.player_name)
                if myself:
                    expects_object, wanted = True, myself
                name, _at = self.aimer.prepare(expects_object, wanted=wanted)
                # Every hunt goes in the log, hit or miss. A miss used to leave
                # only the game's probe lines behind, which say where the
                # pointer went but not what the player was reaching for.
                if expects_object:
                    outcome = repr(name) if name else "missed"
                else:
                    outcome = "no clear spot" if name is False else "clear"
                print("[click] hex {} wanted {}: {}{}".format(
                    reading.look if reading else "?", wanted or "ground",
                    outcome,
                    " (covered by {})".format(self.aimer.blocked_by)
                    if self.aimer.blocked_by else ""), flush=True)
                if (expects_object and not name and not self.aimer.blocked_by
                        and getattr(self.aimer, "bare", False) and not myself
                        and self.world.log.cursor_mode not in screens.SKILL_CURSORS
                        and self.world.log.cursor_mode != screens.CURSOR_USE_ITEM):
                    # **Nothing there to point at, so the click is a walk.** The
                    # readout names ground decoration -- Dirt, Weeds -- that the
                    # engine will not pick, and with nothing in the way a
                    # sighted player clicking that hex walks onto it. Refusing
                    # with "cannot point at Dirt" was refusing a walk.
                    ground, _at = self.aimer.prepare(False)
                    print("[click] hex {}: {} cannot be picked, walking "
                          "instead: {}".format(reading.look if reading else "?",
                                               wanted, ground), flush=True)
                    if ground is not False:
                        time.sleep(CURSOR_SETTLE)
                        guarded_click(self.hwnd, button)
                        return
                if expects_object and not name:
                    blocker = self.aimer.blocked_by
                    # Name what was being reached FOR. A hex holding a Wall and
                    # a Locker, with another wall drawn over both, is about the
                    # locker; "cannot point at Wall; Wall is drawn over it"
                    # is true and says nothing.
                    hidden = [w for w in (wanted or ())
                              if not (blocker and worldlog.names_match(blocker, [w]))]
                    what = (hidden or wanted or [tr("use.that", "that")])[0]
                    if blocker:
                        said = tr("aim.covered", "Cannot point at {thing}; {blocker} is "
                                  "drawn over it.", thing=what, blocker=blocker)
                        if getattr(self.world, "engine_actions", False):
                            said += " " + tr("aim.menu_reaches",
                                             "Its action menu can still reach it.")
                        self.ann.answer(said)
                    else:
                        self.ann.answer(tr("aim.cannot_point", "Cannot point at {thing}.",
                                           thing=what))
                    return
                if not expects_object and name is False:
                    # Every part of the hex is underneath something else's
                    # sprite, so a click would act on that instead of walking.
                    # Name it: "behind Wall" is something a player can act on,
                    # "behind something" is a shrug.
                    self.ann.answer(tr("aim.behind", "That hex is behind {thing}.",
                                       thing=self.aimer.blocked_by
                                       or tr("route.something", "something")))
                    return
                time.sleep(CURSOR_SETTLE)
            guarded_click(self.hwnd, button)
        except FocusLost:
            self.ann.answer(tr("app.game_is_not_focused", "Game is not focused."))
        except Exception as exc:  # never let a hotkey kill the loop
            print("[app] click: {}".format(exc), flush=True)

    def say_reply(self) -> None:
        """Say the reply the list cursor is on, by pressing its number.

        Note what is NOT here. No aim, no cursor mode, no asking the engine
        what the pointer is over, no refusal to act on a maybe -- the whole
        apparatus every other click in this mod needs. Fallout binds the
        replies to the number keys itself, and the engine says so in its own
        button table: each reply's button carries the release code 49 + index,
        which is the key '1' upward. So this presses a key, and the engine does
        exactly what it does for a sighted player pressing the same one.

        It is the only action in the mod that cannot land on the wrong thing.
        """
        reading = self.world.read_dialogue()
        if reading is None or not reading.options:
            self.ann.answer(tr("app.no_replies_offered", "No replies offered."))
            return
        index = max(0, min(self.world.dlg_index, len(reading.options) - 1))
        if index >= 9:
            # Only 1 to 9 are bound. A tenth reply exists in the array and can
            # be read out, but saying it would mean clicking on it, and that is
            # not built. Say so plainly rather than pressing something else.
            self.ann.answer(tr("app.the_mod_cannot_say_replies_past_the_ninth_yet", "The mod cannot say replies past the ninth yet."))
            return
        text = reading.options[index]
        # Said before the key goes down, because this is the one confirmation
        # the player gets that they said what they meant to. The NPC's answer
        # follows on its own, off the memory poll.
        self.ann.answer(tr("dialogue.saying", "Saying: {reply}",
                           reply=text or tr("dialogue.reply_number", "reply {number}",
                                            number=index + 1)))
        guarded_tap(self.hwnd, str(index + 1), settle=0.2)

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
            self.ann.answer(tr("app.nothing_selected", "Nothing selected."))
            return
        if self.world.finder is None:
            self.ann.answer(tr("app.not_attached_to_the_game", "Not attached to the game."))
            return
        # First press marks the item. Nothing is sent to the game at all: the
        # move is a drag, and a drag begun on one keypress and finished on
        # another would leave the game holding an item across however long the
        # player takes to navigate -- a state they cannot see and the mod cannot
        # reliably detect. So the whole drag happens on the second press.
        if self._holding is None:
            if not inv.selected:
                self.ann.answer(tr("app.no_item_selected", "No item selected."))
                return
            self._holding = (inv.selected, inv.side, inv.index, inv.total,
                             inv.selected_count)
            self.ann.answer(
                tr("move.picked_up", "{item}. Choose where to put it and press "
                   "Enter again.", item=inv.selected)
            )
            return

        name, side, index, total, count = self._holding
        before = inv.counts
        # The count goes with the item, not with the cursor: by now the cursor
        # is on the destination, and that is what the "Move Items" window used
        # to be sized from.
        inv.start_moving(count)
        # Say so before starting. The drag aims twice and each aim asks the
        # game where the pointer is a dozen times, so this takes a few seconds
        # -- and a few seconds of silence after a keypress reads exactly like
        # the key never arrived, which is the misreading this whole project
        # keeps having to design against.
        self.ann.answer(tr("move.moving", "Moving {item}.", item=name))
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
            self.ann.answer(tr("app.game_is_not_focused", "Game is not focused."))
            return

        self._holding = None
        self._moved = (name, before, time.time() + 1.5)
        self._ask_totals()

    def _ask_totals(self) -> None:
        """Ask the script for both lists' counts, once it is safe to ask.

        The TOTALS, not the selected item. An item equipped from the carried
        list changes the carried count and nothing at all about the slot it went
        into, so re-reading the selection -- which is what this used to do --
        reported every successful equip as a failure. Its reply arrives through
        the log on a later tick.

        **Never while the "Move Items" window is up, and that is not a nicety.**
        Dragging a stack is exactly what puts that window up, so this ran into
        it every time a shop was involved. It is a modal loop of the engine's
        own and it reads the keyboard itself: numpad 0 is the digit zero to it,
        and gl_inven.ssl stands down while it is showing, so the key was not
        even swallowed on the way past. The mod answered "how many?" with
        "none" before the player had touched anything, the window sat on a
        count the engine will not accept, and Enter answered with the error
        sound -- the one at 0x0047692A, which is the only thing in the game
        that plays `iisxxxx1`.
        """
        if self.hwnd is None:
            return
        # Asked of the live window list rather than of `self.screen`: the drag
        # takes seconds and the window opens in the middle of it, so the mod's
        # idea of which screen is up is from before the question was asked.
        if self.proc is not None and quantity.showing(self.proc):
            self._owed_totals = True
            return
        self._owed_totals = False
        try:
            guarded_tap(self.hwnd, "numpad0", settle=0.25)
        except Exception:
            pass

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
        # **Not while the game is still asking how many.** Moving a stack puts
        # the "Move Items" window up and nothing has moved yet -- the player is
        # part way through deciding. Judging here would call every stack a
        # failure a second after the question appeared, and say so over the top
        # of the question.
        if self.screen == screens.QUANTITY:
            self._moved = (name, before, time.time() + 1.5)
            return
        # The window has gone, so the question the drag could not ask can be
        # asked now. Without this the totals never arrive and every stack moved
        # in a shop is reported as one that did not move.
        if self._owed_totals:
            self._ask_totals()
            self._moved = (name, before, time.time() + 1.5)
            return
        # Compare the whole reading, not just the count. Dropping something into
        # an equipment slot changes no list length anywhere -- the slot's
        # contents change -- so a count test called every successful equip a
        # failure and told the player they were still holding it.
        if inv.counts is not None and inv.counts != before:
            self._moved = None
            self.ann.answer(tr("move.moved", "Moved {item}.", item=name))
        elif time.time() > deadline:
            self._moved = None
            # The drag ran and the reading did not change. Say so plainly. The
            # earlier version guessed "you must be holding it" here, which was
            # a story invented to explain silence -- and it was wrong, because
            # what silence actually meant was that the clicks did nothing.
            self.ann.answer(tr("move.not_moved", "{item} did not move.", item=name))

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
        if what == "back_tab" and self.screen == screens.CHARGEN:
            # Hush the editor now, from this thread, before the next poll can
            # announce the step the game takes on its own.
            watcher = self.current_watcher()
            if watcher is not None:
                watcher.quiet_until = time.time() + 2.0
        self._pending.append((what, time.time()))

    def _run_item_action(self) -> None:
        """Carry out an item-menu choice, off the log-parsing path.

        Done here rather than where the line is read because these actions take
        seconds and drive the pointer, and doing that in the middle of parsing a
        batch of log lines would stall the rest of them behind it.
        """
        if self.world is not None and self.world.pending_move:
            self.world.pending_move = False
            self.move_item()
            return
        line = self.world.pending_item_action if self.world else None
        if not line:
            return
        self.world.pending_item_action = None
        if line == "useactive":
            # The U key, from the map: the item is already in the active hand,
            # so this is just the click that arms it. What it gets used ON is
            # the player's next choice, which is the point.
            done, why = itemactions.click_item_slot(
                self.proc, self.hwnd, log_path=self.world.log.path)
            if not done:
                self.ann.answer(why or tr("app.that_did_not_work", "That did not work."))
            return
        m = inventory._DO.match(line)
        if not m:
            return
        # Drop and look are carried out by gl_inven.ssl itself now, so an entry
        # that still arrives here is one the mod has no way to carry out.
        self.ann.answer(tr("app.the_mod_has_no_way_to_do_that_yet",
                           "The mod has no way to do that yet."))

    def _run_pending(self) -> None:
        while self._pending:
            what, queued_at = self._pending.pop(0)
            # Drop anything stale. If the game lost focus the loop stops
            # ticking, and a click that fires when focus comes back lands in a
            # context the player has long since moved on from.
            #
            # Say so when it happens. A key that is thrown away here is a key
            # the player pressed and heard nothing about, which is
            # indistinguishable from a key that never arrived -- and that
            # ambiguity is what made this cost a session to find rather than a
            # minute. It should be rare now that a screen flicker no longer
            # strands the queue; if it turns out not to be rare, this line is
            # what will say so.
            if time.time() - queued_at > 1.0:
                print("[app] dropped hotkey {!r}: {:.1f}s stale".format(
                    what, time.time() - queued_at), flush=True)
                continue
            self._do_action(what)

    # The numpad's three middle keys, and what they mean where the arrows do
    # not already mean it. Everywhere but the world map these are the same
    # three actions the arrow keys raise, which is how they behaved when the
    # hotkey table bound them straight to these names.
    _NUMPAD_AS_ARROWS = {"num8": "dlg_prev", "num2": "dlg_next",
                         "num5": "dlg_say"}
    # On the world map they are the cursor's north, south, and come-back-to-me.
    # They cannot be the arrows there: the arrow keys are the engine's own and
    # they scroll the view.
    _NUMPAD_ON_WORLDMAP = {"num8": "wm_n", "num2": "wm_s", "num5": "wm_snap"}

    # The screens whose keys are entirely the mod's table. Nothing reaches past
    # them: three are modal loops of the engine's own, where a key that got
    # through would act on the window behind, and on the other two a stray
    # mouse button would click wherever the pointer was last left.
    _TABLE_SCREENS = (screens.CALLED_SHOT, screens.QUANTITY, screens.TIMER,
                      screens.PIPBOY, screens.WORLDMAP, screens.PREFS,
                      screens.PAUSE)

    # Numpad plus or minus anywhere but the map.

    def help(self) -> None:
        """F1: the keys for the screen you are on, from its own table."""
        watcher = self.current_watcher()
        if watcher is None:
            self.ann.answer(tr("app.no_screen_recognised_so_no_keys_to_list", "No screen recognised, so no keys to list."))
            return
        self.ann.answer(controls.help_text(watcher.help_keys(),
                                           watcher.help_title()))

    def _do_action(self, what: str) -> None:
        if what == "help":
            self.help()
            return
        if what in ("log_prev", "log_next"):
            # The message log works on every screen: what was said a moment
            # ago is worth hearing again wherever you are when you want it.
            self.ann.answer(self.history.older() if what == "log_prev"
                            else self.history.newer())
            return
        if what in self._NUMPAD_AS_ARROWS:
            what = (self._NUMPAD_ON_WORLDMAP if self.screen == screens.WORLDMAP
                    else self._NUMPAD_AS_ARROWS)[what]
        if self.screen in self._TABLE_SCREENS:
            watcher = self.current_watcher()
            if watcher is None:
                return
            if self.screen == screens.QUANTITY:
                # Control with up or down moves by ten -- sixty caps is six
                # presses, not sixty. Typing the number is quicker still.
                watcher.big = 10 if getattr(self, "ctrl_held", False) else 1
            if controls.dispatch(watcher, what, self.ann):
                return
            if what in ("repeat", "summary", "describe"):
                getattr(watcher, what)(self.ann)
            return
        if what == "enter":
            # A conversation is the one place outside the table screens where
            # the mod answers Enter: gl_dialog.ssl takes the key from the
            # engine, and this types the number of the reply the list is on.
            # In an item window gl_inven.ssl takes it and says so in the log;
            # on the map the action menu is the script's own.
            if (self.screen == screens.WORLD and self.world is not None
                    and self.world.talking()):
                self.say_reply()
            return
        if what == "back_tab":
            if self.screen == screens.CHARGEN:
                watcher = self.current_watcher()
                if watcher is not None:
                    watcher.back_section(self.ann, self.hwnd)
            return
        if what in ("back", "left", "right", "home", "end"):
            # The game's own keys on every screen without a table.
            return
        # The "Move Items" window first, and FIRST is the whole point.
        #
        # Up and down arrive here under the dialogue names, because that is
        # what they are everywhere else, and the dialogue branch below answers
        # for them -- or declines to, silently, which is what it did. A stack
        # dragged onto a barter table put this window up, the mod announced it
        # and said which keys to press, and then every one of those keys went
        # to a conversation that was not the thing on screen. The arrows did
        # nothing at all, and there was no way to hear why.
        #
        # Everything falls in here while this window is up, including the keys
        # this screen has no use for. There is a modal loop of the engine's own
        # running: a key that reaches past it reaches the barter window behind
        # it, and `o` pressing OFFER through a half-answered question is not a
        # thing to leave possible.
        #
        # Enter and Escape are deliberately absent: they are the engine's own
        # keys on this window and already work, and binding them would press
        # twice.
        # The called-shot window, for the same reason as the one below: a modal
        # loop of the engine's, so nothing the mod does may reach past it.
        if what.startswith("digit"):
            # Everywhere but the "how many" window the number row is the
            # game's, and it has already had the key.
            return
        if what == "barter_offer":
            # Only where there is a barter to offer in. `o` is an ordinary
            # letter everywhere else, so this must reach nothing and say
            # nothing off this screen -- the same rule the world map's keys
            # follow.
            proc = getattr(self, "proc", None)
            hwnd = getattr(self, "hwnd", None)
            if proc is None or hwnd is None:
                return
            if not barter.offering(proc):
                return
            world = getattr(self, "world", None)
            # **A lopsided offer is asked about first.** Caps put on the table
            # while meaning to buy, with nothing asked for, went for nothing
            # the moment O was pressed. Said once; pressed again within a few
            # seconds, on the same table, it goes.
            inv = getattr(world, "inventory", None) if world is not None else None
            worry = inv.lopsided() if inv is not None else None
            if worry:
                now = time.time()
                pending = getattr(self, "_offer_confirm", None)
                if not (pending and pending[0] == inv.price and now < pending[1]):
                    self._offer_confirm = (inv.price, now + OFFER_CONFIRM_SECONDS)
                    self.ann.answer("{} {}".format(worry, tr(
                        "barter.offer_anyway", "Press O again to offer anyway.")))
                    return
            self._offer_confirm = None
            log_path = world.log.path if world is not None and hasattr(world, "log") else None
            sent, why = barter.offer(proc, hwnd, log_path=log_path)
            if not sent:
                self.ann.answer(why or tr("app.that_did_not_work", "That did not work."))
            # Nothing is said on success. What the shopkeeper did with the
            # offer arrives through the price hook a moment later, and saying
            # "offered" here as well would announce it twice -- once as an
            # intention and once as a fact.
            return
        if what.startswith("wm_"):
            # The world map's keys, and four of them are ordinary letters and
            # punctuation -- `[`, `]`, `/` and `T`. Everywhere else those are
            # things a player types, so they must reach nothing and say
            # nothing. Falling through to the generic dispatch below would
            # answer "No screen recognised" at a name field, which is both
            # wrong and loud.
            if self.screen != screens.WORLDMAP:
                return
            watcher = self.current_watcher()
            if watcher is not None:
                getattr(watcher, what, lambda _a: None)(self.ann)
            return
        # The reply-list keys are the hex cursor's keys wearing another hat.
        # In a conversation gl_dialog.ssl swallows them so the engine never
        # sees them as reply numbers; everywhere else they belong to the map,
        # and this must not answer for them there.
        if what.startswith("dlg_"):
            # Up and down are the Pip-Boy's keys too. They arrive under the
            # dialogue names because that is where they were first bound, and
            # renaming them would only move the confusion: what they are is the
            # two keys everyone already reaches for to walk a list.
            #
            # The engine does nothing with them on this panel -- it is mouse
            # only -- so nothing is being taken from anybody, and unlike the
            # conversation screen no script has to swallow them first.
            if not (self.world is not None and self.world.talking()):
                return
            if what == "dlg_prev":
                self.world.dlg_step(self.ann, -1)
            elif what == "dlg_next":
                self.world.dlg_step(self.ann, 1)
            elif what == "dlg_say":
                self.world.dlg_say(self.ann)
            return
        if what in ("click", "rclick") and self.screen == screens.CHARGEN:
            # The game's own keys here: plus and minus spend and take back
            # points, and the engine gets the key whatever the mod does. Going
            # on to `click()` sent a REAL left click to wherever the pointer
            # was left, once per point, and said "Character screen." each time
            # -- on top of the point being announced, so that was cut off.
            return
        if what in ("click", "rclick") and self.screen == screens.SLOTS:
            # **Nothing at all.** This screen is the game's own keyboard from
            # end to end -- up and down move the highlight, left and right turn
            # the page, Enter commits, Escape backs out -- and the mod has no
            # business adding a key to it.
            #
            # What was here has been wrong twice. First it drove the page arrows
            # with the pointer, on the belief that sfall offered the pages to
            # the mouse alone; the arrow keys had been turning them all along.
            # Then it spoke a reminder of what to press instead, which is still
            # a binding, still something to press by accident, and still a
            # sentence nobody asked for.
            #
            # The `return` is the whole point and must stay: without it these
            # fall through to the click below, which sends a real click at
            # wherever the pointer was last left -- on the screen that
            # overwrites saved games.
            return
        if what in ("click", "rclick"):
            self.click("left" if what == "click" else "right")
            return
        watcher = self.current_watcher()
        if watcher is None:
            self.ann.answer(tr("app.no_screen_recognised", "No screen recognised."))
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
                # What was said before belongs to a game that no longer
                # exists; reading it back would describe the wrong world.
                self.history.clear()
                self.ann.answer(tr("app.game_loaded", "Game loaded."))

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
            # Into the log as well as the speech. The game's debug.log does not
            # carry these and the mod's log did not either, so "it never said
            # his hit points" could not be checked against anything: whether
            # the engine wrote the line and the mod lost it, or the engine never
            # wrote it, looked the same afterwards.
            print("[display] {}".format(line), flush=True)
            self.history.add(line)
            self.ann.say(line, force=True)

    def _ticks_to_believe(self, detected: str) -> int:
        """How long a reading must hold before the mod acts on it.

        One transition needs more than the usual four polls, and it is the one
        where the flags are not lying: leaving the character editor really does
        read as character selection, because the two screens set the same three
        flags and DONE and CANCEL both close the same window. Only what happens
        afterwards separates them, so this one waits for it.
        """
        if self.screen == screens.CHARGEN and detected == screens.SELECT:
            return SELECT_AFTER_EDITOR_TICKS
        if self.screen == screens.MAIN_MENU and detected == screens.CHARGEN:
            return EDITOR_FROM_MENU_TICKS
        return SCREEN_STABLE_TICKS

    def _watch_box(self) -> None:
        """The engine's question box, put up over the map.

        **Control and X asked "are you sure you want to quit?" in silence.**
        The pause menu already noticed this box when Exit raised it; over the
        map nothing was looking. It is the engine's general dialog (0x0041CF20)
        and its words are drawn into the window, not kept anywhere, so it is
        noticed by shape -- the same shape the save screen's boxes have -- and
        named by the key that opened it. Any other box is said to be a
        question, which is true, rather than guessed at.
        """
        if self.screen not in (screens.WORLD, screens.UNKNOWN) or self.proc is None:
            self._box = None
            return
        world = self.world
        if world.talking() or world.inventory.open:
            self._box = None
            return
        try:
            box = slotscreen.confirm_box(self.proc)
        except Exception:
            box = None
        seen = (box.addr, box.width, box.height, len(box.buttons)) if box else None
        if seen == getattr(self, "_box", None):
            return
        self._box = seen
        if box is None:
            return
        if len(box.buttons) < 2:
            self.ann.answer(tr("app.the_game_is_showing_a_message_that_cannot_be_read_press_ente",
                               "The game is showing a message that cannot be read. "
                               "Press Enter to dismiss it."))
            return
        yes_no = tr("pausemenu.yes_no", "Y or Enter for yes, N or Escape for no.")
        if time.time() - getattr(self, "quit_key_at", 0.0) < QUIT_KEY_SECONDS:
            self.ann.answer("{} {}".format(pausemenu.quit_question(self.proc), yes_no))
            return
        self.ann.answer("{} {}".format(
            tr("app.question_box", "The game is asking a question the mod cannot read."),
            yes_no))

    def tick(self) -> None:
        if not self.proc:
            return
        # Always pump the script log first: it is the only thing that can tell
        # us a game session is live, and memory alone mistakes the map for the
        # premade-character screen.
        # **Each stage is timed, and a slow tick says which stage.** Typed
        # amounts in the "how many" window were all thrown away as stale: the
        # loop was taking over a second a turn there, and a queued key only
        # lives for one. Nothing said where the second went.
        marks = [("start", time.time())]
        self.world.pump()
        marks.append(("script log", time.time()))
        self._settle_move()
        marks.append(("settle move", time.time()))
        self.pump_display()
        marks.append(("display", time.time()))
        # A save is always worth hearing, whatever screen the mod thinks is up.
        # It is also the one announcement that must never be dropped: acting on
        # a save that did not happen is how an evening's play is lost.
        for line in self.saves.poll():
            self.ann.say(line, force=True)
        marks.append(("saves", time.time()))
        # The script's mode says whether this is Save or Load; before a game
        # loads there is no script, and the only way here is Load.
        self.slots.mode = self.world.log.game_mode if self.world.log.session_live else None
        detected = screens.detect(self.proc,
                                  in_game=self.world.log.session_live,
                                  mode=self.world.log.game_mode)
        marks.append(("detect", time.time()))
        self._slow_tick(marks)

        if detected != self.screen:
            # Debounce: only believe a new screen once it has held steady.
            if detected == self._pending_screen:
                self._pending_ticks += 1
            else:
                self._pending_screen = detected
                self._pending_ticks = 1
            if self._pending_ticks >= self._ticks_to_believe(detected):
                # It held. Commit it and do nothing else this tick: the watcher
                # is being swapped out from under everything below.
                self.screen = detected
                self._pending_ticks = 0
                print("[app] screen: {}".format(detected), flush=True)
                watcher = self.current_watcher()
                if watcher:
                    watcher.reset()
                    watcher.enter(self.ann)
                return
            # A flicker that has not held is not a transition yet, so fall
            # through to the hotkeys below -- but without polling the watcher.
            # `self.screen` has not moved, so the watcher a queued key would
            # run against is exactly the one that was valid last tick.
            #
            # **Returning here is what made numpad dot unreliable.** The two
            # screen flags are not written atomically -- see the note on
            # SCREEN_STABLE_TICKS -- so two readings can alternate, and while
            # they do, `_pending_ticks` is reset to 1 every single tick and
            # never reaches four. This returned on every one of them,
            # `_run_pending` was never reached, and the queued press sat in the
            # list until the one-second staleness check below threw it away
            # without a sound.
            #
            # It failed intermittently because it depended on whether the game
            # happened to be mid-flicker at the instant the key was pressed,
            # which is not something a player can see or predict. Pressing `m`
            # by hand never failed once, because that goes straight to the
            # engine and touches none of this -- which is precisely the
            # evidence that located it.
        else:
            self._pending_screen = detected
            self._pending_ticks = 0
            watcher = self.current_watcher()
            if watcher:
                watcher.poll(self.ann)
            self._watch_box()

        # Hotkeys last: an aimed click sends its own keystrokes and reads the
        # same log, so it must not run half way through a screen transition.
        self._run_pending()
        self._run_item_action()

    @staticmethod
    def _slow_tick(marks) -> None:
        """Log where the time went, when a tick took long enough to matter."""
        total = marks[-1][1] - marks[0][1]
        if total < SLOW_TICK_SECONDS:
            return
        parts = ", ".join("{} {:.2f}".format(name, at - marks[i][1])
                          for i, (name, at) in enumerate(marks[1:]))
        print("[app] slow tick {:.2f}s: {}".format(total, parts), flush=True)

    def run(self, on_tick: Optional[Callable[[], None]] = None,
            until: Optional[Callable[[], bool]] = None) -> None:
        """Poll the game until `until` says to stop, or forever without it."""
        period = 1.0 / POLL_HZ
        last_try = 0.0
        print("[app] waiting for Fallout 2 ...", flush=True)
        while True:
            if until is not None and until():
                print("[app] stopping", flush=True)
                return
            if not self._connected():
                now = time.time()
                if now - last_try >= RECONNECT_SECONDS:
                    last_try = now
                    if self.connect():
                        self.ann.say(tr("app.fallout_2_accessibility_connected", "Fallout 2 accessibility connected."), force=True)
                        # And, only if something is wrong, what is missing.
                        # Said here rather than in connect() so it lands after
                        # the greeting instead of ahead of it.
                        warning = (self._offsets.summary()
                                   if self._offsets is not None else None)
                        if warning:
                            self.ann.say(warning, force=True)
                        # And whether the pointer can be used at all. This one
                        # matters more than it looks: without it, full screen
                        # presents as every click in the mod quietly doing
                        # nothing.
                        if getattr(self, "_window_complaint", None):
                            self.ann.say(self._window_complaint, force=True)
                time.sleep(RECONNECT_SECONDS)
                continue
            try:
                if self._active():
                    began = time.time()
                    self.tick()
                    took = time.time() - began
                    if took >= SLOW_TICK_SECONDS:
                        print("[app] tick took {:.2f}s on {}".format(
                            took, self.screen), flush=True)
            except OSError:
                pass
            except Exception:
                # **The loop outlives a broken tick.** It used to catch only
                # OSError, so anything else ended the mod outright: a mistyped
                # relative import in one log-line handler raised ImportError on
                # the first Skilldex line and every key went dead from then on,
                # in a game the player was in the middle of.
                #
                # Printed in full rather than swallowed. Silence is this
                # project's worst failure mode and a caught exception is a very
                # effective way to produce it -- but a mod that keeps working
                # for everything else, and says where to look, beats one that
                # stops. The speech is deliberately once per distinct fault, so
                # a fault that recurs every tick does not talk over the game.
                import traceback

                where = traceback.format_exc()
                print("[app] tick failed:\n{}".format(where), flush=True)
                summary = where.strip().splitlines()[-1]
                if summary != self._last_fault:
                    self._last_fault = summary
                    self.ann.say(tr("app.the_mod_hit_an_error_and_carried_on_check_the_console", "The mod hit an error and carried on. "
                                 "Check the console."), force=True)
            if on_tick:
                on_tick()
            time.sleep(period)
