# Access Never Changes

**0.2.9 "Little Boy"**

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
- **Containers, looting and the inventory.** What is in the pot, what you are
  carrying, what is in your hands, and what it all weighs. `A` takes everything
  in a container; two presses of numpad + move or equip a single item, by
  dragging it the way the engine expects.
- **Talking to people.** What they said and every reply you can give, read out
  and numbered. The number keys say a reply — that is the engine's own binding,
  so nothing has to be aimed at. Up and down walk the list.
- **How you are doing.** `;` reads health, action points and armour class.
- **Saving and loading.** F6 and F7 are the engine's own quick keys and need no
  screen; the mod watches the savegame folder and says when a save lands. The
  save and load screens read out which slots hold a game.
- **The Pip-Boy, and resting.** `P` opens it and the arrows walk it. The clock
  is read out, and the alarm clock's fourteen ways to rest are read out and
  chosen with a keypress — which is how you heal without a doctor. What
  actually happened is reported from the clock rather than from the button:
  "Rested 8 hours", or that nothing moved and so you cannot rest here.
- **The world map.** A cursor walks the world in squares and reads out the
  ground, the fog and the places, the same way the look cursor walks a map in
  hexes — but on a square grid, so all eight directions are real ones and
  numpad 8 and 2 are simply north and south. `[` and `]` step through the
  places you know, nearest first, and `/` takes the cursor to one. Numpad plus
  sets off, and says nothing until the engine's own destination confirms where
  you are going. Arriving, and being stopped short of arriving by something
  walking out of the desert, are told apart and said differently.
- **Your quests, and your holodisks.** The Status page lists the places you
  have something to do and the disks you are carrying; one key reads a place's
  tasks out, saying which are done, or reads a holodisk from end to end. None
  of it is on the screen to be read — the Pip-Boy paints its text as a picture
  — so it is rebuilt from the tables the engine parses and the variables it
  gates them on, using the engine's own rule, and checked against the engine's
  own count before it is spoken.

## Installing

