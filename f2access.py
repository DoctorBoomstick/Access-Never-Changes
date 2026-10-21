#!/usr/bin/env python3
"""Fallout 2 screen reader accessibility.

Run this alongside the game:

    python f2access.py

Then play. Character creation is announced as you move through it.

Numpad 0-9 belong to the in-game script (gl_world.ssl), which walks a look
cursor around the hex grid. So this mod's own hotkeys live on the numpad
*operator* keys, which the script ignores:

    Numpad +   left mouse button
    Numpad -   right mouse button (cycles the cursor mode)
    Numpad *   summary / where am I
    Numpad /   repeat the current item
    Numpad .   full description

Saving and loading use the game's own keys, not this mod's: F6 quick saves and
F7 quick loads, with no screen and no pointer involved. The mod watches the
savegame folder and says when one lands.

Hotkeys need `pip install pynput`; without it everything else still works.

The game must run WINDOWED (WINDOWED=1 in f2_res.ini). Exclusive-fullscreen
DX9 starves the low-level keyboard hook.

Settings come from access.ini beside this file (see config/access.ini for every
one of them), and the switches below win over it. Installed, the same program
is AccessNeverChanges.exe, and two more ways to start it matter:

    --launch              start Fallout 2 as well, and stop when it closes
    install / uninstall   what the installer runs; see install.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time

from fallout2_access import config, i18n, paths
from fallout2_access.i18n import tr
from fallout2_access.app import App
from fallout2_access.version import banner
from fallout2_access.speech.backends import get_speaker

# Numpad 0-9 are claimed by the in-game script (hex cursor movement), so the
# mod's own hotkeys live on the operator keys, which the script ignores.
# The two mouse buttons sit on numpad + and -, next to each other and
# unmistakable by feel. Everything else is a readout, so a misfire costs a
# sentence rather than an action.
HOTKEYS = {
    107: "click",     # numpad +   LEFT mouse button
    109: "rclick",    # numpad -   RIGHT mouse button (cycles the cursor mode)
    106: "summary",   # numpad *   summary / where am I
    111: "repeat",    # numpad /   repeat the current item
    110: "describe",  # numpad .   full description
    # In a conversation only. Everywhere else these belong to the hex cursor
    # inside the game, and the mod ignores them -- gl_dialog.ssl is what stops
    # the engine reading them as reply numbers while a conversation is up,
    # which it was doing: numpad 4 said the fourth thing on the list.
    #
    # **The arrows are the keys to reach for. The numpad is kept because it is
    # what the old documentation taught.** Both are bound to the same three
    # actions, and both physically produce the same virtual keys -- see
    # `key_vk` below for the trap that sat under all six of them.
    38: "dlg_prev",   # Up         previous reply
    40: "dlg_next",   # Down       next reply
    # **The numpad's three middle keys carry their own names, not the arrows'.**
    # They used to be bound straight to dlg_prev/dlg_next/dlg_say, which was
    # fine while numpad 8 and Up could only ever mean the same thing. The world
    # map broke that: there the arrow keys are the engine's own, and they scroll
    # the view, while the numpad walks this mod's cursor. One name for both keys
    # would have meant pressing Up scrolled the map AND moved the cursor, and
    # the player hearing about one of the two.
    #
    # So the physical keys are told apart here and `App._do_action` maps them
    # back together on every screen except the world map. Nothing about
    # dialogue or the Pip-Boy changes.
    104: "num8",      # numpad 8   -- Up, when Num Lock is on
    98: "num2",       # numpad 2   -- Down, when Num Lock is on
    101: "num5",      # numpad 5   re-read / back to the player
    12: "num5",       # Clear      -- numpad 5 with Num Lock off
    # The world map's cursor. A square grid has eight neighbours, so unlike the
    # hex cursor inside the game every one of these is a real direction.
    # Claimed here rather than in gl_world.ssl because on the world map the
    # script declines every key -- WORLDMAP is in its MAP_HIDDEN set -- and the
    # engine binds none of the numpad, so nothing is being taken from anybody.
    103: "wm_nw",     # numpad 7
    105: "wm_ne",     # numpad 9
    100: "wm_w",      # numpad 4
    102: "wm_e",      # numpad 6
    97: "wm_sw",      # numpad 1
    99: "wm_se",      # numpad 3
    # The scanner, on the same three keys it uses inside the game. On a map
    # gl_world.ssl reads these itself and this mod never sees them; on the world
    # map no script is listening, so they are read here.
    219: "wm_scan_prev",   # [
    221: "wm_scan_next",   # ]
    191: "wm_scan_jump",   # /
    # The barter screen's OFFER button, which is a click and only a click --
    # its event code is 109, which looks like the `m` key and is not; pressing
    # `m` does nothing at all. So the mod needs a key of its own for it, and
    # `o` is free: tried against a live barter, the engine ignores it.
    79: "barter_offer",    # O
    # Enter is the game's own key, and the mod leaves it alone everywhere but
    # one place: the called-shot window, where the engine ignores it and a
    # player choosing a body part will reach for it. App drops it elsewhere.
    13: "enter",
    # The rest of the grammar in fallout2_access/controls.py. All of these are
    # the game's own keys somewhere -- Left and Right in the character editor,
    # Home on the map -- and pass straight through to it; the mod only acts on
    # them on screens whose table binds them.
    8: "back",        # Backspace  back one level
    37: "left",       # Left       less
    39: "right",      # Right      more
    36: "home",       # Home       the least
    35: "end",        # End        the most
    112: "help",      # F1         the keys for this screen
    # The number row, for typing an amount into the "how many" window. Only
    # that window acts on them -- App drops them everywhere else, where they
    # belong to the game: reply numbers, the Skilldex.
    48: "digit0", 49: "digit1", 50: "digit2", 51: "digit3", 52: "digit4",
    53: "digit5", 54: "digit6", 55: "digit7", 56: "digit8", 57: "digit9",
    # T is watched, not taken. It is the engine's own key for the town view and
    # it already works, so nothing is sent when this fires -- pressing it again
    # would open the view twice. What the binding buys is the case where the
    # engine *ignores* it, which it does at any place you have not been inside
    # yet: a silently dead key is indistinguishable from a broken mod, and this
    # is how the mod gets to say which.
    84: "wm_town",         # T
}


# Keys that mean something else with Shift held. Comma and period are the
# message log; gl_world.ssl takes them from the game, whose own `<` and `>`
# would otherwise turn you on the spot (the unshifted keys still do).
SHIFTED_HOTKEYS = {
    188: "log_prev",  # Shift ,    older in the message log
    190: "log_next",  # Shift .    newer in the message log
    9: "back_tab",    # Shift Tab  the previous section, in the character editor
}


def hotkey_for(vk, shift: bool):
    """The action a key means, given whether Shift is held, or None.

    With Shift, the number row is not digits: Shift and 1 is the light level,
    read by the script, and the "how many" window must not take it for a 1.
    """
    if shift:
        what = SHIFTED_HOTKEYS.get(vk)
        if what:
            return what
        if vk is not None and 48 <= vk <= 57:
            return None
    return HOTKEYS.get(vk)


# Set by Windows on keyboard input that a program sent rather than a person.
LLKHF_INJECTED = 0x10


def from_player(_msg, data) -> bool:
    """False for keys this mod sent itself, so it never hears its own typing.

    **The mod was answering itself.** Typing an amount into the "how many"
    window sends digits, and this listener heard those digits as the player
    pressing them -- so every 6 the mod typed queued another 6, which typed
    another, and the queue filled with echoes faster than it could drain.
    f2access.log caught it: thirty-odd "digit6" from a player who pressed it
    a handful of times. Windows marks synthetic input LLKHF_INJECTED, and a
    key with that mark is one this program, not the player, pressed.
    """
    return not (getattr(data, "flags", 0) & LLKHF_INJECTED)


def key_vk(key) -> "int | None":
    """The Windows virtual key behind a pynput key event.

    **This is why the reply keys did nothing for anybody, ever.** The listener
    used to read `key.vk` and give up when it was missing, and pynput hands the
    listener two different shapes: an ordinary character key arrives as a
    `KeyCode`, which has a `vk`, while anything pynput recognises as a special
    key arrives as a `Key` enum member, which does not. `Key.up` keeps its
    virtual key one level down, in `Key.up.value.vk`.

    So `getattr(key, "vk", None)` was None for every arrow press, and the
    hotkey was dropped before any of the dialogue code ran.

    That one line accounts for the whole history of this feature. Num Lock is
    what decides which shape the numpad arrives in -- with it on, numpad 8 is a
    KeyCode with vk 104 and worked; with it off, Windows reports VK_UP, pynput
    calls that `Key.up`, and it vanished here. Which is why the keys worked for
    whoever wrote them and for nobody else, and why binding the arrows as well
    fixed nothing at all: the arrows took the same missing branch.

    Both shapes are asked, in order. Nothing else about the listener changes.
    """
    vk = getattr(key, "vk", None)
    if vk is not None:
        return vk
    # A Key enum member: the KeyCode it wraps is its value.
    return getattr(getattr(key, "value", None), "vk", None)


def start_hotkeys(app: App) -> bool:
    try:
        from pynput import keyboard  # type: ignore
    except ImportError:
        print("[hotkeys] pynput not installed; hotkeys disabled", flush=True)
        print("[hotkeys]   pip install pynput", flush=True)
        return False

    ctrl = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
    shift = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
    held = {"shift": False}

    def on_release(key):
        if key in ctrl:
            app.ctrl_held = False
        if key in shift:
            held["shift"] = False

    def on_press(key):
        if key in ctrl:
            # Tracked rather than asked of Windows, because the listener is
            # the one that knows; read by whoever cares, today only the "how
            # many" window, where Ctrl with up and down steps by ten.
            app.ctrl_held = True
            return
        if key in shift:
            held["shift"] = True
            return
        if getattr(app, "ctrl_held", False) and key_vk(key) == 88:
            # Control and X is the engine's own quit key. Not taken, only
            # noted: the box it opens has no words the mod can read, and
            # knowing the key that opened it is how the box gets named.
            app.quit_key_at = time.time()
        what = hotkey_for(key_vk(key), held["shift"])
        if not what:
            return
        if app.require_focus and not app._active():
            return
        try:
            app.action(what)
        except Exception as exc:  # a hotkey must never kill the listener
            print("[hotkeys] {}".format(exc), flush=True)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release,
                                 suppress=False, win32_event_filter=from_player)
    listener.daemon = True
    listener.start()
    print(
        "[hotkeys] numpad +  LEFT click   |  numpad -  RIGHT click\n"
        "[hotkeys] numpad *  summary      |  numpad /  repeat    |  numpad .  describe\n"
        "[hotkeys] on a map: numpad 0-9 and the brackets are handled inside the game\n"
        "[hotkeys] on the world map: numpad 1-9 walk the cursor, [ ] / scan places",
        flush=True,
    )
    return True


class _Tee:
    """Write to the console and to a file, so a session can be read back.

    The game's debug.log says what the scripts saw; this says what the Python
    half decided. Without it, "talk to it opened the inventory" could be traced
    to the menu walk giving up but not to WHY it gave up -- the reason went to
    a console nobody was reading, and was gone when it closed.
    """

    def __init__(self, stream, path: str) -> None:
        self.stream = stream
        self.file = open(path, "w", encoding="utf-8", buffering=1)

    def write(self, text: str) -> int:
        try:
            self.file.write(text)
        except (OSError, ValueError):
            pass
        return self.stream.write(text) if self.stream else len(text)

    def flush(self) -> None:
        for out in (self.stream, self.file):
            try:
                if out:
                    out.flush()
            except (OSError, ValueError):
                pass


# Beside the program, and started afresh each run -- the same as debug.log.
LOG_PATH = paths.log_path()

# How long a launched game gets to show up before the mod gives up on it.
# Generous: the first start after an install can sit on a disk check.
LAUNCH_GRACE_SECONDS = 90.0

# How long the game may be gone before the mod takes it as closed. sfall
# restarts the game itself on a first launch where two high-resolution patches
# meet, and the game that comes back is a new process.
RESTART_GRACE_SECONDS = 20.0


def run_installer(argv) -> int:
    """`install GAME` and `uninstall GAME`, as the installer calls them.

    The installed program has no console, so what install.py prints goes to
    install.log beside it -- which is where the installer points a player when
    something needs their attention.
    """
    import install

    try:
        sys.stdout = _Tee(sys.stdout, paths.install_log_path())
        sys.stderr = sys.stdout
    except OSError:
        pass
    command, rest = argv[0], list(argv[1:])
    if command == "uninstall":
        rest.append("--uninstall")
    return install.main(rest)


def let_the_game_come_to_the_front() -> None:
    """Hand the game the right to take the front of the screen.

    **Without it the game cannot read the keyboard at all.** Fallout claims the
    keyboard through DirectInput as it starts, and that only succeeds for the
    window in front. Windows only lets a new program in front when whoever
    started it was allowed there -- and this program has no window of its own,
    so the game came up behind everything, failed with "Failure initializing
    input devices", and the mod sat attached to a game that never ran.

    A keypress earns the right (Windows gives it to whoever made the last
    input), and AllowSetForegroundWindow passes it on. F24 is a key no keyboard
    has and nothing listens for; the mod's own listener ignores injected keys.
    Measured: started from a background process, the game came up behind with
    the error box every time without this, and in front with it.
    """
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32")
        vk_f24, keyup = 0x87, 0x0002
        user32.keybd_event(vk_f24, 0, 0, 0)
        user32.keybd_event(vk_f24, 0, keyup, 0)
        time.sleep(0.05)
        user32.AllowSetForegroundWindow(ctypes.c_uint32(0xFFFFFFFF))  # ASFW_ANY
    except Exception as exc:
        print("[launch] could not hand over the foreground: {}".format(exc), flush=True)


def launch_game(game: str):
    exe = os.path.join(game, "fallout2.exe")
    let_the_game_come_to_the_front()
    try:
        return subprocess.Popen([exe], cwd=game)
    except OSError as exc:
        print("[launch] could not start {}: {}".format(exe, exc), flush=True)
        return None


def hand_over_again_on_restart(launched, app, hand_over=None) -> threading.Thread:
    """Hand the front over again if the game restarts itself before it opens.

    sfall does that on a first launch where two high resolution patches meet:
    it asks which to keep, and on Yes starts a new game and quits. That game is
    sfall's, not ours, the Yes keypress has spent the right to the front this
    program handed over, and so it came up behind everything with "Failure
    initializing input devices" -- the very failure the hand-over exists for.
    The installer now makes sfall's change itself, so this is for whatever it
    could not: an exe it did not recognise, or Steam putting the old one back.

    A thread waiting on the process, not the poll loop: the new game opens its
    window within a second or two, and the loop looks only every two seconds
    while nothing is connected. The game window is the test of "before it
    opened" -- a game that had one and then ended was closed, not restarted.
    """
    hand_over = hand_over or let_the_game_come_to_the_front

    def watch() -> None:
        launched.wait()
        if app.hwnd is None:
            print("[launch] the game ended before opening; handing the front "
                  "to whatever it started", flush=True)
            hand_over()

    thread = threading.Thread(target=watch, name="restart-watch", daemon=True)
    thread.start()
    return thread


class StopWhenGameCloses:
    """True once the game this run was attached to has gone.

    Not "when the launched process exits": a launcher stub may start the real
    game and exit at once. So: the mod saw the game, and now it does not. And
    a launched game that never turns up lets the mod go after a grace period,
    rather than leaving a program with no window waiting forever.
    """

    def __init__(self, app, launched=None, grace: float = LAUNCH_GRACE_SECONDS,
                 clock=time.time, restart: float = RESTART_GRACE_SECONDS) -> None:
        self.app = app
        self.launched = launched
        self.grace = grace
        self.restart = restart
        self.clock = clock
        self.started = clock()
        self.seen = False
        self.lost_at = None

    def __call__(self) -> bool:
        if self.app._connected():
            self.seen = True
            self.lost_at = None
            return False
        if self.seen:
            # Gone -- but give it a moment to come back as a new process. On a
            # first launch sfall settles the high-resolution question by
            # starting the game again, and quitting here left that game silent.
            if self.lost_at is None:
                self.lost_at = self.clock()
            return self.clock() - self.lost_at > self.restart
        if self.launched is not None and self.launched.poll() is not None:
            return self.clock() - self.started > self.grace
        return False


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in ("install", "uninstall"):
        return run_installer(argv)

    try:
        sys.stdout = _Tee(sys.stdout, LOG_PATH)
        sys.stderr = sys.stdout
    except OSError:
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--speech", help="force a backend: nvda, sapi, accessible_output2")
    ap.add_argument(
        "--any-focus",
        action="store_true",
        help="announce even when the game is not the foreground window",
    )
    ap.add_argument("--no-hotkeys", action="store_true")
    ap.add_argument(
        "--no-step-sound",
        action="store_true",
        help="do not tick once per hex while you walk",
    )
    ap.add_argument("--launch", action="store_true",
                    help="start Fallout 2 too, and stop when it closes")
    ap.add_argument("--exit-with-game", action="store_true", default=None,
                    help="stop when the game closes")
    ap.add_argument("--stay", dest="exit_with_game", action="store_false",
                    help="keep waiting for the game after it closes")
    args = ap.parse_args(argv)

    print(banner(), flush=True)
    problems = []
    settings = config.load(problems=problems)
    game = paths.game_dir(settings.game_folder)
    # A language with no file yet is not a mistake -- "auto" asks for German on
    # a German game whether or not anyone has translated the mod -- so it is
    # logged and not spoken. A file that would not read IS one.
    notes = []
    language = i18n.init(i18n.choose(settings.language, game), problems=notes)
    print("[config] {}; speaking {}".format(paths.config_path(), language),
          flush=True)
    for problem in problems + notes:
        print("[config] {}".format(problem), flush=True)
    problems += [n for n in notes if not n.startswith("no ")]

    prefer = args.speech or (None if settings.speech == "auto" else settings.speech)
    speaker = get_speaker(prefer=prefer)
    if problems:
        speaker.speak(tr("start.bad_settings", "Access Never Changes: a settings file has a mistake. "
                      "The log says which."))
    app = App(speaker=speaker,
              require_focus=not (args.any_focus or settings.speak_without_focus),
              step_sound=settings.step_sound and not args.no_step_sound)

    if settings.hotkeys and not args.no_hotkeys:
        start_hotkeys(app)

    launched = None
    if args.launch:
        if not game:
            print("[launch] no Fallout 2 folder: set [game] folder in {}".format(
                paths.config_path()), flush=True)
            speaker.speak(tr("start.no_game", "Access Never Changes could not find Fallout 2. "
                          "Set the game folder in access.ini."))
            time.sleep(4)
            return 1
        launched = launch_game(game)
        if launched is None:
            speaker.speak(tr("start.no_launch", "Access Never Changes could not start Fallout 2."))
            time.sleep(4)
            return 1
        hand_over_again_on_restart(launched, app)

    exit_with_game = args.exit_with_game
    if exit_with_game is None:
        exit_with_game = settings.exit_with_game or args.launch
    until = StopWhenGameCloses(app, launched) if exit_with_game else None

    try:
        app.run(until=until)
    except KeyboardInterrupt:
        print("\n[app] stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
