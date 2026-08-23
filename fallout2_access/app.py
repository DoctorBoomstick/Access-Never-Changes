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
from .game import (actions, charsheet, dialogue, itemactions, itemmove,
                   slotscreen, timerwin, uiwindow)
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

    def __init__(self, chargen: CharGen, log=None) -> None:
        self.chargen = chargen
        # The in-game character screen is the same panel as the creation editor,
        # so the same watcher narrates it -- but its numbers come from a live
        # character rather than from the editor's working copy. Handing the
        # reader the script's report is what makes it say 6 where the sheet says
        # 6, instead of the 8 sitting in the base stat table.
        self.log = log
        self._prev: Dict[str, object] = {}

    def reset(self) -> None:
        self._prev = {}

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
            # What the current row actually says.
            #
            # The selection index is not always the thing that moves. The Kills
            # and Karma lists scroll a row at a time while the index sits still,
            # so a watcher keyed on the index alone heard nothing and said
            # nothing -- three rows of a list reported as one, and the others
            # silent even of a number.
            "label": self._row_text(),
        }

    def _row_text(self) -> Optional[str]:
        item = self.chargen.current()
        return item.announce() if item else None

    def enter(self, ann: Announcer) -> None:
        self._sync()
        self._prev = self.snapshot() or {}
        # The same panel serves two purposes and they are not the same screen.
        # Announcing "character creation" over a character who has been played
        # for an hour is simply wrong, and it is the first thing said on the way
        # in, so it is the first thing that sounds broken.
        title = ("Character sheet." if self.chargen.sheet is not None
                 and self.chargen.sheet.ready else "Character creation.")
        item = self.chargen.current()
        ann.answer("{} {}".format(title, item.announce()) if item else title)

    def poll(self, ann: Announcer) -> None:
        snap = self.snapshot()
        if snap is None:
            return
        prev, self._prev = self._prev, snap
        if not prev:
            return

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
            ann.answer("{}.".format(self.chargen.sex_name() or "sex changed"))
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
            else:
                # An item outside the measured index map. The in-game sheet has
                # sections the creation editor does not -- the Perks, Karma and
                # Kills tabs -- and their indices have never been measured.
                #
                # Say the number rather than nothing. A confident wrong label
                # would be worse than silence, but silence is what makes a
                # screen feel broken: tabbing onto a section and hearing nothing
                # is indistinguishable from the key not arriving. The index is a
                # fact, it is honest about not knowing what the section is, and
                # it is exactly what someone reading it aloud to me needs to
                # say. It goes to the console too.
                index = snap.get("selection")
                print("[chargen] no entry for editor index {}".format(index),
                      flush=True)
                ann.answer("Item {}, not covered yet.".format(index))
            return

        # A row that changed without the index changing.
        #
        # **Only for the Perks, Karma and Kills box.** Those three lists scroll
        # a line at a time and leave the selection index where it was, so
        # nothing else notices them. Everywhere else the index IS the movement,
        # and watching the text as well announced things twice and out of
        # order: the label pointers update a frame after the selection does, so
        # tabbing to a new section spoke the row on the poll the index changed
        # and spoke it again on the next, sometimes with the previous section's
        # text still in the pointer. Tabbing read as "stats, name age sex,
        # stats again, age sex name".
        item = self.chargen.current()
        if (item is not None and item.section == "record"
                and prev.get("label") != snap.get("label")
                and snap.get("label")):
            ann.answer(str(snap.get("label")))

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
            return "Name. {}".format(
                name if name and name != "None" else "Empty.")
        if which == "age":
            return "Age {}.".format(self.chargen.age())
        if which == "sex":
            return "Sex. {}.".format(self.chargen.sex_name() or "not known")
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
            return "Name cleared."
        if after.startswith(before):
            # Includes the very first letter, where `before` is empty and the
            # whole of `after` is what was just typed.
            return after[len(before):]
        if before.startswith(after):
            return "{}, {}".format(before[len(after):], after)
        return "Name {}".format(after)

    def repeat(self, ann: Announcer) -> None:
        self._sync()
        item = self.chargen.current()
        if item:
            ann.answer(item.announce())

    def describe(self, ann: Announcer) -> None:
        self._sync()
        item = self.chargen.current()
        if item and item.description:
            ann.answer("{}. {}".format(item.label, item.description))
        elif item:
            ann.answer("{}. No description.".format(item.label))

    def summary(self, ann: Announcer) -> None:
        self._sync()
        ann.answer(self.chargen.summary())


