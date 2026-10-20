"""Find the engine's globals in whatever build is actually running.

The mod holds absolute addresses into fallout2.exe, and an absolute address is a
fact about one build. The Restoration Project Unofficial demonstrated the cost:
it rewrote the executable in place, the character editor's window handle moved
eight bytes, and the mod fell silent on that screen without one read failing.
Every read succeeded and returned -1 -- which legitimately means "no editor
open" -- so nothing could distinguish a moved variable from a closed window.

So the addresses are found rather than assumed. `offsets/signatures.json` holds,
for each name, the bytes of an instruction that references the variable, with
the four operand bytes wildcarded. Match the pattern, read the operand back out,
and that is where the variable lives in THIS executable.

Three rules, and the first two are the reason this file is worth having:

**A signature that does not resolve is reported by name and left unresolved.**
Never fall back to the recorded address on a build that is not the recorded
build -- that is precisely how RPU stayed invisible, an address that read
cleanly and meant something else.

**A signature that matches twice is a failure, not a coin toss.** `find_pattern`
already refuses to guess; this keeps that promise instead of taking the first
hit.

**Some variables no instruction names.** They are entries inside arrays, reached
by index, so no `mov` spells their address out -- measured for EDITOR_WINDOW and
for the stat table. Those are derived from a signatured neighbour plus a fixed
distance, because the distance is a fact about the engine's layout while the
base is a fact about the build. Two more are derived on purpose rather than by
necessity: chargen's AGE_ADDR and SEX_ADDR are built from the stat table at
import time, and a pair that can disagree is worse than either answer alone.

The file also records which module attribute each name feeds, so the list of
things that must be found lives in one place and cannot drift out of step with
the file that finds them.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import struct
from typing import Dict, List, NamedTuple, Optional, Tuple

from ..i18n import tr
from . import scan
from .process import Process

SIGNATURES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "offsets", "signatures.json",
)


class Resolution(NamedTuple):
    """What was found, and what was not."""

    addresses: Dict[str, int]
    failures: List[str]
    scanned: bool           # False when the recorded build was recognised
    exe_sha256: str

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> Optional[str]:
        """One sentence for the player, or None when there is nothing to say.

        Spoken rather than only printed, because the console is not somewhere a
        blind player can look, and "some screens are silent" is exactly the kind
        of fault that otherwise reads as the mod being broken in general.
        """
        if not self.failures:
            return None
        n = len(self.failures)
        if n == 1:
            return tr("offsets.missing_one",
                      "1 address could not be found in this version of the "
                      "game. Some screens may not be read.")
        return tr("offsets.missing",
                  "{count} addresses could not be found in this version of "
                  "the game. Some screens may not be read.", count=n)


def load(path: str = SIGNATURES) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def exe_sha256(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def owners(doc: dict) -> Dict[str, List[Tuple[str, str]]]:
    """name -> the module attributes it feeds, from the file itself."""
    out: Dict[str, List[Tuple[str, str]]] = {}
    for section in ("signatures", "derived"):
        for name, spec in doc.get(section, {}).items():
            got = spec.get("owners") or []
            if got:
                out[name] = [tuple(o) for o in got]
    return out


def derive(addresses: Dict[str, int], derived: dict) -> Tuple[Dict[str, int],
                                                              List[str]]:
    """Apply anchor-plus-distance entries on top of what was signatured.

    Pure, so the arithmetic can be tested without a game running. Ordered so an
    anchor that is itself derived resolves first; a single pass would otherwise
    depend on dictionary order to get the right answer.
    """
    out = dict(addresses)
    failures: List[str] = []
    pending = dict(derived)
    for _ in range(len(pending) + 1):
        if not pending:
            break
        progressed = False
        for name in sorted(pending):
            spec = pending[name]
            anchor = spec.get("anchor")
            delta = spec.get("delta")
            if anchor is None or delta is None:
                failures.append("{}: malformed derived entry".format(name))
                del pending[name]
                progressed = True
                break
            if anchor in out:
                out[name] = out[anchor] + delta
                del pending[name]
                progressed = True
                break
        if not progressed:
            break
    for name in sorted(pending):
        # Not "assume the recorded value": an anchor that failed means the
        # neighbourhood is not where it was, which is exactly when a fixed
        # distance from it is worthless.
        failures.append("{}: anchor {} did not resolve".format(
            name, pending[name].get("anchor")))
    return out, failures


def resolve(proc: Process, doc: Optional[dict] = None) -> Resolution:
    """Locate every signatured global in the attached process."""
    doc = doc if doc is not None else load()
    digest = exe_sha256(proc.exe_path)
    if not doc:
        return Resolution({}, ["offsets/signatures.json is missing or invalid"],
                          False, digest)

    sigs = doc.get("signatures", {})
    derived_spec = doc.get("derived", {})

    # The fast path is an optimisation, not a shortcut in judgement: the file
    # records which executable it was generated against, and on that exact
    # executable the recorded addresses are what the patterns would find.
    # Scanning a megabyte of code to rediscover them would cost startup time to
    # learn nothing.
    if digest and digest == doc.get("exe_sha256", ""):
        addresses = {n: s["address"] for n, s in sigs.items() if "address" in s}
        addresses.update({n: s["address"] for n, s in derived_spec.items()
                          if "address" in s})
        return Resolution(addresses, [], False, digest)

    regions = scan.code_regions(proc)
    addresses: Dict[str, int] = {}
    failures: List[str] = []
    for name, spec in sorted(sigs.items()):
        pattern = spec.get("pattern")
        offset = spec.get("operand_offset")
        if not pattern or offset is None:
            failures.append("{}: malformed signature".format(name))
            continue
        # unique=True: two matches is an under-specified pattern, and taking
        # the first would be the guess this whole file exists to avoid.
        hit = scan.find_pattern(proc, pattern, regions, unique=True)
        if hit is None:
            failures.append("{}: signature did not match uniquely".format(name))
            continue
        raw = proc.read(hit + offset, 4)
        if not raw or len(raw) != 4:
            failures.append("{}: operand unreadable".format(name))
            continue
        addresses[name] = struct.unpack("<I", raw)[0]

    addresses, more = derive(addresses, derived_spec)
    return Resolution(addresses, failures + more, True, digest)


def apply_to(module_name: str, attr: str, addr: int) -> bool:
    """Write one resolved address into the module that reads it.

    `attr` may name a tuple entry, as `MOUSE_MIRRORS[0]`. pointer.py keeps its
    fallback mirrors in a tuple, and assigning an int over the whole tuple would
    replace a list of candidates with a single number -- which fails later, far
    from here, as "this is not iterable".
    """
    module = importlib.import_module(module_name, __package__)
    if attr.endswith("]") and "[" in attr:
        base, index = attr[:-1].split("[", 1)
        current = getattr(module, base, None)
        if not isinstance(current, tuple):
            return False
        i = int(index)
        if not 0 <= i < len(current):
            return False
        rebuilt = current[:i] + (addr,) + current[i + 1:]
        changed = rebuilt != current
        setattr(module, base, rebuilt)
        return changed
    changed = getattr(module, attr, None) != addr
    setattr(module, attr, addr)
    return changed


def bind(proc: Process, doc: Optional[dict] = None) -> Resolution:
    """Resolve, then write the answers into the modules that read them.

    The constants stay where they are and keep their measured values, so the
    mod runs on the build it was developed against with or without this. What
    binding changes is what happens on any OTHER build: instead of reading a
    plausible number out of the wrong place, the address is found, or the name
    is reported as unresolved and nothing is overwritten.

    Assigning module attributes is deliberate and is the smallest honest change
    available. The alternative -- threading an offsets object through every
    reader -- touches every call site to say the same thing, and a wrong address
    is not a problem any of those call sites can do anything about.
    """
    doc = doc if doc is not None else load()
    result = resolve(proc, doc)
    if not result.addresses or not doc:
        return result

    table = owners(doc)
    applied: List[str] = []
    for name, addr in sorted(result.addresses.items()):
        for module_name, attr in table.get(name, ()):
            try:
                if apply_to(module_name, attr, addr):
                    applied.append("{} -> {}.{} 0x{:08X}".format(
                        name, module_name.lstrip("."), attr, addr))
            except (ImportError, AttributeError, ValueError) as exc:
                result.failures.append(
                    "{}: cannot write {}.{} ({})".format(
                        name, module_name, attr, exc))

    if result.scanned:
        print("[offsets] unrecognised executable ({}...); resolved {} of {} "
              "by signature".format(result.exe_sha256[:12],
                                    len(result.addresses), len(table)),
              flush=True)
        for line in applied:
            print("[offsets]   {}".format(line), flush=True)
    for why in result.failures:
        print("[offsets] UNRESOLVED {}".format(why), flush=True)
    return result
