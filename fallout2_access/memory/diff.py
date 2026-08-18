"""Differential value scanning -- how we locate engine globals we have no
address for.

The workflow is the classic one: capture a baseline, let the game change
something observable (press Down in the char editor), then keep only the
addresses that moved the way the on-screen value moved. A handful of rounds
takes a few hundred thousand candidates down to one.

Scanning is deliberately pointed at the main module's writable regions by
default. Fallout 2 keeps its editor state in statically allocated globals, so
that is both the right haystack and a tiny one -- a few megabytes, not the
whole address space.
"""

from __future__ import annotations

import bisect
from array import array
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .process import Process, Region

# name -> (array typecode, expected size in bytes, signed)
TYPES: Dict[str, Tuple[str, int, bool]] = {
    "i8": ("b", 1, True),
    "u8": ("B", 1, False),
    "i16": ("h", 2, True),
    "u16": ("H", 2, False),
    "i32": ("i", 4, True),
    "u32": ("I", 4, False),
}

Capture = List[Tuple[int, array]]


class ValueScan:
    """A narrowing search for addresses holding a value of interest."""

    def __init__(
        self,
        proc: Process,
        regions: Optional[Sequence[Region]] = None,
        vtype: str = "i32",
    ) -> None:
        if vtype not in TYPES:
            raise ValueError(
                "unknown type {!r}; want one of {}".format(vtype, ", ".join(sorted(TYPES)))
            )
        self.proc = proc
        self.vtype = vtype
        self.typecode, self.itemsize, self.signed = TYPES[vtype]
        if array(self.typecode).itemsize != self.itemsize:
            raise RuntimeError(
                "platform array itemsize mismatch for {!r}".format(vtype)
            )
        self.regions: List[Region] = sorted(
            regions if regions is not None else proc.module_regions(),
            key=lambda r: r.base,
        )
        self._wide: Optional[Capture] = None
        self._cands: Optional[Dict[int, int]] = None
        self.rounds = 0

    # -- state ---------------------------------------------------------------

    @property
    def narrowed(self) -> bool:
        return self._cands is not None

    @property
    def count(self) -> int:
        if self._cands is not None:
            return len(self._cands)
        if self._wide is not None:
            return sum(len(a) for _, a in self._wide)
        return 0

    def reset(self) -> None:
        self._wide = None
        self._cands = None
        self.rounds = 0

    @property
    def haystack_bytes(self) -> int:
        return sum(r.size for r in self.regions)

    # -- capture -------------------------------------------------------------

    def _capture(self) -> Capture:
        out: Capture = []
        for region in self.regions:
            data = self.proc.read_chunked(region.base, region.size)
            usable = len(data) - (len(data) % self.itemsize)
            if usable <= 0:
                continue
            out.append((region.base, array(self.typecode, data[:usable])))
        return out

    def _indexer(self, caps: Capture) -> Callable[[int], Optional[int]]:
        bases = [b for b, _ in caps]
        arrs = [a for _, a in caps]
        ends = [b + len(a) * self.itemsize for b, a in caps]
        itemsize = self.itemsize

        def lookup(addr: int) -> Optional[int]:
            i = bisect.bisect_right(bases, addr) - 1
            if i < 0 or addr >= ends[i]:
                return None
            off = addr - bases[i]
            if off % itemsize:
                return None
            return arrs[i][off // itemsize]

        return lookup

    def baseline(self) -> int:
        """Capture a wide snapshot to compare later scans against."""
        self._wide = self._capture()
        self._cands = None
        self.rounds = 0
        return self.count

    # -- filters -------------------------------------------------------------

    def exact(self, value: int) -> int:
        """Keep addresses currently holding `value`."""
        return self._apply(lambda prev, cur: cur == value, needs_prev=False)

    def between(self, low: int, high: int) -> int:
        return self._apply(lambda prev, cur: low <= cur <= high, needs_prev=False)

    def changed(self) -> int:
        return self._apply(lambda prev, cur: prev != cur, needs_prev=True)

    def unchanged(self) -> int:
        return self._apply(lambda prev, cur: prev == cur, needs_prev=True)

    def increased(self) -> int:
        return self._apply(lambda prev, cur: cur > prev, needs_prev=True)

    def decreased(self) -> int:
        return self._apply(lambda prev, cur: cur < prev, needs_prev=True)

    def delta(self, amount: int) -> int:
        return self._apply(lambda prev, cur: cur - prev == amount, needs_prev=True)

    def _apply(
        self, pred: Callable[[Optional[int], int], bool], needs_prev: bool
    ) -> int:
        fresh = self._capture()

        if self._cands is not None:
            lookup = self._indexer(fresh)
            kept: Dict[int, int] = {}
            for addr, prev in self._cands.items():
                cur = lookup(addr)
                if cur is None:
                    continue
                if pred(prev, cur):
                    kept[addr] = cur
            self._cands = kept
            self.rounds += 1
            return len(kept)

        # Wide scan.
        if needs_prev:
            if self._wide is None:
                raise RuntimeError(
                    "this filter needs a baseline; run baseline() first"
                )
            prev_by_base = {b: a for b, a in self._wide}
            kept = {}
            for base, arr in fresh:
                prev_arr = prev_by_base.get(base)
                if prev_arr is None or len(prev_arr) != len(arr):
                    continue
                itemsize = self.itemsize
                for i, cur in enumerate(arr):
                    prev = prev_arr[i]
                    if pred(prev, cur):
                        kept[base + i * itemsize] = cur
        else:
            kept = {}
            itemsize = self.itemsize
            for base, arr in fresh:
                for i, cur in enumerate(arr):
                    if pred(None, cur):
                        kept[base + i * itemsize] = cur

        self._cands = kept
        self._wide = None
        self.rounds += 1
        return len(kept)

    # -- inspection ----------------------------------------------------------

    def refresh(self) -> Dict[int, int]:
        """Re-read current candidate values without filtering."""
        if self._cands is None:
            return {}
        lookup = self._indexer(self._capture())
        out: Dict[int, int] = {}
        for addr in self._cands:
            cur = lookup(addr)
            if cur is not None:
                out[addr] = cur
        self._cands = out
        return out

    def items(self, limit: int = 40) -> List[Tuple[int, int]]:
        """Current candidates as (address, value), lowest address first."""
        if self._cands is None:
            return []
        pairs = sorted(self._cands.items())
        return pairs[:limit] if limit else pairs

    def addresses(self) -> List[int]:
        return sorted(self._cands) if self._cands else []
