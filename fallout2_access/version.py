"""The mod's version.

Numbering, as set by the project's owner:

    MAJOR.MINOR   move only on his mark
    PATCH         moves with every change

Each MINOR release carries a name. This one is "Little Boy" -- the release
where the mod stopped talking over the game. It gave M back to the engine and
read its own key off the keyboard rather than synthesising the one it had
taken; it stopped hiding the dead, so a corpse can be found, named and looted;
and it started saying which way a critter is looking, because where somebody's
back is turned is half of sneaking and all of stealing.
"""

VERSION = "0.2.9"
NAME = "Little Boy"


def banner() -> str:
    return "Access Never Changes {} \"{}\"".format(VERSION, NAME)