# The key list that used to be spoken here is gone, on the owner's instruction:
# it was said on every entry to the world AND on every summary, which made it
# the most-heard sentence in the mod, and a player who has read the readme is
# being told what they already know every time they load a game. The keys are
# documented in README.md and docs/CONTROLS.md, where they can be consulted once
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
        # A world action-menu choice waiting to be carried out: look, talk.
        self.pending_menu_action: Optional[str] = None
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
            elif line.startswith("WORLD:menudo"):
                # A menu entry the script cannot carry out, because it needs
                # the pointer. Written down and picked up by the loop, off this
                # parsing path -- driving the engine's menu takes seconds.
                self.pending_menu_action = line
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
                    if not screens.is_dialogue(self.log.game_mode):
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
        ann.answer("Exploring.")

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
        self._pump_dialogue(ann)

    def talking(self) -> bool:
        """Is a conversation the thing on screen?

        The barter window is a conversation's child, and while it is up it is
        what the player is looking at -- gl_inven.ssl owns it and is already
        describing both lists. Two voices narrating different halves of the
        same screen is worse than either on its own.
        """
        return (self.dialogue is not None
                and screens.is_dialogue(self.log.game_mode)
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
        """Walk the reply list. Numpad 8 and 2, as everywhere else in the mod.

        Clamped, not wrapped -- the same choice the action menu made, and for
        the same reason: a list that wraps is one you can walk off the end of
        without noticing, and every entry on this one is something you are
        about to say to somebody.
        """
        reading = self.read_dialogue()
        if reading is None or not reading.options:
            ann.answer("No replies offered.")
            return
        self.dlg_index = max(0, min(self.dlg_index + delta,
                                    len(reading.options) - 1))
        ann.answer(dialogue.say_option(self.dlg_index, reading.options))

    def dlg_say(self, ann: Announcer) -> None:
        """Re-read the reply the list cursor is on."""
        reading = self.read_dialogue()
        if reading is None:
            ann.answer("Cannot read the replies.")
            return
        ann.answer(dialogue.say_option(self.dlg_index, reading.options))

    def read_dialogue(self):
        return self.dialogue.read() if self.dialogue is not None else None

    def repeat(self, ann: Announcer) -> None:
        # A panel over the map takes the question with it. "Repeat" while the
        # loot window is open means the item under the list cursor, not the hex
        # the player last looked at before they opened it.
        if self.inventory.open:
            ann.answer(self.inventory.repeat() or HELP_NOTHING)
            return
        # In a conversation the question this key asks is "what can I say?".
        # The hex the player was last looking at is not what is on screen.
        if self.talking():
            reading = self.read_dialogue()
            ann.answer(dialogue.say_options(reading.options) if reading
                       else "Cannot read the replies.")
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
        # And here it asks the third question this key has been given: what did
        # they just say? A long reply is a paragraph, and one a player wants to
        # hear again without the list of answers after it every time.
        if self.talking():
            reading = self.read_dialogue()
            if reading is None:
                ann.answer("Cannot read what they said.")
            else:
                ann.answer(reading.reply or "They have said nothing.")
            return
        if self.hwnd is None:
            ann.answer("Not attached to the game.")
            return
        if not screens.is_map_mode(self.log.game_mode):
            ann.answer("{}.".format(
                screens.mode_name(self.log.game_mode).capitalize()))
            return

        # **No aiming.** This used to say "Checking", then spend several seconds
        # driving the pointer onto the object, holding the button down for the
        # engine to build its icon strip, and stepping away again -- and it
        # could still come back with the wrong object, or none, because it was
        # inferring which thing the player meant from where a pointer landed.
        #
        # The script now reads the hex directly with tile_get_objs and offers
        # what is on it. One keystroke, no pointer, nothing to land wrong, and
        # nothing to say first because there is no longer a wait to cover.
        self._menu_aimed_at = None
        guarded_tap(self.hwnd, "m", settle=0.15)

    def summary(self, ann: Announcer) -> None:
        # "Where am I" is answered by whatever currently owns the screen. Each
        # of these is a different question wearing the same key.
        if self.inventory.open:
            ann.answer("{}. {}".format(
                self.inventory.container or screens.mode_name(self.log.game_mode),
                self.inventory.repeat() or HELP_NOTHING))
            return
        if self.talking():
            reading = self.read_dialogue()
            ann.answer(dialogue.say_reading(reading, opening=True, hint=True)
                       if reading else "Cannot read the conversation.")
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

    def __init__(self, screen, saves: SaveWatcher, pager) -> None:
        self.screen = screen
        self.saves = saves
        self.pager = pager
        self._selection: Optional[int] = None
        # Is the confirmation box up? Tracked so it is announced once on
        # arrival rather than twenty times a second.
        self._confirm = False

    def reset(self) -> None:
        self._selection = None
        self._confirm = False

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
            return ("The game is showing a message that cannot be read. "
                    "Press Enter to dismiss it.")

        index = self.screen.selection()
        page = self.screen.page()
        where = "this slot"
        if index is not None and page is not None:
            where = "slot {}".format(self.screen.slot_number(page, index))

        occupied = self.screen.occupied()
        taken = bool(index is not None and index < len(occupied)
                     and occupied[index])
        described = ""
        if taken and index is not None:
            _character, description = self.screen.header(index)
            if description:
                described = ", {}".format(description)

        if self.screen.loading:
            question = "Load {}{}?".format(where, described)
        elif taken:
            # The game's own words for the one case it has words for.
            question = self.screen.message(slotscreen.MSG_OVERWRITE) or \
                "Save game already exists, overwrite?"
            question = "{} {}{}.".format(question, where.capitalize(), described)
        else:
            question = "Save to {}?".format(where)
        return "{} Enter to confirm, Escape to cancel.".format(question)

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
        # The confirmation box first, and while it is up nothing else speaks.
        # It is a modal: the row list behind it is not what the player is
        # answering, and narrating a highlight they can no longer move would be
        # actively misleading.
        box = self.screen.confirm()
        if box is not None:
            if not self._confirm:
                self._confirm = True
                ann.answer(self._confirm_line(box))
            return
        if self._confirm:
            self._confirm = False
            # Nothing is said on the way out. Confirming produces a save, which
            # the savegame watcher announces from the folder; cancelling puts
            # the highlight back, which the row poll below announces anyway.
            self._selection = None

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
        # The last fault spoken, so a fault that recurs every tick is reported
        # to the console each time but announced only once.
        self._last_fault: Optional[str] = None

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
            screens.CHARGEN: CharGenWatcher(CharGen(self.proc), self.world.log),
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
            # Never click in a conversation. There is nothing here worth
            # pointing at -- the replies are chosen by their numbers -- and a
            # click would land wherever the pointer happens to have been left,
            # which means picking a reply at random and saying it to somebody.
            # Of all the misplaced clicks this mod guards against, this is the
            # only one that cannot be walked back.
            if self.world.talking():
                if button == "left":
                    self.say_reply()
                else:
                    self.ann.answer(dialogue.HINT)
                return
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
                # Everything the readout named, not just the first of them --
                # see HexReading.names(). Naming only the first is what made
                # every door in the game unclickable.
                wanted = last.names() if (expects_object and last) else None
                name, _at = self.aimer.prepare(expects_object, wanted=wanted)
                if expects_object and not name:
                    self.ann.answer("Cannot point at {}.".format(
                        wanted[0] if wanted else "that"))
                    return
                if not expects_object and name is False:
                    # Every part of the hex is underneath something else's
                    # sprite, so a click would act on that instead of walking.
                    # Name it: "behind Wall" is something a player can act on,
                    # "behind something" is a shrug.
                    self.ann.answer("That hex is behind {}.".format(
                        self.aimer.blocked_by or "something"))
                    return
                time.sleep(CURSOR_SETTLE)
            guarded_click(self.hwnd, button)
        except FocusLost:
            self.ann.answer("Game is not focused.")
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
            self.ann.answer("No replies offered.")
            return
        index = max(0, min(self.world.dlg_index, len(reading.options) - 1))
        if index >= 9:
            # Only 1 to 9 are bound. A tenth reply exists in the array and can
            # be read out, but saying it would mean clicking on it, and that is
            # not built. Say so plainly rather than pressing something else.
            self.ann.answer("The mod cannot say replies past the ninth yet.")
            return
        text = reading.options[index]
        # Said before the key goes down, because this is the one confirmation
        # the player gets that they said what they meant to. The NPC's answer
        # follows on its own, off the memory poll.
        self.ann.answer("Saying: {}".format(
            text or "reply {}".format(index + 1)))
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
        if line == "useactive":
            # The U key, from the map: the item is already in the active hand,
            # so this is just the click that arms it. What it gets used ON is
            # the player's next choice, which is the point.
            done, why = itemactions.click_item_slot(
                self.proc, self.hwnd, log_path=self.world.log.path)
            if not done:
                self.ann.answer(why or "That did not work.")
            return
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
        log_path = self.world.log.path
        if what.startswith("use"):
            done, why = itemactions.use(self.proc, self.hwnd, side, index,
                                        active, log_path=log_path)
        elif what.startswith("drop"):
            done, why = itemactions.drop(self.world.finder, self.proc,
                                         self.hwnd, side, index, total,
                                         log_path=log_path)
        else:
            done, why = False, "The mod has no way to do that yet."
        if not done:
            self.ann.answer(why or "That did not work.")

    def _run_menu_action(self) -> None:
        """Carry out a world action-menu choice: look at it, talk to it.

        Both are done by driving the engine's own menu, which means aiming at
        the object again and creeping the highlight onto the icon -- several
        seconds, and far too slow to do while parsing a batch of log lines.
        """
        line = self.world.pending_menu_action if self.world else None
        if not line:
            return
        self.world.pending_menu_action = None
        parts = line.split("|")
        head = parts[0].split()
        if len(head) < 2 or not head[1].lstrip("-").isdigit():
            return
        code = int(head[1])
        target = parts[1].strip() if len(parts) > 1 else ""
        if self.proc is None or self.hwnd is None or self.aimer is None:
            self.ann.answer("Not attached to the game.")
            return

        # Say so first. This takes a few seconds, and silence after a keypress
        # reads as the key never having arrived -- the misreading this project
        # keeps having to design against.
        self.ann.answer("{}{}.".format(
            actions.name(code).capitalize(),
            ": {}".format(target) if target else ""))
        try:
            done, why = actions.perform(self.proc, self.aimer, self.hwnd, code,
                                        wanted=target or None)
        except FocusLost:
            self.ann.answer("Game is not focused.")
            return
        except Exception as exc:  # never let this kill the loop
            print("[app] menu action: {}".format(exc), flush=True)
            self.ann.answer("That did not work.")
            return
        if not done:
            self.ann.answer("Could not {}: {}.".format(
                actions.name(code), why or "no answer"))
        # Nothing is said on success. Looking prints the game's own sentence
        # along the bottom of the screen and talking opens a conversation, and
        # both of those are already announced by whoever owns them.

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
        # The reply-list keys are the hex cursor's keys wearing another hat.
        # In a conversation gl_dialog.ssl swallows them so the engine never
        # sees them as reply numbers; everywhere else they belong to the map,
        # and this must not answer for them there.
        if what.startswith("dlg_"):
            if not (self.world is not None and self.world.talking()):
                return
            if what == "dlg_prev":
                self.world.dlg_step(self.ann, -1)
            elif what == "dlg_next":
                self.world.dlg_step(self.ann, 1)
            elif what == "dlg_say":
                self.world.dlg_say(self.ann)
            return
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
        self._run_menu_action()

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
                    self.ann.say("The mod hit an error and carried on. "
                                 "Check the console.", force=True)
            if on_tick:
                on_tick()
            time.sleep(period)
