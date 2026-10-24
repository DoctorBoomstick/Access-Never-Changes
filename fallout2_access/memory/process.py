"""Attach to a running process and read its memory.

The target (fallout2.exe) is a 32-bit process; this code is expected to run
under 64-bit Python. ReadProcessMemory is bitness-agnostic, but module
enumeration is not -- CreateToolhelp32Snapshot needs TH32CS_SNAPMODULE32 for a
WOW64 target and is documented as flaky, so psapi's EnumProcessModulesEx is
kept as a fallback.

Read-only by design: we never open the process for writing. Everything the
accessibility layer needs is observation.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
from typing import Dict, Iterator, List, NamedTuple, Optional, Sequence

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

FALLOUT_EXE_NAMES = ("fallout2.exe", "fallout2hr.exe")

# -- constants ---------------------------------------------------------------

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008

MEM_COMMIT = 0x1000

PAGE_NOACCESS = 0x01
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE = 0x10
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
PAGE_GUARD = 0x100

_READABLE = frozenset(
    (
        PAGE_READONLY,
        PAGE_READWRITE,
        PAGE_WRITECOPY,
        PAGE_EXECUTE_READ,
        PAGE_EXECUTE_READWRITE,
        PAGE_EXECUTE_WRITECOPY,
    )
)
_WRITABLE = frozenset(
    (PAGE_READWRITE, PAGE_WRITECOPY, PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY)
)

LIST_MODULES_32BIT = 0x01
ERROR_BAD_LENGTH = 24
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH = 260

# Top of the user-mode address space on x64. A 32-bit target's walk terminates
# well below this on its own.
MAX_USER_ADDRESS = 0x7FFFFFFF0000


class ProcessNotFound(Exception):
    """No running process matched the requested name."""


# -- win32 structures --------------------------------------------------------


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * MAX_PATH),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wt.DWORD),
        ("hModule", ctypes.c_void_p),
        ("szModule", ctypes.c_wchar * 256),
        ("szExePath", ctypes.c_wchar * MAX_PATH),
    ]


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    """Native (64-bit) layout -- VirtualQueryEx returns this shape to us."""

    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wt.DWORD),
        ("__alignment1", wt.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
        ("__alignment2", wt.DWORD),
    ]


class MODULEINFO(ctypes.Structure):
    _fields_ = [
        ("lpBaseOfDll", ctypes.c_void_p),
        ("SizeOfImage", wt.DWORD),
        ("EntryPoint", ctypes.c_void_p),
    ]


kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.VirtualQueryEx.restype = ctypes.c_size_t


# -- data ---------------------------------------------------------------------


class Module(NamedTuple):
    name: str
    base: int
    size: int
    path: str

    @property
    def end(self) -> int:
        return self.base + self.size

    def __repr__(self) -> str:  # pragma: no cover - display only
        return "<Module {} 0x{:08X}+0x{:X}>".format(self.name, self.base, self.size)


class Region(NamedTuple):
    base: int
    size: int
    protect: int

    @property
    def end(self) -> int:
        return self.base + self.size

    @property
    def writable(self) -> bool:
        return (self.protect & 0xFF) in _WRITABLE


# -- process ------------------------------------------------------------------


def find_pids(names: Sequence[str]) -> List[int]:
    """Return PIDs of running processes whose image name matches (case-insensitive)."""
    wanted = {n.lower() for n in names}
    pids: List[int] = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return pids
        while True:
            if entry.szExeFile.lower() in wanted:
                pids.append(entry.th32ProcessID)
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return pids


kernel32.QueryFullProcessImageNameW.argtypes = [
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL


class Process:
    """A read-only handle onto a running process."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
        )
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = handle
        self._modules: Optional[Dict[str, Module]] = None

    # -- lifecycle ----------------------------------------------------------

    @classmethod
    def attach(cls, names: Sequence[str] = FALLOUT_EXE_NAMES) -> "Process":
        pids = find_pids(names)
        if not pids:
            raise ProcessNotFound(
                "no running process named {}".format(" or ".join(names))
            )
        return cls(pids[0])

    def close(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None
        if getattr(self, "_write_handle", None):
            kernel32.CloseHandle(self._write_handle)
            self._write_handle = None

    def __enter__(self) -> "Process":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def exe_path(self) -> str:
        """Full path to the running executable, or "" if it cannot be read.

        This is how the mod finds the game's folder, and it has to be asked of
        the process rather than assumed: the mod used to live inside the game
        directory and worked out paths from its own location, which broke the
        moment it moved into a repo of its own. Asking the process is also the
        only answer that stays right for a GOG install, a second copy, or a
        game started from somewhere unexpected.
        """
        if not self._handle:
            return ""
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(
            self._handle, 0, buf, ctypes.byref(size)
        ):
            return buf.value
        return ""

    @property
    def directory(self) -> str:
        """The folder the game is installed in."""
        path = self.exe_path
        return os.path.dirname(path) if path else ""

    @property
    def alive(self) -> bool:
        if not self._handle:
            return False
        code = wt.DWORD()
        if not kernel32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE

    # -- modules ------------------------------------------------------------

    def modules(self, refresh: bool = False) -> Dict[str, Module]:
        if self._modules is None or refresh:
            mods = self._modules_toolhelp()
            if not mods:
                mods = self._modules_psapi()
            self._modules = mods
        return self._modules

    def main_module(self) -> Module:
        """The Fallout 2 executable's module."""
        mods = self.modules()
        for name in FALLOUT_EXE_NAMES:
            if name in mods:
                return mods[name]
        # Fall back to whichever module is loaded at the classic 32-bit image base.
        for mod in mods.values():
            if mod.base == 0x00400000:
                return mod
        raise ProcessNotFound("could not identify the Fallout 2 main module")

    def module_list(self) -> List[Module]:
        """Every loaded module, duplicate names included.

        `modules()` keys by base name, which is fine right up until two
        different files share one -- and sfall is exactly that case. Its
        ddraw.dll loads Windows' own ddraw.dll to forward DirectDraw calls to,
        so the process has two modules called "ddraw.dll" and the dict keeps
        whichever the walk saw last. That silently returned
        C:\\WINDOWS\\SysWOW64\\ddraw.dll, and a search for sfall's variables
        inside it found nothing at all -- which reads exactly like "sfall did
        not react" and is really "we looked in the wrong file".

        Ordered as the walk found them; callers that care which copy they want
        must say so, usually by path.
        """
        return list(self._module_entries())

    def module_at(self, name: str, directory: str) -> Optional[Module]:
        """The module with this base name loaded from under `directory`.

        The way to ask for sfall rather than Windows' DirectDraw.
        """
        want = name.lower()
        root = os.path.normcase(os.path.abspath(directory))
        for mod in self.module_list():
            if mod.name.lower() != want:
                continue
            path = os.path.normcase(os.path.abspath(mod.path or ""))
            if path.startswith(root):
                return mod
        return None

    def _module_entries(self) -> List[Module]:
        # Documented as returning ERROR_BAD_LENGTH while the target is still
        # loading its module list; MSDN's advice is simply to retry.
        for _ in range(8):
            snap = kernel32.CreateToolhelp32Snapshot(
                TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, self.pid
            )
            if snap != INVALID_HANDLE_VALUE:
                break
            if ctypes.get_last_error() != ERROR_BAD_LENGTH:
                return []
        else:
            return []

        out: List[Module] = []
        try:
            entry = MODULEENTRY32W()
            entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
            if not kernel32.Module32FirstW(snap, ctypes.byref(entry)):
                return []
            while True:
                out.append(Module(
                    name=entry.szModule,
                    base=entry.modBaseAddr or 0,
                    size=entry.modBaseSize,
                    path=entry.szExePath,
                ))
                if not kernel32.Module32NextW(snap, ctypes.byref(entry)):
                    break
        finally:
            kernel32.CloseHandle(snap)
        return out

    def _modules_toolhelp(self) -> Dict[str, Module]:
        return {m.name.lower(): m for m in self._module_entries()}

    def _modules_psapi(self) -> Dict[str, Module]:
        needed = wt.DWORD()
        arr_type = ctypes.c_void_p * 1024
        mods = arr_type()
        ok = psapi.EnumProcessModulesEx(
            self._handle,
            ctypes.byref(mods),
            ctypes.sizeof(mods),
            ctypes.byref(needed),
            LIST_MODULES_32BIT,
        )
        if not ok:
            return {}
        count = min(needed.value // ctypes.sizeof(ctypes.c_void_p), 1024)
        out: Dict[str, Module] = {}
        for i in range(count):
            hmod = mods[i]
            name_buf = ctypes.create_unicode_buffer(MAX_PATH)
            psapi.GetModuleBaseNameW(self._handle, hmod, name_buf, MAX_PATH)
            path_buf = ctypes.create_unicode_buffer(MAX_PATH)
            psapi.GetModuleFileNameExW(self._handle, hmod, path_buf, MAX_PATH)
            info = MODULEINFO()
            psapi.GetModuleInformation(
                self._handle, hmod, ctypes.byref(info), ctypes.sizeof(info)
            )
            out[name_buf.value.lower()] = Module(
                name=name_buf.value,
                base=info.lpBaseOfDll or 0,
                size=info.SizeOfImage,
                path=path_buf.value,
            )
        return out

    # -- regions ------------------------------------------------------------

    def regions(
        self, writable_only: bool = False, limit: int = MAX_USER_ADDRESS
    ) -> Iterator[Region]:
        """Walk committed, readable regions of the target's address space.

        The default limit spans the whole user-mode range. For a 32-bit target
        VirtualQueryEx simply stops returning results past 0x7FFFFFFF, so the
        walk ends on its own -- no need to special-case bitness here.
        """
        addr = 0
        mbi = MEMORY_BASIC_INFORMATION64()
        size = ctypes.sizeof(mbi)
        while addr < limit:
            got = kernel32.VirtualQueryEx(
                self._handle, ctypes.c_void_p(addr), ctypes.byref(mbi), size
            )
            if not got:
                break
            region_size = int(mbi.RegionSize)
            if region_size <= 0:
                break
            protect = mbi.Protect & 0xFF
            if (
                mbi.State == MEM_COMMIT
                and protect in _READABLE
                and not (mbi.Protect & PAGE_GUARD)
                and (not writable_only or protect in _WRITABLE)
            ):
                yield Region(int(mbi.BaseAddress), region_size, mbi.Protect)
            addr = int(mbi.BaseAddress) + region_size
        return

    def module_regions(self, module: Optional[Module] = None) -> List[Region]:
        """Committed writable regions inside a module's image.

        This is where the engine's global variables live -- the char editor's
        state included -- so it is the right haystack for a first scan.
        """
        mod = module or self.main_module()
        out: List[Region] = []
        for region in self.regions(writable_only=True):
            if region.end > mod.base and region.base < mod.end:
                base = max(region.base, mod.base)
                end = min(region.end, mod.end)
                out.append(Region(base, end - base, region.protect))
        return out

    # -- reads --------------------------------------------------------------

    def read(self, addr: int, size: int) -> Optional[bytes]:
        """Read `size` bytes. Returns None if the read fails outright."""
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(
            self._handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)
        )
        if not ok or got.value == 0:
            return None
        return buf.raw[: got.value]

    def read_chunked(self, addr: int, size: int, chunk: int = 0x10000) -> bytes:
        """Read a range, tolerating unreadable pages by zero-filling them.

        Region walks can race with the game freeing memory; a partial result is
        far more useful here than an exception.
        """
        out = bytearray()
        pos = 0
        while pos < size:
            want = min(chunk, size - pos)
            got = self.read(addr + pos, want)
            if got is None or len(got) != want:
                if want <= 0x1000:
                    out.extend(got if got else b"\x00" * want)
                    pos += want
                    continue
                # Split and retry so one bad page doesn't cost us the region.
                half = want // 2
                first = self.read_chunked(addr + pos, half, chunk)
                second = self.read_chunked(addr + pos + half, want - half, chunk)
                out.extend(first)
                out.extend(second)
                pos += want
                continue
            out.extend(got)
            pos += want
        return bytes(out)

    # -- writes -------------------------------------------------------------
    #
    # **One customer, deliberately.** Everything else in the mod changes the
    # game by pressing its keys and clicking its buttons, so the engine's own
    # rules apply. The preferences screen is the exception: its sliders and
    # knobs are mouse drags with no keys at all, while the values they set are
    # plain working copies the screen keeps until Done saves and applies them
    # (game/prefs.py). Writing those is setting the slider, with the screen's
    # own Done and Cancel still deciding whether it sticks.
    #
    # A second handle, opened on first use, so a mod that never writes never
    # holds write access to the game.

    def write(self, addr: int, data: bytes) -> bool:
        if getattr(self, "_write_handle", None) is None:
            self._write_handle = kernel32.OpenProcess(
                PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, self.pid)
            if not self._write_handle:
                self._write_handle = None
                return False
        done = ctypes.c_size_t(0)
        ok = kernel32.WriteProcessMemory(
            self._write_handle, ctypes.c_void_p(addr), data, len(data),
            ctypes.byref(done))
        return bool(ok) and done.value == len(data)

    def read_i32(self, addr: int) -> Optional[int]:
        raw = self.read(addr, 4)
        return int.from_bytes(raw, "little", signed=True) if raw and len(raw) == 4 else None

    def read_u32(self, addr: int) -> Optional[int]:
        raw = self.read(addr, 4)
        return int.from_bytes(raw, "little", signed=False) if raw and len(raw) == 4 else None

    def read_i16(self, addr: int) -> Optional[int]:
        raw = self.read(addr, 2)
        return int.from_bytes(raw, "little", signed=True) if raw and len(raw) == 2 else None

    def read_u8(self, addr: int) -> Optional[int]:
        raw = self.read(addr, 1)
        return raw[0] if raw else None

    def read_ptr(self, addr: int) -> Optional[int]:
        """Read a 32-bit pointer out of the target."""
        return self.read_u32(addr)

    def read_cstring(self, addr: int, max_len: int = 256, encoding: Optional[str] = None) -> Optional[str]:
        """Read a NUL-terminated string, stopping safely at page boundaries.

        ReadProcessMemory fails for the *whole* range if any part of it is
        unmapped, so a naive fixed-size read silently returns nothing for any
        string that happens to sit near the end of a committed region. That bug
        blanked 'Small Guns' -- 24 bytes from a page edge -- and would have
        produced unpredictable gaps all over the mod.

        So: read page by page, and stop as soon as the next page is unreadable.
        The text is decoded in the game's codepage unless `encoding` says otherwise.
        """
        if encoding is None:
            from ..codepage import game
            encoding = game()
        out = bytearray()
        pos = 0
        while pos < max_len:
            cur = addr + pos
            # Never let a single read span a page boundary.
            to_page_end = 0x1000 - (cur & 0xFFF)
            want = min(to_page_end, max_len - pos)
            chunk = self.read(cur, want)
            if chunk is None:
                break
            end = chunk.find(b"\x00")
            if end >= 0:
                out.extend(chunk[:end])
                return bytes(out).decode(encoding, errors="replace")
            out.extend(chunk)
            pos += want
        if not out:
            return None
        return bytes(out).decode(encoding, errors="replace")
