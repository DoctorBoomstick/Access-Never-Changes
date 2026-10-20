"""The mod's version.

Numbering, as set by the project's owner:

    MAJOR.MINOR   move only on his mark
    PATCH         moves with every change

Each MINOR release carries a name. This one is "Fat Man" -- 1.0, the first
release for players rather than for the repo. It installs with a wizard and
starts with the game; it speaks in whatever language a translator gives it,
from files beside it; it reads the race and style a character is made with,
the quit box Control and X raises, and the save's description box; and it
drops things through the engine's own Drop, which no version before it could.

"Little Boy", 0.2, was the release where the mod stopped talking over the
game: M given back to the engine, the dead no longer hidden, and which way a
critter is looking said aloud.
"""

VERSION = "1.0.0"
NAME = "Fat Man"


def banner() -> str:
    return "Access Never Changes {} \"{}\"".format(VERSION, NAME)
