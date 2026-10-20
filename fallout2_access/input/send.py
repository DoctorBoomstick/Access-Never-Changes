"""Send keystrokes to the game and manage its window focus.

Two details matter here and both are easy to get wrong:

1. Fallout 2 reads the keyboard through DirectInput. DirectInput ignores
   PostMessage/SendMessage entirely, and virtual-key SendInput is unreliable
   for it -- so every key is sent as a *scancode* (KEYEVENTF_SCANCODE) with
   the extended-key flag where the scancode requires it.

2. Windows' foreground lock will silently refuse SetForegroundWindow from a
   background process. AttachThreadInput to the target's thread first, which
   is the conventional way through it.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time
from typing import List, Optional, Sequence, Tuple
from ..i18n import tr

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

# DirectInput scancodes, and whether each needs the extended-key prefix.
# (scancode, extended)
DIK = {
    "up": (0x48, True),
    "down": (0x50, True),
    "left": (0x4B, True),
    "right": (0x4D, True),
    # The four the manual gives the inventory lists, and the engine really does
    # answer them -- tested against the live game rather than taken on the
    # manual's word, because the same manual is silent about the arrows the
    # scripts took. Home puts a list at the top and End at the bottom, in one
    # keystroke and with nothing pointed at; Page Up and Page Down move it by
    # exactly one pane. See `itemmove.scroll_to` for what that is worth.
    "home": (0x47, True),
    "end": (0x4F, True),
    "pageup": (0x49, True),
    "pagedown": (0x51, True),
    "enter": (0x1C, False),
    "escape": (0x01, False),
    "tab": (0x0F, False),
    "space": (0x39, False),
    "minus": (0x0C, False),
    "plus": (0x0D, False),  # the '=' key
    # The number row. Fallout binds these to the dialogue replies itself --
    # option i is pressed by the key '1' + i, which the engine states in its
    # own button table -- so saying a reply is pressing one of these rather
    # than pointing at anything.
    #
    # Zero and backspace are here for the "Move Items" window, which reads
    # digits typed at it and takes one off on a backspace -- see quantity.py.
    # Zero had no entry at all, which is worth a line of its own: the mod had
    # exactly one route to the digit and it was `numpad0`, whose meaning
    # depends on Num Lock and which that window reads as a zero.
    "0": (0x0B, False),
    "backspace": (0x0E, False),
    "1": (0x02, False),
    "2": (0x03, False),
    "3": (0x04, False),
    "4": (0x05, False),
    "5": (0x06, False),
    "6": (0x07, False),
    "7": (0x08, False),
    "8": (0x09, False),
    "9": (0x0A, False),
    # The whole alphabet, rather than the dozen letters something in Python
    # happened to need. This table has now produced two false failures of the
    # same shape: a probe of the character editor died on 'h' and a check of the
    # U key died on 'u', in both cases reporting a missing key as though the
    # thing being tested were broken. `u` in particular is a key the mod
    # documents and a player presses; not being able to send it made the one
    # bug that needed reproducing the one bug that could not be.
    "a": (0x1E, False),
    "b": (0x30, False),
    "c": (0x2E, False),
    "d": (0x20, False),
    "e": (0x12, False),
    "f": (0x21, False),
    "g": (0x22, False),
    "h": (0x23, False),
    "i": (0x17, False),
    "j": (0x24, False),
    "k": (0x25, False),
    "l": (0x26, False),
    "m": (0x32, False),
    "n": (0x31, False),
    "o": (0x18, False),
    "p": (0x19, False),
    "q": (0x10, False),
    "r": (0x13, False),
    "s": (0x1F, False),
    "t": (0x14, False),
    "u": (0x16, False),
    "v": (0x2F, False),
    "w": (0x11, False),
    "x": (0x2D, False),
    "y": (0x15, False),
    "z": (0x2C, False),
    # Numpad. Note these share scancodes with the arrow/nav cluster and are
    # distinguished *only* by the extended flag: numpad 8 is 0x48 plain, while
    # the up arrow is 0x48 extended. Getting that wrong sends the wrong key.
    "numpad0": (0x52, False),
    "numpad1": (0x4F, False),
    "numpad2": (0x50, False),
    "numpad3": (0x51, False),
    "numpad4": (0x4B, False),
    "numpad5": (0x4C, False),
    "numpad6": (0x4D, False),
    "numpad7": (0x47, False),
    "numpad8": (0x48, False),
    "numpad9": (0x49, False),
    "numpad_star": (0x37, False),
    "numpad_minus": (0x4A, False),
    "numpad_plus": (0x4E, False),
    "numpad_dot": (0x53, False),
    "backslash": (0x2B, False),
    "apostrophe": (0x28, False),
    # The rest of the keys gl_world.ssl already binds. The table only ever
    # listed the ones something in Python happened to send, so driving the
    # scanner from a tool failed on a missing entry rather than on anything
    # real.
    "semicolon": (0x27, False),     # read out health, AP and AC
    "lbracket": (0x1A, False),      # previous scan category / entry
    "rbracket": (0x1B, False),      # next scan category / entry
    "slash": (0x35, False),         # jump the look cursor to the scanned object
    # Left Ctrl, held rather than tapped. ddraw.ini binds
    # ItemMoveSkipDragKey=29 to it, which makes a click move an item between
    # inventory lists instead of starting a drag -- and a drag is not something
    # this mod can do, because it would have to hold the button down across an
    # aim it cannot verify half way through.
    "lctrl": (0x1D, False),
    # Left Shift, held for the same reason and never on its own. ddraw.ini
    # binds ItemFastMoveKey=42 to it, which moves a whole stack instead of
    # opening the "Move Items" window to ask how many. Ctrl says "do not drag";
    # Shift says "do not ask". Measured: Ctrl alone opened the quantity picker
    # and moved nothing, so the pair is what a move actually needs.
    "lshift": (0x2A, False),
    "rshift": (0x36, False),
    "rctrl": (0x1D, True),
}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wt.DWORD),
        ("wParamL", wt.WORD),
        ("wParamH", wt.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT


def _key_event(scancode: int, extended: bool, keyup: bool) -> INPUT:
    flags = KEYEVENTF_SCANCODE
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if keyup:
        flags |= KEYEVENTF_KEYUP
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(
        wVk=0, wScan=scancode, dwFlags=flags, time=0, dwExtraInfo=None
    )
    return inp


def tap(key: str, hold: float = 0.03, settle: float = 0.12) -> None:
    """Press and release one key, then wait for the game loop to react.

    `settle` matters: Fallout 2's UI loop is slow, and reading memory before it
    has processed the key produces a stale snapshot and a wrong conclusion.
    """
    if key not in DIK:
        raise ValueError("unknown key {!r}; known: {}".format(key, ", ".join(sorted(DIK))))
    scancode, extended = DIK[key]
    down = _key_event(scancode, extended, False)
    up = _key_event(scancode, extended, True)

    sent = user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    if sent != 1:
        raise OSError("SendInput failed: {}".format(ctypes.get_last_error()))
    time.sleep(hold)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
    time.sleep(settle)


def tap_many(key: str, count: int, **kwargs) -> None:
    for _ in range(count):
        tap(key, **kwargs)


# -- windows -----------------------------------------------------------------

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


# Fallout 2's own window class. GNW is the engine's windowing library and this
# is the class it registers, so it is the one window that is actually the game.
GAME_WINDOW_CLASS = "GNW95 Class"

# The window DirectX puts up in front of it. Not the game: keystrokes sent here
# reach nothing and the pointer means nothing, but it is visible, titled, and
# owned by the same process, so a search that takes the first match will take
# this one about half the time.
PROXY_WINDOW_CLASS = "D3DProxyWindow"


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def game_windows(pid: int) -> List[int]:
    """Every visible, titled top-level window belonging to `pid`."""
    found: List[int] = []

    def callback(hwnd, _lparam):
        wnd_pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wnd_pid))
        if wnd_pid.value == pid and user32.IsWindowVisible(hwnd):
            if user32.GetWindowTextLengthW(hwnd) > 0:
                found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def find_game_window(pid: int) -> Optional[int]:
    """The game's own window, chosen by class rather than by luck.

    **This cost a whole evening's play, and it failed by being intermittent.**
    Running the game full screen, DirectX adds a second visible titled window of
    its own -- `D3DProxyWindow`, covering the screen -- so the process owns two
    windows that both pass a "visible and titled" test. This used to return
    whichever `EnumWindows` yielded first, which is Z-order, which is whichever
    happened to be on top at that instant.

    When it picked the proxy, every keystroke the mod sent went nowhere and
    every aim ground through its full step count against a pointer that could
    not move. Nothing errored. It reads exactly like the mod being slow, and
    that is how it was reported.

    So the game is identified by the class GNW registers for it, and the proxy
    is refused outright rather than merely deprioritised: on a build where the
    game's own window is somehow missing, having no window at all is a failure
    the mod reports, while having the proxy is a failure it cannot detect.
    """
    windows = game_windows(pid)
    for hwnd in windows:
        if window_class(hwnd) == GAME_WINDOW_CLASS:
            return hwnd
    # No GNW window. Take anything that is not the proxy -- other builds and
    # other wrappers exist, and this should not be a whitelist of one.
    for hwnd in windows:
        if window_class(hwnd) != PROXY_WINDOW_CLASS:
            return hwnd
    return None


# How far off screen a window has to be before it is certainly parked rather
# than merely partly off the edge. The proxy parks the real window at -25600.
_PARKED = -10000


def fullscreen_complaint(hwnd: Optional[int], pid: int) -> Optional[str]:
    """Say why the pointer will not work, or None when it will.

    Full screen is not a supported way to run this mod and never has been --
    the docs have said so since the first week -- but nothing checked,
    and the way it fails is silent. DirectX parks the game's real window off
    screen behind its own, so the pointer has no meaningful position: every
    click the mod aims is computed against a window sitting at -25600.

    Worth saying out loud rather than printing. A player who cannot see the
    screen has no way to notice that the game went full screen, and every
    symptom of it -- items that will not move, a barter window that does
    nothing -- looks like the mod being broken.
    """
    if hwnd is None:
        return tr("window.not_found",
                  "Cannot find the game's window. If the game is running full "
                  "screen, set Mode to 5 under Graphics in ddraw.ini and "
                  "restart it.")
    fix = tr("window.fix",
             "Set Mode to 5 under Graphics in ddraw dot ini and restart the "
             "game. Not WINDOWED in f2_res.ini -- with the built-in high "
             "resolution patch that setting is ignored.")
    rect = window_rect(hwnd)
    if rect[0] < _PARKED or rect[1] < _PARKED:
        return tr("window.fullscreen",
                  "The game is running full screen, and the mod cannot aim the "
                  "pointer that way. {fix} Reading and speaking still work; "
                  "clicking does not.", fix=fix)
    for other in game_windows(pid):
        if window_class(other) == PROXY_WINDOW_CLASS:
            return tr("window.directx",
                      "The game is running full screen through DirectX, and "
                      "the mod cannot aim the pointer that way. {fix} Reading "
                      "and speaking still work; clicking does not.", fix=fix)
    return None


def window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def is_foreground(hwnd: int) -> bool:
    return user32.GetForegroundWindow() == hwnd


class FocusLost(RuntimeError):
    """The game window was not in the foreground when a key was to be sent.

    Raised rather than pressing on, because a keystroke sent to the wrong
    window is silent: the tool carries on, the game never sees the input, and
    whatever memory happens to say gets recorded as a result. That produced a
    bogus scan once already.
    """


VK_MENU = 0x12
KEYEVENTF_KEYUP_VK = 0x0002


def _alt_nudge() -> None:
    """Tap ALT to release Windows' foreground lock.

    SetForegroundWindow is refused for a background process unless that process
    "owns" the foreground or recently received input. Synthesising an ALT press
    is the conventional way to satisfy that check.
    """
    user32.keybd_event(VK_MENU, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP_VK, 0)
    time.sleep(0.02)


def focus_window(hwnd: int, timeout: float = 3.0) -> bool:
    """Bring `hwnd` to the foreground, working around the foreground lock."""
    if is_foreground(hwnd):
        return True

    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    our_thread = kernel32.GetCurrentThreadId()

    deadline = time.time() + timeout
    for attempt in range(4):
        attached = False
        if target_thread and target_thread != our_thread:
            attached = bool(user32.AttachThreadInput(our_thread, target_thread, True))
        try:
            if attempt:
                _alt_nudge()
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(our_thread, target_thread, False)

        while time.time() < deadline:
            if is_foreground(hwnd):
                time.sleep(0.15)  # let the game settle before it is typed at
                return is_foreground(hwnd)
            time.sleep(0.05)
    return is_foreground(hwnd)


# -- mouse ---------------------------------------------------------------

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def client_size(hwnd: int) -> Tuple[int, int]:
    r = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return r.right - r.left, r.bottom - r.top


def client_to_screen(hwnd: int, x: int, y: int) -> Tuple[int, int]:
    """Map a point in the game's client area to absolute screen pixels."""
    pt = POINT(x, y)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def move_mouse_client(hwnd: int, x: int, y: int) -> Tuple[int, int]:
    """Put the pointer at a point inside the game's client area."""
    sx, sy = client_to_screen(hwnd, x, y)
    user32.SetCursorPos(int(sx), int(sy))
    return sx, sy


