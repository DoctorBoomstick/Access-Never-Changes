"""Fallout 2 screen reader accessibility layer.

Architecture (see docs/DEVELOPING.md):
    memory/   attach to the game, read its memory, locate symbols
    offsets/  signature table -- data, not code
    msg/      DAT2 reader -> the game's own .msg strings
    game/     typed views over engine state
    speech/   screen reader backends
    input/    hotkeys and synthesized mouse
    screens/  one module per game screen
"""

__version__ = "0.1.0-harness"
