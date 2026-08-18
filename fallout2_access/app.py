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

import time
from typing import Callable, Dict, Optional

import os

from .game import screens
from .game.aim import Aimer
from .game.chargen import CharGen
from .game.combat import CombatWatcher
from .game.displaywin import DisplayWindow
from .game.premade import PremadeScreen
from .game.scanner import Scanner
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

MAIN_MENU_HELP = (
    "Main menu. Press N for new game, L to load a game, I for the intro, "
    "O for options, C for credits, E to exit."
)
SELECT_HELP = (
    "Left and right arrows cycle characters. Press T to take this one, "
    "M to modify it, C to create your own, or B to go back."
)


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


WORLD_HELP = (
    "Numpad 7 9 4 6 1 3 move the look cursor around the six hex "
    "directions. Numpad 5 re-reads the hex, numpad 8 returns the cursor to you, "
    "numpad star clicks where the cursor is."
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
    # Calibration output. Numpad 2 is no longer a key anyone presses on
    # purpose -- the aimer presses it several times per click to find out where
    # the pointer is, and narrating that would bury the click in numbers.
    "WORLD:calib",
    "WORLD:win",
    "WORLD:mode",
)


class WorldWatcher(Watcher):
    """In-game map exploration, driven by gl_world.ssl through debug.log."""

    key = screens.WORLD

    def __init__(self, log: WorldLog) -> None:
        self.log = log
        self.combat = CombatWatcher()
        self.scanner = Scanner()
        self._queue: list = []
        self._mode: Optional[int] = None

    def reset(self) -> None:
        self._queue = []

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
            elif line.startswith("COMBAT:"):
                # Combat speaks even when the mod thinks another screen is up.
                # Being attacked is not something to withhold because a screen
                # detector is unsure.
                self._queue.extend((t, False) for t in self.combat.handle(line))
            elif line.startswith("WORLD:hex") and self.log.last_hex:
                self._queue.append((self.log.last_hex, True))
            elif line.startswith("WORLD:gamemode"):
                if self._mode is not None and self.log.game_mode != self._mode:
                    self._queue.append((screens.mode_name(self.log.game_mode), False))
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
                parts = line.split()
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
        if self.log.last_hex:
            ann.answer(self.log.last_hex.announce())
        else:
            ann.answer("No hex read yet. Press numpad 5.")

    def describe(self, ann: Announcer) -> None:
        self.repeat(ann)

    def summary(self, ann: Announcer) -> None:
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
        self.world = WorldWatcher(WorldLog(log_path))
        self.aimer = Aimer(self.hwnd, log_path) if self.hwnd else None
        # The game's own prose. Located lazily: the beacon it keys off is only
        # printed once a game is actually loaded.
        self.display = DisplayWindow(self.proc)
        self.watchers = {
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

        The mod moves the pointer; it does not decide what the click means.
        That split matters. Pointing is the part you physically cannot do, so
        the mod does it and verifies it. What a click then *does* -- walk,
        interact, attack, pick a lock -- belongs to the cursor mode, which is
        yours to set with right click or a Skilldex key, exactly as it is for a
        sighted player. The mod announces the mode whenever it changes, so you
        have the same information they read off the cursor's shape.

        An earlier version chose the mode for you and it was a mistake in both
        directions: it disarmed a skill the moment you tried to use one, and it
        guessed wrong about intent in cases nobody had enumerated.

        What does NOT change is the refusal to click on a maybe. If the look
        hex holds something and the engine will not confirm the pointer is on
        it, nothing is sent -- a misplaced click walks you somewhere you did not
        choose, or swings at empty ground and spends the turn.
        """
        if self.hwnd is None:
            return
        try:
            if button == "left" and screens.is_map_mode(self.world.log.game_mode):
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
                expects_object = bool(
                    last and last.contents and last.contents not in ("empty", "you")
                )
                if expects_object:
                    name, _dy = self.aimer.confirm_object()
                    if not name:
                        self.ann.answer("Cannot point at that.")
                        return
            guarded_click(self.hwnd, button)
        except FocusLost:
            self.ann.answer("Game is not focused.")
        except Exception as exc:  # never let a hotkey kill the loop
            print("[app] click: {}".format(exc), flush=True)

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
        self.pump_display()
        detected = screens.detect(self.proc, in_game=self.world.log.session_live)

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