def _mouse_event(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = 0  # INPUT_MOUSE
    inp.mi = MOUSEINPUT(dx=dx, dy=dy, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=None)
    return inp


def move_mouse_relative(dx: int, dy: int, settle: float = 0.05,
                        hwnd: Optional[int] = None) -> None:
    """Nudge the pointer by a relative delta, the way a physical mouse does.

    SetCursorPos does NOT move Fallout 2's cursor: the game captures the mouse
    and recentres it every frame (get_mouse_x/y reports dead centre forever),
    which is normal for DirectInput's exclusive mode. DirectInput consumes
    *relative* device motion, so this is the only form it reacts to.
    """
    ev = _mouse_event(MOUSEEVENTF_MOVE, dx, dy)
    user32.SendInput(1, ctypes.byref(ev), ctypes.sizeof(INPUT))
    # Re-centre the Windows cursor afterwards so these deltas cannot accumulate
    # into a drift towards a window edge. See park_pointer.
    if hwnd is not None:
        park_pointer(hwnd)
    time.sleep(settle)


def park_pointer(hwnd: int) -> None:
    """Put the *Windows* cursor back in the middle of the game window.

    Fallout tracks its own cursor from relative DirectInput motion and ignores
    SetCursorPos entirely, so this does not disturb where the game thinks the
    pointer is -- verified live: the game still reported (569,346) either side
    of a park.

    What it prevents is the Windows cursor drifting to a window edge. The engine
    scrolls the map while the pointer sits near one, so the mod's own relative
    moves would eventually push the real cursor into that zone and the world
    would start sliding. The pointer then stands still while the map moves
    underneath it: the hex under a stationary pointer marched 17687, 17888,
    18289, 18490, 18891 over two seconds, so every aimed click landed on a hex
    that had since moved on, and one of them found the interface bar's OPTIONS
    button and opened the escape menu over the game.
    """
    w, h = client_size(hwnd)
    sx, sy = client_to_screen(hwnd, w // 2, h // 2)
    user32.SetCursorPos(int(sx), int(sy))


# How long a held modifier gets to register before the button goes down.
MODIFIER_LEAD = 0.18


def mouse_click_with(modifier, button: str = "left", **kwargs) -> None:
    """Click while holding one or more keys down.

    Used for the inventory's move-without-dragging modifiers, and it needs
    both of them at once. sfall has two settings here and they solve different
    halves of the same problem: `ItemMoveSkipDragKey` (left Ctrl) turns a click
    into a move so nothing has to be dragged, and `ItemFastMoveKey` (left
    Shift) moves the whole stack rather than opening the "Move Items" window to
    ask how many.

    Ctrl alone is not enough, which was measured rather than assumed: a
    Ctrl+click on an item in the barter window opened the quantity picker --
    a 259x162 panel with up, down, Done and Cancel -- and the item did not
    move. sfall's own note says the two "can be mapped to the same key for a
    combined effect", which is the same statement read the other way round.

    Every key is released in a `finally`, because a Ctrl left stuck down would
    silently change what every later keystroke means -- sfall binds Ctrl plus
    the numpad to the game speed controls, which is exactly the numpad this
    mod's hex cursor lives on.
    """
    names = [modifier] if isinstance(modifier, str) else list(modifier)
    for name in names:
        if name not in DIK:
            raise ValueError("unknown modifier {!r}".format(name))
    events = [DIK[name] for name in names]
    for scancode, extended in events:
        user32.SendInput(1, ctypes.byref(_key_event(scancode, extended, False)),
                         ctypes.sizeof(INPUT))
    # Give the engine time to notice the keys are down BEFORE the button goes
    # down. Fallout's input loop is slow -- the whole `settle` argument on tap()
    # exists because of it -- and a modifier pressed thirty milliseconds ahead
    # of the click was not registered at all: the click fell through as an
    # ordinary one and picked the item up into a drag instead of moving it.
    time.sleep(MODIFIER_LEAD)
    try:
        mouse_click(button, **kwargs)
    finally:
        for scancode, extended in reversed(events):
            user32.SendInput(1, ctypes.byref(_key_event(scancode, extended, True)),
                             ctypes.sizeof(INPUT))
        time.sleep(0.03)


def mouse_click(button: str = "left", hold: float = 0.06, settle: float = 0.25) -> None:
    """Click at the pointer's current position.

    Sent through SendInput rather than PostMessage: Fallout 2 reads input via
    DirectInput, which ignores window messages entirely.
    """
    if button == "left":
        down, up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    elif button == "right":
        down, up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    else:
        raise ValueError("button must be 'left' or 'right'")

    ev = _mouse_event(down)
    user32.SendInput(1, ctypes.byref(ev), ctypes.sizeof(INPUT))
    time.sleep(hold)
    ev = _mouse_event(up)
    user32.SendInput(1, ctypes.byref(ev), ctypes.sizeof(INPUT))
    time.sleep(settle)


def mouse_down(button: str = "left") -> None:
    """Press and hold. The other half of a drag."""
    flags = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
    ev = _mouse_event(flags)
    user32.SendInput(1, ctypes.byref(ev), ctypes.sizeof(INPUT))


def mouse_up(button: str = "left") -> None:
    """Release. Always call this, even on a failed drag -- a button left down
    leaves the game holding an item nobody can see."""
    flags = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
    ev = _mouse_event(flags)
    user32.SendInput(1, ctypes.byref(ev), ctypes.sizeof(INPUT))


def require_focus(hwnd: int) -> None:
    """Ensure the game is foreground, or raise. Call before every keystroke."""
    if is_foreground(hwnd):
        return
    if not focus_window(hwnd):
        raise FocusLost(
            "game window 0x{:X} is not in the foreground; keystrokes would go "
            "to whatever is (often this terminal). Aborting rather than "
            "recording bad data.".format(hwnd)
        )


def guarded_tap(hwnd: int, key: str, **kwargs) -> None:
    """tap(), but verified to land in the game window."""
    require_focus(hwnd)
    tap(key, **kwargs)


def guarded_click(hwnd: int, button: str = "left", **kwargs) -> None:
    """mouse_click(), but verified to land in the game window.

    The unguarded version silently sent a click to whatever window happened to
    hold focus -- the terminal, in practice -- which looked exactly like "the
    game ignored our click" and cost a round of debugging. Any synthetic input
    needs the same precondition check as a keystroke.
    """
    require_focus(hwnd)
    mouse_click(button, **kwargs)


def guarded_click_with(hwnd: int, modifier: str, button: str = "left", **kwargs) -> None:
    """mouse_click_with(), but verified to land in the game window."""
    require_focus(hwnd)
    mouse_click_with(modifier, button, **kwargs)
