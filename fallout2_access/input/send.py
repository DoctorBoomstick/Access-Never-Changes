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
    "enter": (0x1C, False),
    "escape": (0x01, False),
    "tab": (0x0F, False),
    "space": (0x39, False),
    "minus": (0x0C, False),
    "plus": (0x0D, False),  # the '=' key
    "a": (0x1E, False),
    "b": (0x30, False),
    "c": (0x2E, False),
    "d": (0x20, False),
    "m": (0x32, False),
    "n": (0x31, False),
    "o": (0x18, False),
    "s": (0x1F, False),
    "t": (0x14, False),
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


def find_game_window(pid: int) -> Optional[int]:
    """The main visible top-level window belonging to `pid`."""
    found: List[int] = []

    def callback(hwnd, _lparam):
        wnd_pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wnd_pid))
        if wnd_pid.value == pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0] if found else None


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
