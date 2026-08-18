"""Array-of-bytes (signature) scanning.

Signatures rather than hardcoded addresses are what let one build work against
the Steam, GOG and plain 1.02d executables. A signature that fails to resolve
must be reported by name, never silently skipped -- a wrong address is far
worse than a missing one, because it speaks confident nonsense.

Pattern syntax is the conventional space-separated hex with `??` wildcards:

    "A1 ?? ?? ?? ?? 83 F8 07"
"""

from __future__ import annotations

import re
from typing import Iterator, List, Optional, Pattern, Sequence

from .process import Process, Region


def compile_pattern(pattern: str) -> Pattern:
    """Compile a signature string into a bytes regex."""
    parts = pattern.replace(",", " ").split()
    if not parts:
        raise ValueError("empty pattern")
    chunks: List[bytes] = []
    for part in parts:
        if part in ("??", "?", "*"):
            chunks.append(b".")
            continue
        if len(part) != 2:
            raise ValueError("bad pattern token {!r} (want 2 hex digits or ??)".format(part))
        try:
            value = int(part, 16)
        except ValueError:
            raise ValueError("bad pattern token {!r}".format(part))
        chunks.append(re.escape(bytes([value])))
    return re.compile(b"".join(chunks), re.DOTALL)


def find_pattern_all(
    proc: Process,
    pattern: str,
    regions: Optional[Sequence[Region]] = None,
    limit: int = 0,
) -> List[int]:
    """Every address matching `pattern`. Empty list means no match."""
    rx = compile_pattern(pattern)
    if regions is None:
        regions = list(proc.module_regions())
    hits: List[int] = []
    for region in regions:
        data = proc.read_chunked(region.base, region.size)
        for match in rx.finditer(data):
            hits.append(region.base + match.start())
            if limit and len(hits) >= limit:
                return hits
    return hits


def find_pattern(
    proc: Process,
    pattern: str,
    regions: Optional[Sequence[Region]] = None,
    unique: bool = True,
) -> Optional[int]:
    """The single address matching `pattern`.

    With `unique`, an ambiguous signature returns None rather than guessing --
    two matches means the signature is not specific enough to trust.
    """
    hits = find_pattern_all(proc, pattern, regions, limit=0 if unique else 1)
    if not hits:
        return None
    if unique and len(hits) > 1:
        return None
    return hits[0]


def code_regions(proc: Process) -> List[Region]:
    """Executable regions of the main module -- the haystack for code signatures."""
    mod = proc.main_module()
    out: List[Region] = []
    for region in proc.regions():
        if region.end <= mod.base or region.base >= mod.end:
            continue
        if region.protect & 0xF0:  # any PAGE_EXECUTE_* variant
            base = max(region.base, mod.base)
            end = min(region.end, mod.end)
            out.append(Region(base, end - base, region.protect))
    return out
