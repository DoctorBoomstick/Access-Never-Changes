"""Screen reader output, tried in order of preference.

Carried over from the original bridge.py, which had this part right. The one
non-obvious detail worth preserving: the NVDA controller DLL must be loaded by
absolute path -- a bare filename fails depending on the working directory.
"""

from __future__ import annotations

import ctypes
import os
import sys
from typing import List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Speaker:
    name = "none"

    def speak(self, text: str, interrupt: bool = True) -> None:
        raise NotImplementedError

    def silence(self) -> None:
        pass


class AO2Speaker(Speaker):
    name = "accessible_output2"

    def __init__(self) -> None:
        from accessible_output2.outputs.auto import Auto  # type: ignore

        self._out = Auto()

    def speak(self, text: str, interrupt: bool = True) -> None:
        self._out.speak(text, interrupt=interrupt)

    def silence(self) -> None:
        try:
            self._out.silence()
        except Exception:
            pass


class NVDASpeaker(Speaker):
    name = "NVDA"

    def __init__(self) -> None:
        last: Optional[Exception] = None
        for dll in ("nvdaControllerClient64.dll", "nvdaControllerClient32.dll"):
            path = os.path.join(_ROOT, dll)
            if not os.path.exists(path):
                continue
            try:
                lib = ctypes.windll.LoadLibrary(path)
            except OSError as exc:
                last = exc
                continue
            if lib.nvdaController_testIfRunning() != 0:
                last = RuntimeError("NVDA is not running")
                continue
            self._lib = lib
            return
        raise RuntimeError(str(last) if last else "nvdaControllerClient DLL not found")

    def speak(self, text: str, interrupt: bool = True) -> None:
        if interrupt:
            self._lib.nvdaController_cancelSpeech()
        self._lib.nvdaController_speakText(text)

    def silence(self) -> None:
        self._lib.nvdaController_cancelSpeech()


class SAPISpeaker(Speaker):
    name = "SAPI"
    _ASYNC = 0x1
    _PURGE = 0x2

    def __init__(self) -> None:
        import win32com.client  # type: ignore

        self._voice = win32com.client.Dispatch("SAPI.SpVoice")

    def speak(self, text: str, interrupt: bool = True) -> None:
        flags = self._ASYNC | (self._PURGE if interrupt else 0)
        self._voice.Speak(text, flags)

    def silence(self) -> None:
        self._voice.Speak("", self._ASYNC | self._PURGE)


class ConsoleSpeaker(Speaker):
    """Fallback that prints. Keeps the tool usable for debugging with no TTS."""

    name = "console"

    def speak(self, text: str, interrupt: bool = True) -> None:
        print("[say] {}".format(text), flush=True)


def get_speaker(prefer: Optional[str] = None, allow_console: bool = True) -> Speaker:
    order = [NVDASpeaker, AO2Speaker, SAPISpeaker]
    if prefer:
        wanted = prefer.lower()
        order.sort(key=lambda c: c.name.lower() != wanted)

    errors: List[str] = []
    for cls in order:
        try:
            speaker = cls()
            print("[speech] using {}".format(speaker.name), flush=True)
            return speaker
        except Exception as exc:
            errors.append("  {}: {}".format(cls.name, exc))

    for line in errors:
        print(line, file=sys.stderr)
    if allow_console:
        print("[speech] no screen reader available; printing instead", flush=True)
        return ConsoleSpeaker()
    raise RuntimeError("no speech backend available")