You need Fallout 2 with [sfall](https://sourceforge.net/projects/sfall/) and
Python 3.8+.

```
python install.py
```

That finds the game, copies the compiled scripts into it, and makes sure the few
settings the mod depends on are set. It patches individual settings rather than
overwriting your `ddraw.ini`, backs up anything it touches, and `--check` shows
you what it would do without doing it.

Then, with the game running:

```
python f2access.py
```

Run that **from this folder**. Only the compiled scripts belong in the game
directory; the Python half stays here.

Optional: `pip install pynput` for the hotkeys, `pip install pywin32` for SAPI
speech if you do not use NVDA.

## Using it

See [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md) for the full key list and
what gets announced. The short version:

| Key | Action |
|---|---|
| Numpad 7 9 4 6 1 3 | move the look cursor one hex |
| Numpad 8 / 2 | north / south — the directions a hex grid lacks |
| Numpad 5 | bring the cursor back to you |
| Arrow keys | in a container or the inventory: walk the item lists |
| `A` | in a container: take everything — the game's own TAKE ALL |
| Numpad + | left click on the look cursor's hex — walk, or attack |
| Numpad - | right click — cycles the cursor mode |
| Numpad ✳ | where am I / whose turn is it |
| `[` / `]` | scanner: type of thing nearby |
| `Shift+[` / `Shift+]` | scanner: which one of that type |
| `Ctrl+[` / `Ctrl+]` | scanner: category |
| `/` | move the look cursor to the scanned thing |
| F6 / F7 | quick save / quick load — the game's own keys, now announced |
| `P` | the Pip-Boy — the game's own key |
| `Z` | the Pip-Boy's alarm clock, straight to resting — the game's own key |
| Up / Down | in the Pip-Boy: walk the list |
| Numpad + | in the Pip-Boy: choose what you are on |
| Numpad - | in the Pip-Boy: back to its main list |
| `1` – `9` | in a conversation: say that reply — the game's own keys |
| Up / Down | in a conversation: walk the reply list |
| Numpad 5 | in a conversation: re-read the reply you are on |
| Numpad 7 8 9 4 6 1 3 2 | on the world map: walk the cursor — all eight are real directions here |
| Numpad 5 | on the world map: bring the cursor back to you |
| `[` / `]` | on the world map: step through the places you know |
| `/` | on the world map: take the cursor to that place |
| Numpad + | on the world map: travel to the cursor's square, or go into the place you are on |
| Arrows / Home / `T` | on the world map: the game's own keys — scroll, centre, town map — now announced |
| `1` – `9` | in a town map: go in that way — the game's own keys |

**Do not hold Ctrl while using the numpad.** sfall binds Ctrl plus the numpad to
the game speed controls. [docs/CONTROLS.md](docs/CONTROLS.md) covers that and
every other key the game itself uses.

## How it works

Two halves that meet in a log file.

**Out of process**, Python reads the game's memory and speaks what changes. It
never writes to the game. It polls real state twenty times a second and reports
differences rather than remembering what it thinks is true, which is why the
speech cannot drift out of sync with the game.

The world map is the exception that proves where the line falls, and it falls
the other way from everywhere else. No map is loaded there, so no script can
help — and none is needed: the player's position, the destination, the sixty-one
places with their names and entrances, and the 28×30 grid of terrain and fog are
all plain structures in memory. So the whole screen is read by the Python half,
which makes it the one part of a loaded game that can be changed without
restarting it.

**In process**, four sfall scripts run inside Fallout 2 — `gl_world.ssl` for the
map, `gl_combat.ssl` for fighting, `gl_inven.ssl` for containers and the
inventory, and `gl_dialog.ssl` for conversations. They can ask the engine things
Python cannot see: what is on a hex, whose turn it is, what is in the pot, what
the mouse is really pointing at. They report through `debug.log`, which the
Python side tails.

`gl_dialog.ssl` is the exception that shows where the line is. It reads nothing
and reports nothing, because the dialogue screen is static memory the Python
side can read for itself. It exists for the one thing only a script can do:
stop a key reaching the engine.

They are separate scripts on purpose. Each registers its own hooks and repeat
rate independently, so the split is free, and each claims the game modes the
others decline — so exactly one of them acts on any given key press without any
of them needing to know about the others.

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

- Addresses are found by signature rather than hardcoded. Every engine global
  the mod reads is recorded in `fallout2_access/offsets/signatures.json` as the
  bytes of an instruction that references it, with the operand wildcarded, so a
  build that moves the variable is still readable. The executable is recognised
  by hash on the build it was measured against and no scan happens; anything
  else is scanned at startup, and a name that cannot be found is reported and
  spoken rather than quietly left pointing at the wrong place.
  Checked across builds: all 74 resolve on the Restoration Project Unofficial's
  patched executable, using signatures generated against the retail Steam one.
  Every address turned out to be identical between the two, so that patch moves
  code rather than data — which also means the run has proved the signatures
  resolve correctly, and not yet that they survive a build which really does
  move something.
- What actually breaks on other installs is configuration, not addresses. RPU
  ships its own `ddraw.ini`, and `install.py` exists to put the handful of
  settings the mod depends on back: `DebugMode` and `show_script_messages`
  decide whether the scripts can be heard at all, `GlobalScriptPaths` whether
  they are loaded, `AutoQuickSave` whether F6 can save without a mouse, and
  `HiResMode` which high resolution patch is in charge. Run `install.py`
  against any install you play on, and again after installing anything else.
- Skill percentages and derived stats are computed from the SPECIAL values
  during character creation, where that is what the editor is doing too. In a
  loaded game they are read from the engine instead, through `get_critter_stat`
  and `has_skill`, so drugs, armour, tag skills and spent points are all
  included.
- **The Pip-Boy's Automaps page is counted rather than named, on purpose.** An
  automap is a floor plan drawn from tile data with no text in it, so naming
  the list would only take you to a picture. The page says how many maps it
  holds and lets you move through them; it does not pretend to describe one.
- **The Vault 13 holodisk is the one disk that cannot be named.** It is the
  only one of the twenty-one that is not in the table the engine parses from
  `holodisk.txt`, so the mod has no record of it to reconstruct from. It is not
  invented; it is simply absent from the list.
- Dialogue reads and answers, but a conversation of more than nine replies can
  only have its first nine said: the engine binds `1` to `9` and a tenth would
  have to be clicked on. Nothing in the tutorial or in Arroyo has that many.
- The dialogue Review screen — the transcript of a conversation — is not read.
  Most of its entries hold only a message id rather than text, so it would have
  to be resolved through the .msg files rather than simply read.
- Floating one-liners, the words that appear over a character's head instead of
  opening a conversation, are not read. They are neither the dialogue screen nor
  the interface bar the mod already reads.
- Lists longer than six items cannot have their lower entries moved yet: the
  mod scrolls a list to the top by construction, but not back down again.
- Using an item on something in the world -- explosives on a door, say -- still
  needs the timer window, which is not covered.
- `U` arms the item in your active hand -- the engine switches to its use
  cursor and waits to be told what to use it on. Picking that target is not
  covered yet, so U works for anything you then reach with the action menu and
  does not yet work for using something on yourself.
- Body parts struck in combat are not spoken yet: the words live in the game's
  own `combat.msg`, and inventing English ones would break every translation.

## Licence

MIT — see [LICENSE](LICENSE). The sfall headers the scripts include, and the
compiler used to build them, belong to the sfall project and are not
redistributed here.
