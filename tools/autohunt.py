#!/usr/bin/env python3
"""Automated engine-symbol hunter.

The interactive harness (f2mem.py) assumes someone can read its output and
coordinate keypresses by eye. This tool does the whole loop by itself: it
focuses the game, sends its own keystrokes, captures memory around each one,
and narrows to the addresses that moved exactly the way the keypress should
have moved them. Then it proves the survivors by predicting several moves
ahead and checking.

Only navigation keys are sent by default (Up/Down move the selection and
change nothing about the character), so a run is non-destructive.

    python tools/autohunt.py probe
    python tools/autohunt.py hunt --key down --delta 1 --name char_editor_selected
    python tools/autohunt.py verify
    python tools/autohunt.py snapshot
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fallout2_access.memory import (  # noqa: E402
    FALLOUT_EXE_NAMES,
    Process,
    ProcessNotFound,
    TYPES,
    ValueScan,
)
from fallout2_access.input import (  # noqa: E402
    DIK,
    find_game_window,
    focus_window,
    is_foreground,
    tap,
    tap_many,
    window_title,
)

SYMBOLS_PATH = os.path.join(_ROOT, "fallout2_access", "offsets", "found.json")


def fmt(addr: int) -> str:
    return "0x{:08X}".format(addr)


def load_symbols() -> Dict[str, dict]:
    try:
        with open(SYMBOLS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_symbols(symbols: Dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(SYMBOLS_PATH), exist_ok=True)
    with open(SYMBOLS_PATH, "w", encoding="utf-8") as fh:
        json.dump(symbols, fh, indent=2, sort_keys=True)
        fh.write("\n")


class Session:
    def __init__(self) -> None:
        self.proc = Process.attach(FALLOUT_EXE_NAMES)
        self.module = self.proc.main_module()
        self.hwnd = find_game_window(self.proc.pid)
        if self.hwnd is None:
            raise RuntimeError(
                "attached to pid {} but found no visible window for it".format(
                    self.proc.pid
                )
            )
        print(
            "attached  pid {}  window {!r}  module {} at {}".format(
                self.proc.pid, window_title(self.hwnd), self.module.name, fmt(self.module.base)
            )
        )

    def focus(self) -> bool:
        ok = focus_window(self.hwnd)
        if not ok:
            print(
                "WARNING could not bring the game to the foreground; "
                "keystrokes will not reach it"
            )
        return ok


def cmd_probe(args) -> int:
    """Is input reaching the game at all, and what moves when we press a key?"""
    session = Session()
    if not session.focus():
        return 2
    time.sleep(0.3)

    scan = ValueScan(session.proc, None, args.type)
    print("haystack {:,} bytes ({})".format(scan.haystack_bytes, args.type))
    scan.baseline()

    print("sending {!r} x{}".format(args.key, args.count))
    tap_many(args.key, args.count)

    changed = scan.changed()
    print("{} addresses changed".format(changed))

    if changed == 0:
        print(
            "\nNOTHING CHANGED. Either the keystroke never reached the game, or\n"
            "the current screen ignores that key. Check the game is focused and\n"
            "that you are on a screen where {!r} does something.".format(args.key)
        )
        return 1

    # Small ints that moved are the interesting ones -- selection indices,
    # counters, stat values. Huge deltas are timers and render state.
    small = [(a, v) for a, v in scan.items(0) if -200 <= v <= 200]
    print("{} of them hold a small int (-200..200):".format(len(small)))
    for addr, value in small[:25]:
        print("  {}  {}".format(fmt(addr), value))
    if len(small) > 25:
        print("  ... {} more".format(len(small) - 25))
    return 0


def hunt(
    session: Session,
    key: str,
    delta: int,
    vtype: str,
    rounds: int,
    settle: float,
) -> List[int]:
    """Narrow to addresses that move by `delta` every time `key` is pressed."""
    scan = ValueScan(session.proc, None, vtype)
    print("haystack {:,} bytes ({})".format(scan.haystack_bytes, vtype))

    # Step away from any list boundary first, so the value can actually move
    # in both directions without clamping or wrapping.
    opposite = {"down": "up", "up": "down", "right": "left", "left": "right"}
    print("centring: 3x {!r}".format(key))
    tap_many(key, 3, settle=settle)

    scan.baseline()
    print("baseline captured ({:,} values)".format(scan.count))

    sequence: List[Tuple[str, int]] = []
    for i in range(rounds):
        # Alternate direction every couple of rounds to avoid running off the
        # end of the list, and to prove the value tracks both ways.
        if i and i % 2 == 0 and key in opposite:
            sequence.append((opposite[key], -delta))
        else:
            sequence.append((key, delta))

    for i, (k, d) in enumerate(sequence, 1):
        tap(k, settle=settle)
        n = scan.delta(d)
        print("round {}: {!r} delta {:+d} -> {} candidate(s)".format(i, k, d, n))
        if n == 0:
            print(
                "\nno candidate survived. the value may not move by exactly {:+d}, "
                "or the screen changed under us.".format(d)
            )
            return []
        if n <= 4 and i >= 3:
            break

    return scan.addresses()


def verify_candidate(
    session: Session, addr: int, key: str, delta: int, vtype: str, steps: int = 3
) -> Tuple[bool, str]:
    """Predict several moves ahead and check the address actually follows."""
    _, size, signed = TYPES[vtype]
    opposite = {"down": "up", "up": "down", "right": "left", "left": "right"}

    def read() -> Optional[int]:
        raw = session.proc.read(addr, size)
        if raw is None or len(raw) != size:
            return None
        return int.from_bytes(raw, "little", signed=signed)

    start = read()
    if start is None:
        return False, "unreadable"

    tap_many(key, steps)
    after = read()
    if after is None:
        return False, "unreadable after {}x{}".format(steps, key)
    expected = start + delta * steps
    if after != expected:
        return False, "expected {} after {}x{}, got {}".format(expected, steps, key, after)

    back = opposite.get(key)
    if back:
        tap_many(back, steps)
        restored = read()
        if restored != start:
            return False, "did not return to {} after {}x{} (got {})".format(
                start, steps, back, restored
            )

    return True, "tracked {} -> {} -> {}".format(start, expected, start)


def cmd_hunt(args) -> int:
    session = Session()
    if not session.focus():
        return 2
    time.sleep(0.3)

    addrs = hunt(session, args.key, args.delta, args.type, args.rounds, args.settle)
    if not addrs:
        return 1

    print("\n{} surviving candidate(s); verifying".format(len(addrs)))
    confirmed: List[int] = []
    for addr in addrs:
        ok, why = verify_candidate(session, addr, args.key, args.delta, args.type)
        print("  {}  {}  {}".format(fmt(addr), "PASS" if ok else "fail", why))
        if ok:
            confirmed.append(addr)

    if not confirmed:
        print("\nnothing passed verification.")
        return 1

    print("\nCONFIRMED:")
    for addr in confirmed:
        print(
            "  {}  rva 0x{:X}".format(addr and fmt(addr), addr - session.module.base)
        )
        dump_neighbourhood(session, addr, args.type)

    if args.name:
        if len(confirmed) > 1:
            print(
                "\nnot recording {!r}: {} addresses passed, so the signal is "
                "ambiguous. inspect the dumps above and record the right one "
                "with f2mem.py's `name`.".format(args.name, len(confirmed))
            )
            return 1
        symbols = load_symbols()
        symbols[args.name] = {
            "addr": confirmed[0],
            "rva": confirmed[0] - session.module.base,
            "type": args.type,
            "note": "auto-confirmed: {} moves {:+d} per {!r}".format(
                args.name, args.delta, args.key
            ),
        }
        save_symbols(symbols)
        print("\nrecorded {} = {}".format(args.name, fmt(confirmed[0])))
    return 0


def dump_neighbourhood(session: Session, addr: int, vtype: str, span: int = 16) -> None:
    """Show the ints around a confirmed address.

    Fallout 2 keeps related state in contiguous arrays, so the neighbours of
    one confirmed symbol are usually the rest of the structure -- this is how
    one hit turns into seven SPECIAL stats.
    """
    _, size, signed = TYPES[vtype]
    start = addr - span * size
    raw = session.proc.read(start, span * 2 * size + size)
    if raw is None:
        return
    print("    neighbourhood ({} values of {}):".format(span * 2 + 1, vtype))
    line: List[str] = []
    for i in range(0, len(raw) - size + 1, size):
        value = int.from_bytes(raw[i : i + size], "little", signed=signed)
        cur = start + i
        mark = "*" if cur == addr else " "
        line.append("{}{:>6}".format(mark, value))
        if len(line) == 8:
            print("      {}  {}".format(fmt(start + i - 7 * size), "".join(line)))
            line = []
    if line:
        print("      {}  {}".format(fmt(start + len(raw) - len(line) * size), "".join(line)))


def cmd_verify(args) -> int:
    session = Session()
    symbols = load_symbols()
    if not symbols:
        print("no symbols recorded yet")
        return 1
    for name in sorted(symbols):
        info = symbols[name]
        vtype = info.get("type", "i32")
        _, size, signed = TYPES.get(vtype, ("i", 4, True))
        raw = session.proc.read(info["addr"], size)
        value = (
            int.from_bytes(raw, "little", signed=signed)
            if raw and len(raw) == size
            else None
        )
        print("  {:<28} {} = {}".format(name, fmt(info["addr"]), value))
    return 0


def cmd_snapshot(args) -> int:
    return cmd_verify(args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="check input reaches the game; list what moved")
    p.add_argument("--key", default="down", choices=sorted(DIK))
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--type", default="i32", choices=sorted(TYPES))
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("hunt", help="narrow to a symbol and prove it")
    p.add_argument("--key", default="down", choices=sorted(DIK))
    p.add_argument("--delta", type=int, default=1, help="expected change per press")
    p.add_argument("--type", default="i32", choices=sorted(TYPES))
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--settle", type=float, default=0.12, help="seconds after each key")
    p.add_argument("--name", help="record the result under this symbol name")
    p.set_defaults(func=cmd_hunt)

    p = sub.add_parser("verify", help="show live values of recorded symbols")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("snapshot", help="alias for verify")
    p.set_defaults(func=cmd_snapshot)

    args = parser.parse_args()
    try:
        return args.func(args)
    except ProcessNotFound as exc:
        print("not attached: {}".format(exc))
        print("start Fallout 2, get to the screen you want to scan, then re-run")
        return 2
    except RuntimeError as exc:
        print("error: {}".format(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
