"""Memory access primitives for the running Fallout 2 process."""

from .process import (
    Process,
    Module,
    Region,
    ProcessNotFound,
    FALLOUT_EXE_NAMES,
)
from .scan import compile_pattern, find_pattern, find_pattern_all
from .diff import ValueScan, TYPES

__all__ = [
    "Process",
    "Module",
    "Region",
    "ProcessNotFound",
    "FALLOUT_EXE_NAMES",
    "compile_pattern",
    "find_pattern",
    "find_pattern_all",
    "ValueScan",
    "TYPES",
]
