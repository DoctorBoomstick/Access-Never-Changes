"""The mod's version.

Numbering, as set by the project's owner:

    MAJOR.MINOR   move only on his mark
    PATCH         moves with every change

Each MINOR release carries a name. This one is "gadget" -- the release where
the inventory became something you could operate rather than only listen to.
"""

VERSION = "0.1.6"
NAME = "gadget"


def banner() -> str:
    return "Access Never Changes {} \"{}\"".format(VERSION, NAME)
