#!/usr/bin/env python3
"""Walk every character-editor section and record what each index actually is.

Uses the engine's own name/description pointers, so the resulting map is in the
game's words -- correct in any language, and automatically right for content
mods that replace the text.

Writes fallout2_access/offsets/editor_items.json.

Navigation only -- nothing here alters the character.

    python tools/mapitems.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fallout2_access.memory import FALLOUT_EXE_NAMES, Process, ProcessNotFound  # noqa: E402
from fallout2_access.input import find_game_window, focus_window, tap  # noqa: E402

# Confirmed by tools/autohunt.py and scratch differential scans.
SEL_ADDR = 0x005709EC
NAME_PTR = 0x005705B8
DESC_PTR = 0x005705CC

OUT_PATH = os.path.join(_ROOT, "fallout2_access", "offsets", "editor_items.json")


class Editor:
    def __init__(self, proc: Process, settle: float) -> None:
        self.proc = proc
        self.settle = settle

    def selection(self) -> Optional[int]:
        return self.proc.read_i32(SEL_ADDR)

    def _text(self, ptr_addr: int, limit: int = 400) -> Optional[str]:
        ptr = self.proc.read_u32(ptr_addr)
        if not ptr or not (0x00010000 < ptr < 0x7FFF0000):
            return None
        return self.proc.read_cstring(ptr, limit)

    def name(self) -> Optional[str]:
        return self._text(NAME_PTR, 96)

    def description(self) -> Optional[str]:
        return self._text(DESC_PTR, 400)

    def snapshot(self) -> Dict[str, object]:
        """Read index and text together, retrying until two reads agree."""
        for _ in range(6):
            first = (self.selection(), self.name())
            time.sleep(0.05)
            second = (self.selection(), self.name())
            if first == second and first[0] is not None:
                return {
                    "index": first[0],
                    "name": first[1],
                    "description": self.description(),
                }
        return {"index": self.selection(), "name": self.name(), "description": self.description()}

    def press(self, key: str) -> None:
        tap(key, settle=self.settle)


def walk_section(ed: Editor, max_items: int = 60) -> List[Dict[str, object]]:
    start = ed.snapshot()
    items = [start]
    seen = {start["index"]}
    for _ in range(max_items):
        ed.press("down")
        snap = ed.snapshot()
        if snap["index"] in seen:
            break
        seen.add(snap["index"])
        items.append(snap)
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", type=float, default=0.16)
    ap.add_argument("--sections", type=int, default=6)
    args = ap.parse_args()

    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except ProcessNotFound as exc:
        print("not attached: {}".format(exc))
        return 2
    hwnd = find_game_window(proc.pid)
    if hwnd is None or not focus_window(hwnd):
        print("could not focus the game window")
        return 2

    ed = Editor(proc, args.settle)
    print("selection 0x{:08X}  name 0x{:08X}  desc 0x{:08X}".format(
        SEL_ADDR, NAME_PTR, DESC_PTR))

    sections: Dict[str, List[Dict[str, object]]] = {}
    for i in range(args.sections):
        ed.press("tab")
        head = ed.snapshot()
        key = str(head["index"])
        if key in sections:
            print("\nsection {} already seen -- all sections covered".format(key))
            break
        print("\n--- section starting {} ---".format(key))
        items = walk_section(ed)
        sections[key] = items
        for item in items:
            desc = item.get("description") or ""
            if len(desc) > 60:
                desc = desc[:57] + "..."
            print("  {:>3}  {:<26} {}".format(item["index"], item.get("name"), desc))

    payload = {
        "symbols": {
            "char_editor_selected": SEL_ADDR,
            "char_editor_name_ptr": NAME_PTR,
            "char_editor_desc_ptr": DESC_PTR,
        },
        "module_base": proc.main_module().base,
        "sections": sections,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    total = sum(len(v) for v in sections.values())
    print("\nwrote {} items across {} sections to {}".format(
        total, len(sections), os.path.relpath(OUT_PATH, _ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
