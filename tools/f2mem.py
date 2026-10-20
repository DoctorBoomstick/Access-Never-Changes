#!/usr/bin/env python3
"""Interactive memory harness for the Fallout 2 accessibility mod.

This is the tool we use to *find and prove* engine addresses before any speech
code is written. Nothing downstream is trustworthy until the symbols it
resolves are confirmed against what is actually on screen.

Run it with the game already running:

    python tools/f2mem.py

Then `help`. docs/DEVELOPING.md describes the method.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Dict, List, Optional

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
    find_pattern_all,
)
from fallout2_access.memory.scan import code_regions  # noqa: E402

SYMBOLS_PATH = os.path.join(_ROOT, "fallout2_access", "offsets", "found.json")
POLL_HZ = 12.0


def parse_addr(text: str) -> int:
    text = text.strip().lower()
    if text.startswith("0x"):
        return int(text, 16)
    # Bare tokens are hex: every address we deal with is written that way.
    return int(text, 16)


def parse_value(text: str) -> int:
    text = text.strip().lower()
    if text.startswith("0x"):
        return int(text, 16)
    return int(text, 10)


def fmt_addr(addr: int) -> str:
    return "0x{:08X}".format(addr)


class Harness:
    def __init__(self) -> None:
        self.proc: Optional[Process] = None
        self.scan: Optional[ValueScan] = None
        self.vtype = "i32"
        self.haystack = "module"
        self.symbols: Dict[str, dict] = self._load_symbols()

    # -- symbol store --------------------------------------------------------

    def _load_symbols(self) -> Dict[str, dict]:
        try:
            with open(SYMBOLS_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _save_symbols(self) -> None:
        os.makedirs(os.path.dirname(SYMBOLS_PATH), exist_ok=True)
        with open(SYMBOLS_PATH, "w", encoding="utf-8") as fh:
            json.dump(self.symbols, fh, indent=2, sort_keys=True)
            fh.write("\n")

    # -- attach --------------------------------------------------------------

    def attach(self) -> bool:
        try:
            self.proc = Process.attach(FALLOUT_EXE_NAMES)
        except ProcessNotFound as exc:
            print("not attached: {}".format(exc))
            print("start Fallout 2 first, then run: attach")
            return False
        except OSError as exc:
            print("could not open the process: {}".format(exc))
            return False

        mod = self.proc.main_module()
        regions = self.proc.module_regions(mod)
        total = sum(r.size for r in regions)
        print("attached to pid {}".format(self.proc.pid))
        print("  module     {} at {} size 0x{:X}".format(mod.name, fmt_addr(mod.base), mod.size))
        print("  writable   {} regions, {:,} bytes".format(len(regions), total))
        if mod.base != 0x00400000:
            print("  NOTE image base is not 0x00400000 -- offsets will need rebasing")
        self.scan = None
        return True

    def require(self) -> bool:
        if self.proc is None or not self.proc.alive:
            print("not attached (or the game has exited). run: attach")
            return False
        return True

    def _regions(self):
        assert self.proc is not None
        if self.haystack == "all":
            return [r for r in self.proc.regions(writable_only=True)]
        return self.proc.module_regions()

    def ensure_scan(self) -> Optional[ValueScan]:
        if not self.require():
            return None
        if self.scan is None or self.scan.vtype != self.vtype:
            self.scan = ValueScan(self.proc, self._regions(), self.vtype)
            print(
                "new {} scan over {:,} bytes".format(self.vtype, self.scan.haystack_bytes)
            )
        return self.scan

    # -- commands ------------------------------------------------------------

    def cmd_info(self) -> None:
        if not self.require():
            return
        assert self.proc is not None
        mods = self.proc.modules(refresh=True)
        mod = self.proc.main_module()
        print("pid {}  main module {} at {}".format(self.proc.pid, mod.name, fmt_addr(mod.base)))
        print("modules loaded: {}".format(len(mods)))
        for name in sorted(mods):
            m = mods[name]
            print("  {:<28} {} +0x{:X}".format(m.name, fmt_addr(m.base), m.size))

    def cmd_regions(self) -> None:
        if not self.require():
            return
        for r in self._regions():
            print("  {} +0x{:<8X} protect 0x{:X}".format(fmt_addr(r.base), r.size, r.protect))

    def cmd_filter(self, op: str, args: List[str]) -> None:
        scan = self.ensure_scan()
        if scan is None:
            return
        t0 = time.time()
        try:
            if op in ("exact", "="):
                n = scan.exact(parse_value(args[0]))
            elif op == "between":
                n = scan.between(parse_value(args[0]), parse_value(args[1]))
            elif op == "changed":
                n = scan.changed()
            elif op == "unchanged":
                n = scan.unchanged()
            elif op == "inc":
                n = scan.increased()
            elif op == "dec":
                n = scan.decreased()
            elif op == "delta":
                n = scan.delta(parse_value(args[0]))
            else:
                print("unknown filter {!r}".format(op))
                return
        except IndexError:
            print("that filter needs an argument")
            return
        except RuntimeError as exc:
            print(exc)
            return
        dt = time.time() - t0
        print("{} candidates  (round {}, {:.1f}s)".format(n, scan.rounds, dt))
        if 0 < n <= 12:
            self.cmd_list(["12"])

    def cmd_baseline(self) -> None:
        scan = self.ensure_scan()
        if scan is None:
            return
        t0 = time.time()
        n = scan.baseline()
        print("baseline captured: {:,} values ({:.1f}s)".format(n, time.time() - t0))
        print("now change the value in game, then run: changed / inc / dec")

    def cmd_list(self, args: List[str]) -> None:
        if self.scan is None:
            print("no scan in progress")
            return
        limit = int(args[0]) if args else 40
        items = self.scan.items(limit)
        if not items:
            print("no candidates ({} total)".format(self.scan.count))
            return
        for addr, value in items:
            print("  {}  {}".format(fmt_addr(addr), value))
        if self.scan.count > len(items):
            print("  ... {} more".format(self.scan.count - len(items)))

    def cmd_reset(self) -> None:
        if self.scan:
            self.scan.reset()
        self.scan = None
        print("scan cleared")

    def cmd_read(self, args: List[str]) -> None:
        if not self.require() or not args:
            return
        assert self.proc is not None
        addr = parse_addr(args[0])
        vtype = args[1] if len(args) > 1 else self.vtype
        if vtype not in TYPES:
            print("unknown type {!r}".format(vtype))
            return
        code, size, signed = TYPES[vtype]
        raw = self.proc.read(addr, size)
        if raw is None:
            print("  {}  <unreadable>".format(fmt_addr(addr)))
            return
        value = int.from_bytes(raw, "little", signed=signed)
        print("  {}  {} ({}) raw {}".format(fmt_addr(addr), value, vtype, raw.hex()))

    def cmd_str(self, args: List[str]) -> None:
        if not self.require() or not args:
            return
        assert self.proc is not None
        addr = parse_addr(args[0])
        length = int(args[1]) if len(args) > 1 else 128
        text = self.proc.read_cstring(addr, length)
        print("  {}  {!r}".format(fmt_addr(addr), text))

    def cmd_deref(self, args: List[str]) -> None:
        """Follow a pointer and show the string it points at."""
        if not self.require() or not args:
            return
        assert self.proc is not None
        addr = parse_addr(args[0])
        ptr = self.proc.read_ptr(addr)
        if not ptr:
            print("  {} -> null".format(fmt_addr(addr)))
            return
        text = self.proc.read_cstring(ptr, 128)
        print("  {} -> {}  {!r}".format(fmt_addr(addr), fmt_addr(ptr), text))

    def cmd_dump(self, args: List[str]) -> None:
        if not self.require() or not args:
            return
        assert self.proc is not None
        addr = parse_addr(args[0])
        length = int(args[1]) if len(args) > 1 else 64
        data = self.proc.read(addr, length)
        if data is None:
            print("  <unreadable>")
            return
        for off in range(0, len(data), 16):
            row = data[off : off + 16]
            hexpart = " ".join("{:02X}".format(b) for b in row)
            asciipart = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
            print("  {}  {:<47}  {}".format(fmt_addr(addr + off), hexpart, asciipart))

    def cmd_aob(self, args: List[str]) -> None:
        if not self.require() or not args:
            return
        assert self.proc is not None
        pattern = " ".join(args)
        t0 = time.time()
        try:
            hits = find_pattern_all(self.proc, pattern, code_regions(self.proc))
        except ValueError as exc:
            print("bad pattern: {}".format(exc))
            return
        print("{} match(es) in {:.1f}s".format(len(hits), time.time() - t0))
        for hit in hits[:20]:
            print("  {}".format(fmt_addr(hit)))

    def cmd_watch(self, args: List[str]) -> None:
        """Poll addresses and print only when one changes. Ctrl+C to stop."""
        if not self.require():
            return
        assert self.proc is not None
        addrs: List[int] = []
        for token in args:
            if token in self.symbols:
                addrs.append(self.symbols[token]["addr"])
            else:
                try:
                    addrs.append(parse_addr(token))
                except ValueError:
                    print("skipping {!r}: not an address or known symbol".format(token))
        if not addrs:
            print("usage: watch <addr|symbol> [more...]")
            return
        self._monitor(addrs)

    def cmd_mon(self, args: List[str]) -> None:
        """Watch every current scan candidate live. Ctrl+C to stop."""
        if self.scan is None or not self.scan.narrowed:
            print("narrow a scan first (baseline / changed / exact ...)")
            return
        cap = int(args[0]) if args else 200
        addrs = self.scan.addresses()
        if len(addrs) > cap:
            print(
                "{} candidates is too many to watch; narrow further "
                "or raise the cap: mon {}".format(len(addrs), len(addrs))
            )
            return
        self._monitor(addrs)

    def _monitor(self, addrs: List[int]) -> None:
        assert self.proc is not None
        code, size, signed = TYPES[self.vtype]
        last: Dict[int, Optional[int]] = {}

        def read_all() -> Dict[int, Optional[int]]:
            out: Dict[int, Optional[int]] = {}
            for addr in addrs:
                raw = self.proc.read(addr, size)  # type: ignore[union-attr]
                out[addr] = (
                    int.from_bytes(raw, "little", signed=signed)
                    if raw and len(raw) == size
                    else None
                )
            return out

        last = read_all()
        print("watching {} address(es) as {}. Ctrl+C to stop.".format(len(addrs), self.vtype))
        for addr in addrs:
            print("  {}  {}".format(fmt_addr(addr), last[addr]))
        print("-- changes --")
        try:
            while True:
                time.sleep(1.0 / POLL_HZ)
                if not self.proc.alive:  # type: ignore[union-attr]
                    print("game exited")
                    return
                now = read_all()
                for addr in addrs:
                    if now[addr] != last[addr]:
                        print(
                            "  {}  {} -> {}".format(
                                fmt_addr(addr), last[addr], now[addr]
                            )
                        )
                last = now
        except KeyboardInterrupt:
            print("\nstopped")

    def cmd_name(self, args: List[str]) -> None:
        """Record a confirmed address under a symbol name."""
        if len(args) < 2:
            print("usage: name <symbol> <addr> [type] [note...]")
            return
        symbol = args[0]
        try:
            addr = parse_addr(args[1])
        except ValueError:
            print("bad address {!r}".format(args[1]))
            return
        vtype = args[2] if len(args) > 2 and args[2] in TYPES else self.vtype
        note_start = 3 if (len(args) > 2 and args[2] in TYPES) else 2
        note = " ".join(args[note_start:])
        mod_base = 0x00400000
        if self.proc is not None:
            try:
                mod_base = self.proc.main_module().base
            except ProcessNotFound:
                pass
        self.symbols[symbol] = {
            "addr": addr,
            "rva": addr - mod_base,
            "type": vtype,
            "note": note,
        }
        self._save_symbols()
        print(
            "recorded {} = {} (rva 0x{:X}, {})".format(
                symbol, fmt_addr(addr), addr - mod_base, vtype
            )
        )

    def cmd_syms(self) -> None:
        if not self.symbols:
            print("no symbols recorded yet (use: name <symbol> <addr>)")
            return
        for symbol in sorted(self.symbols):
            info = self.symbols[symbol]
            line = "  {:<28} {} rva 0x{:<6X} {}".format(
                symbol, fmt_addr(info["addr"]), info.get("rva", 0), info.get("type", "?")
            )
            if info.get("note"):
                line += "  -- " + info["note"]
            print(line)
            if self.proc is not None and self.proc.alive:
                vtype = info.get("type", "i32")
                if vtype in TYPES:
                    _, size, signed = TYPES[vtype]
                    raw = self.proc.read(info["addr"], size)
                    if raw and len(raw) == size:
                        print(
                            "      now = {}".format(
                                int.from_bytes(raw, "little", signed=signed)
                            )
                        )

    def cmd_type(self, args: List[str]) -> None:
        if not args:
            print("scan type is {}".format(self.vtype))
            return
        if args[0] not in TYPES:
            print("unknown type; want one of: {}".format(", ".join(sorted(TYPES))))
            return
        self.vtype = args[0]
        self.scan = None
        print("scan type is now {} (scan cleared)".format(self.vtype))

    def cmd_where(self, args: List[str]) -> None:
        if not args:
            print("haystack is {}".format(self.haystack))
            return
        if args[0] not in ("module", "all"):
            print("usage: where module|all")
            return
        self.haystack = args[0]
        self.scan = None
        print("haystack is now {} (scan cleared)".format(self.haystack))


HELP = """
commands
  attach                 (re)attach to a running Fallout 2
  info                   process and loaded module summary
  regions                writable regions in the current haystack

  type [i32|u32|i16|u16|i8|u8]     value type for scanning   (default i32)
  where [module|all]               haystack: exe globals, or all writable memory

  base                   capture a baseline snapshot
  = <v>  / exact <v>     keep addresses equal to v
  between <lo> <hi>      keep addresses in a range
  changed / unchanged    keep addresses that did / didn't move since last capture
  inc / dec              keep addresses that increased / decreased
  delta <n>              keep addresses that moved by exactly n
  list [n]               show candidates
  reset                  clear the scan

  mon [cap]              live-watch every candidate, printing changes
  watch <addr|sym>...    live-watch specific addresses
  read <addr> [type]     one-shot read
  str <addr> [len]       read a C string
  deref <addr>           follow a pointer, show the string behind it
  dump <addr> [len]      hex dump
  aob <pattern>          signature scan, e.g.  aob A1 ?? ?? ?? ?? 83 F8 07

  name <sym> <addr> [type] [note]  record a confirmed address
  syms                             list recorded symbols with live values

  help / quit

