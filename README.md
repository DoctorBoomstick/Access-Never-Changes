# Access Never Changes

**0.1.39 "gadget"**

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
  so nothing has to be aimed at. Numpad 8 and 2 walk the list.
- **How you are doing.** `;` reads health, action points and armour class.
- **Saving and loading.** F6 and F7 are the engine's own quick keys and need no
  screen; the mod watches the savegame folder and says when a save lands. The
  save and load screens read out which slots hold a game.

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
| Numpad 8 / 2 / 4 / 6 | in a container or the inventory: walk the item lists |
| `A` | in a container: take everything — the game's own TAKE ALL |
| Numpad + | left click on the look cursor's hex — walk, or attack |
| Numpad - | right click — cycles the cursor mode |
| Numpad ✳ | where am I / whose turn is it |
| `[` / `]` | scanner: type of thing nearby |
| `Shift+[` / `Shift+]` | scanner: which one of that type |
| `Ctrl+[` / `Ctrl+]` | scanner: category |
| `/` | move the look cursor to the scanned thing |
| F6 / F7 | quick save / quick load — the game's own keys, now announced |
| `1` – `9` | in a conversation: say that reply — the game's own keys |
| Numpad 8 / 2 / 5 | in a conversation: walk the reply list, re-read one |

**Do not hold Ctrl while using the numpad.** sfall binds Ctrl plus the numpad to
the game speed controls. [docs/CONTROLS.md](docs/CONTROLS.md) covers that and
every other key the game itself uses.

## How it works

Two halves that meet in a log file.

**Out of process**, Python reads the game's memory and speaks what changes. It
never writes to the game. It polls real state twenty times a second and reports
differences rather than remembering what it thinks is true, which is why the
speech cannot drift out of sync with the game.

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

- Addresses are absolute, confirmed against the retail Steam `fallout2.exe`.
  They survive game restarts, but signature scanning is still needed before this
  works on GOG or other builds.
- Skill percentages and derived stats are computed from the SPECIAL values
  during character creation, where that is what the editor is doing too. In a
  loaded game they are read from the engine instead, through `get_critter_stat`
  and `has_skill`, so drugs, armour, tag skills and spent points are all
  included.
- The Pipboy is not covered yet, and is now the largest remaining gap.
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
