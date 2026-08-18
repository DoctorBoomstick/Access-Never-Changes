# Access Never Changes

A screen reader accessibility mod for **Fallout 2**.

It runs alongside the retail game — no source port, no patched executable — and
speaks what is happening: the menus, character creation, the map around you,
and combat. Where the game can only be played with a mouse, it aims and clicks
for you, on a hex you chose with the keyboard.

Built for NVDA, with SAPI and accessible_output2 as fallbacks.

## What works today

- **Main menu, character selection and character creation.** All 59 items of
  the character editor, with names, values and descriptions.
- **Moving around the map.** A look cursor walks the hex grid, reads out what is
  on each hex, and one key walks you there.
- **Melee combat.** Turn order, action points, hits, misses, damage and deaths.
  One key attacks the enemy your look cursor is on.

## Installing

You need Fallout 2 with [sfall](https://sourceforge.net/projects/sfall/) and
Python 3.8+.

```
python install.py
```

That finds the game, copies two compiled scripts into it, and makes sure the few
settings the mod depends on are set. It patches individual settings rather than
overwriting your `ddraw.ini`, backs up anything it touches, and `--check` shows
you what it would do without doing it.

Then, with the game running:

```
python f2access.py
```

Optional: `pip install pynput` for the hotkeys, `pip install pywin32` for SAPI
speech if you do not use NVDA.

## Using it

See [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md) for the full key list and
what gets announced. The short version:

| Key | Action |
|---|---|
| Numpad 7 9 4 6 1 3 | move the look cursor one hex |
| Numpad 5 | re-read the hex |
| Numpad 8 | bring the cursor back to you |
| Numpad ✳ | walk there — or attack, if an enemy is standing there |
| Numpad + | where am I / whose turn is it |

**Do not hold Ctrl while using the numpad.** sfall binds Ctrl plus the numpad to
the game speed controls. [docs/CONTROLS.md](docs/CONTROLS.md) covers that and
every other key the game itself uses.

## How it works

Two halves that meet in a log file.

**Out of process**, Python reads the game's memory and speaks what changes. It
never writes to the game. It polls real state twenty times a second and reports
differences rather than remembering what it thinks is true, which is why the
speech cannot drift out of sync with the game.

**In process**, two sfall scripts run inside Fallout 2 — `gl_world.ssl` for the
map and `gl_combat.ssl` for fighting. They can ask the engine things Python
cannot see: what is on a hex, whose turn it is, what the mouse is really
pointing at. They report through `debug.log`, which the Python side tails.

Scripts do not run before a game is loaded, so the menus and character creation
are read from memory; everything in a live game comes from the scripts.

### Two rules everything follows

**Nothing is announced that a sighted player could not see.** Invisible engine
objects are filtered out, enemy hit points are never read out, and no hook that
could change the outcome of a fight is used, even where the engine offers one.
The goal is access to Fallout 2, not an easier Fallout 2.

**Nothing is acted on until the game confirms it.** Before a click, the mod asks
the engine which hex the pointer is really over, and in combat which critter is
really targeted. If the answer does not match what you chose, it does not click
and says so. A misplaced click walks you somewhere you did not pick or attacks
something you did not choose, and you would have no way to catch it.

## Developing

```
python -m unittest discover -s tests -t .    run the tests
python build.py --install                    recompile the scripts and install
```

Changing a `.ssl` script needs a full game restart — global scripts bind when a
save loads. The compiled `.int` files are committed so that playing needs no
compiler; you only need one to change the scripts.

`docs/HARNESS.md` covers the memory-scanning tools in `tools/`, which is how the
addresses in `fallout2_access/offsets/` were found.

## Status and limits

- Addresses are absolute, confirmed against the retail Steam `fallout2.exe`.
  They survive game restarts, but signature scanning is still needed before this
  works on GOG or other builds.
- Skill percentages and derived stats are computed, not read — the engine does
  not store them. The formulas are right for vanilla; a mod that changes them
  would make the numbers wrong while the names stayed right.
- Dialogue, barter, inventory and the Pipboy are not covered yet. Dialogue is
  mouse-only in the engine and is the largest remaining gap.
- Body parts struck in combat are not spoken yet: the words live in the game's
  own `combat.msg`, and inventing English ones would break every translation.

## Licence

MIT — see [LICENSE](LICENSE). The sfall headers the scripts include, and the
compiler used to build them, belong to the sfall project and are not
redistributed here.