addresses are hex (0x optional); scan values are decimal unless 0x-prefixed
""".strip()


def main() -> None:
    print("Fallout 2 memory harness")
    harness = Harness()
    harness.attach()
    print("type 'help' for commands")

    while True:
        try:
            line = input("f2> ").lstrip("﻿").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        cmd, args = parts[0].lower(), parts[1:]

        if cmd in ("quit", "exit", "q"):
            return
        elif cmd in ("help", "?"):
            print(HELP)
        elif cmd == "attach":
            harness.attach()
        elif cmd == "info":
            harness.cmd_info()
        elif cmd == "regions":
            harness.cmd_regions()
        elif cmd == "type":
            harness.cmd_type(args)
        elif cmd == "where":
            harness.cmd_where(args)
        elif cmd in ("base", "baseline"):
            harness.cmd_baseline()
        elif cmd in ("=", "exact", "between", "changed", "unchanged", "inc", "dec", "delta"):
            harness.cmd_filter(cmd, args)
        elif cmd == "list":
            harness.cmd_list(args)
        elif cmd == "reset":
            harness.cmd_reset()
        elif cmd == "mon":
            harness.cmd_mon(args)
        elif cmd == "watch":
            harness.cmd_watch(args)
        elif cmd == "read":
            harness.cmd_read(args)
        elif cmd == "str":
            harness.cmd_str(args)
        elif cmd == "deref":
            harness.cmd_deref(args)
        elif cmd == "dump":
            harness.cmd_dump(args)
        elif cmd == "aob":
            harness.cmd_aob(args)
        elif cmd == "name":
            harness.cmd_name(args)
        elif cmd == "syms":
            harness.cmd_syms()
        else:
            print("unknown command {!r}; type 'help'".format(cmd))


if __name__ == "__main__":
    main()
