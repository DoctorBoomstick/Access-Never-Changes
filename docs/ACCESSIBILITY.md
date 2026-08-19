# Fallout 2 screen reader accessibility

Makes the main menu, character selection and character creation usable with a
screen reader. Runs as a companion process alongside the game — it reads the
game's memory and speaks what changes. It never writes to the game.

## Running it

    python f2access.py

Then start Fallout 2 and play. It attaches on its own, and reattaches if you
restart the game.

Requirements: Python 3.8+, and NVDA running (or `pip install pywin32` for SAPI,
or `pip install accessible_output2`). `pip install pynput` enables the hotkeys.

**The game must run windowed** — `WINDOWED=1` in `f2_res.ini`, already set.
Exclusive-fullscreen DX9 starves the low-level keyboard hook.

## Getting into the game

These are the engine's own keys, not anything this mod adds. The main menu has
**no arrow-key navigation at all** — it is letter hotkeys only.

**Main menu**

| Key | Action |
|---|---|
| `N` | New game |
| `L` | Load game |
| `I` | Intro |
| `O` | Options |
| `C` | Credits |
| `E` or Escape | Exit |

**Character selection** (after pressing `N`)

| Key | Action |
|---|---|
| Left / Right | cycle the premade characters |
| `C` | **Create your own character** |
| `M` | modify the selected premade |
| `T` | take the selected premade as-is |
| `B` or Escape | back |

**Character creation**

| Key | Action |
|---|---|
| Tab | next section: SPECIAL → traits → condition → derived → skills |
| Up / Down | move within a section |
| Left / Right (or `-` / `+`) | lower / raise the selected value |
| `N` / `A` / `S` | edit name / age / gender |
| `O` | options |
| `D` or Enter | done |
| `C` or Escape | cancel |

## In the game world

Once you're on a map, numpad 0-9 are handled **inside the game** by
`gl_world.ssl`, which moves a "look cursor" around the hex grid and reads out
what is on each hex. A hex has six neighbours and no north or south, which is
why the six directions sit on the numpad's corners and sides:

```
      7 NW    9 NE
    4 W           6 E
      1 SW    3 SE
```

| Key | Action |
|---|---|
| Numpad 7 9 4 6 1 3 | move the look cursor one hex |
| Numpad 8 | **north** |
| Numpad 2 | **south** |
| Numpad 5 | bring the cursor back to you |
| Numpad 0 | force the movement cursor |

### North and south, which the grid does not have

A hex has six neighbours and no north or south. Going "up" means alternating
north east and north west — and which one you need next depends on the row, so
doing it by hand drifts. Alternating north east and *west* very nearly cancels:
some pairs climb and some do not, so tracing a wall slides you a few hexes off
it without any sign that it happened.

Numpad 8 and 2 do it for you. They remember which way the staircase leans and
take the step that cancels it, so holding north traces a straight line up the
screen and every second press returns to the starting column. Put the cursor on
a wall, press north repeatedly, and the readout stops saying "Wall" exactly
where the opening is.

Each press is still one ordinary hex step. It is only the choice between two
legal steps — the one a sighted player makes by eye.

(Numpad / repeats the last thing said, which covers re-reading a hex.)
| Numpad + | **left click on the hex the look cursor is on** |

(Numpad 2 is used internally — the mod presses it several times per click to
ask the game where the pointer is. It isn't a key you need.)

## Walking

Pick a hex with the numpad, then press numpad +. You walk there.

Fallout 2 only moves you where you click, and there is no keyboard equivalent,
so the mod has to put the mouse pointer on the hex you chose. It does that by
feedback rather than arithmetic: it moves the pointer, asks the game which hex
it actually landed on, and corrects, usually settling in two or three steps and
well under a second. Pointer acceleration means the same movement command
travels a different distance each time, so anything that calculated a position
would miss.

**It will not click unless the game confirms the pointer is on the hex you
asked for.** If it can't get there — the hex is off the edge of the view, say —
it says so and does nothing. A click that lands on the wrong hex walks you
somewhere you didn't choose, and you would have no way to see it happen.

When you stop, it tells you how far you went: `Moved 3 hexes.`

Readings sound like `Tree, 12 hexes` or `Radscorpion, 3 hexes`. A hex with
nothing named on it is either **empty** — you can walk there — or **blocked**,
meaning you cannot.

That distinction matters more than it looks. Fallout's floors and much of its
walls are drawn as tile art rather than as objects, so asking what objects are
on a hex returns nothing at all for a solid wall. The only thing present is an
invisible blocker, which is exactly what the mod refuses to read out. So the
hex is asked whether it can be walked into instead — which is the question you
were really asking when you ran the cursor along a wall looking for the gap.

`empty` and `blocked` are the mod's own words. Everything that names a *thing*
comes from the game. Invisible engine
objects (scroll blockers, script triggers) are filtered out — a sighted player
doesn't see those either.

### What a click will do

Fallout 2 has several cursor modes and they change what a left click *means* —
walk, interact, attack, or use a skill you armed from the Skilldex. A sighted
player reads that off the cursor's shape without thinking about it, so the mod
announces it whenever it changes:

    movement cursor. A click walks you there
    skill cursor, mode 5. A click uses the skill you picked in the Skilldex,
    it does not walk. Press numpad 0 for the movement cursor

This is not a nicety. An armed Skilldex skill stays armed until something
clears it, and it is silent — a whole round of debugging went into "clicks
don't move the player" before we found the cursor had been holding a skill the
entire time. Numpad 0 always puts it back to movement and says so.

The skill cursors are announced by number rather than name: sfall reports modes
4 through 10 for them but doesn't say which is which, and a confidently wrong
skill name on the thing that decides whether you walk or pick a lock is worse
than a number.

## Skills, doors and other things you act on

Skills work the way they do for everyone else: **press a number key to arm one,
then click the target.**

| Key | Skill | | Key | Skill |
|---|---|---|---|---|
| 1 | Sneak (a toggle — no target) | | 5 | First Aid |
| 2 | Lockpick | | 6 | Doctor |
| 3 | Steal | | 7 | Science |
| 4 | Traps | | 8 | Repair |

The mod tells you what is armed — `Lockpick ready. A click uses it.` — so you
always know what the next click will do. Numpad 0 puts you back to the movement
cursor.

So a locked door is: find it with the scanner, `/` to put the cursor on it,
press `2`, then numpad `+`.

**The mod no longer decides what your click means.** It moves the pointer onto
the hex you chose, because that is the part you cannot do yourself, and it
refuses to click if the game will not confirm the pointer is really on the
thing. What the click then *does* is the cursor mode's business, and the cursor
mode is yours — right click cycles it, number keys arm skills, and every change
is announced.

Hexes and the scanner now say when something is **locked** or **open**, so you
find out before walking across a room rather than by clicking and hearing
nothing:

    Door, locked, east 3 hexes. 1 of 4.

## The game's own words

Fallout talks to you along the bottom of the screen — "You see: a door", "It's
locked", "You hit the Giant Ant for 10 points of damage." The mod reads that
strip directly out of the game and speaks it.

This is the preferred source for anything about the world. It's the engine's own
sentences: already written, already translated, and describing exactly what a
sighted player was told, rather than something the mod reconstructed in English.
Once it's available the mod stops narrating blows itself and defers to it.

Turn order and action points stay the mod's own, because the game never writes
those anywhere.

## Combat

### Attacking

Same key as walking. Put the look cursor on the enemy with the numpad, press
numpad ✳.

Fallout decides what a left click does from the cursor mode, so the mod sets it
to match what you selected: **a living enemy on the hex in combat gives you the
targeting cursor and the click attacks; anything else gives the movement cursor
and the click walks.** There's no ambiguity to trip over — a living critter
blocks its hex, so "walk there" was never on offer for that hex anyway.

Corpses are skipped. A dead critter stops blocking its tile, so a body and a
live enemy can share a hex, and swinging at the body would waste your turn.

### What you hear

Combat announces itself as it happens — you don't press anything for this:

    Your turn.
    8 of 8 action points.
    5.
    You miss Giant Ant.
    Giant Ant's turn.
    Giant Ant hits you for 7.
    You hit Giant Ant for 22, critical.
    Giant Ant dies.
    Combat over.

At the start of your turn you get the full action point figure; after that just
the remainder as you spend it, since the total doesn't change. Numpad + reports
whose turn it is and your AP, instead of the usual key reminder.

Names and numbers are the game's own. **Body parts aren't spoken yet** — the
engine reports which was struck as a number, and the words for them live in the
game's `combat.msg`, which we can't read yet. An English list hardcoded here
would break every translation, so it stays quiet until we can quote the game.

Enemy hit points are deliberately **not** announced, because a sighted player
can't see them either. What they get is the examine description, and that's
what we'll give.

Combat is announcement only. Nothing the mod does can change the outcome of a
fight — the hooks it uses *could* turn a miss into a hit or skip a turn, and it
never touches those.

## The scanner

The look cursor feels its way around one hex at a time. The scanner is for
finding things: it asks the game for everything of a kind that is on screen and
reads it out, nearest first.

It has three levels, because a room can hold a dozen torches and stepping
through them one at a time is unbearable.

| Key | Level |
|---|---|
| `Ctrl+[` / `Ctrl+]` | **category** — critters, items, scenery |
| `[` / `]` | **type** — Torch, Rocks, Giant Ant |
| `Shift+[` / `Shift+]` | **which one** of that type |
| `/` | move the look cursor to the selected one |

How much it says depends on what you changed:

    Ctrl+]    Scenery. Torch, 6, nearest north east 4 hexes. 1 of 12.
    ]         Rocks, 3, nearest east 2 hexes. 2 of 12.
    Shift+]   south west 7 hexes, 3 of 6.

Stepping between six torches doesn't say "torch" six times — you already know
what they are; you want to know where. The count after a type name tells you
whether `Shift+]` is worth pressing at all.

Stepping the list does **not** move your cursor. Listing what is around you and
going to it are different intentions, and you may just want to look. Press `/`
when you actually want to go there — then the cursor works as it always does:
numpad + walks you there, or attacks it if it's alive and a fight is on.

### What it won't tell you

**Only what is on screen.** The engine would happily hand over every object on
the map, walls and all, but reading those out would be x-ray vision. The mod
uses the game's own "am I drawing this" test, so the line falls exactly where it
falls for a sighted player. A sighted player takes in a whole screen at a
glance — listing it one item at a time is how you get the same information
through a screen reader, not more of it.

**None of the engine's invisible furniture.** A Fallout map is carpeted in
objects that exist only to make the engine work: Block Hex Auto Inviso, Secret
Blocking Hex, Exit Grid Map Marker, Light Source. They have names, they pass the
game's own visibility flag, and the engine reports them as on screen — but no
player has ever seen one. They are recognised by the blank placeholder art they
are drawn with, a rule derived from 81,000 logged objects rather than guessed
at. On the Temple map that is 65% of everything you would otherwise have heard.

## Hotkeys this mod adds## Hotkeys this mod adds

These live on the numpad **operator** keys, since 0-9 belong to the in-game
script:

| Key | Action |
|---|---|
| Numpad + | **left mouse button** |
| Numpad - | **right mouse button** — cycles the cursor mode |
| Numpad ✳ | summary / where am I |
| Numpad / | repeat the current item |
| Numpad . | full description |

The two mouse buttons sit next to each other on `+` and `-`, unmistakable by
feel. Everything else on the numpad is a readout, so a misfire costs you a
sentence rather than an action.

A left click acts on the hex your look cursor is on: the mod moves the pointer
there first, because that is the part you cannot do yourself. What the click
then *means* is up to you and the cursor mode, exactly as it is for a sighted
player — right click cycles the mode and the mod tells you which one you landed
on.

Off the map — in the inventory, Pipboy, a dialog — numpad ✳ doesn't aim. There
are no hexes there, so it just clicks where the pointer already is.

## What gets announced

**Main menu** — the six options and their letters, on arrival.

**Character selection** — the character shown, in full:

    Character selection. Narg. Strength 8, Perception 5, Endurance 9,
    Charisma 3, Intelligence 4, Agility 7, Luck 4.
    Tagged skills: Melee Weapons, Small Guns, Throwing.
    Traits: Heavy Handed, Gifted.
    Left and right arrows cycle characters. Press T to take this one,
    M to modify it, C to create your own, or B to go back.

Cycling with Left/Right re-announces the new character.

**Character creation** — moving the selection speaks the item and its value;
changing a value speaks the new value and what you have left:

    Strength, 5
    Strength, 6, 4 points left
    Small Guns, 25 percent, tagged
    Sex Appeal, selected
    Hit Points, 30 of 30

All 59 items across the five sections are covered, and tagging a skill or
picking a trait announces how many you have left.

## Screens

The mod works out which screen you are on by reading two flags from the game,
not by guessing from content — the selection screen leaves the editor's
selection index and SPECIAL array populated, so a content-based guess narrates
character creation while you are actually choosing a premade.

**An unrecognised screen stays silent.** A confident wrong announcement is
worse than none when you cannot check it against the display.

## How it works, and what that buys you

Game memory is the only source of truth. The loop re-reads real state 20 times
a second and announces differences — it never keeps its own idea of what is
selected. That makes it impossible for the speech to drift out of sync with the
game, which is the failure that sank the earlier attempt at this.

Names and descriptions are read from the game's own loaded `.msg` text, not
hardcoded. Translations and text-replacing content mods work with no changes.

## Known limits

- **Skill percentages and derived stats are computed, not read.** The engine
  doesn't store them anywhere — it recalculates them when drawing. All 29
  formulas were verified against a live screen, so they're correct for vanilla,
  but a mod that changes skill formulas (sfall can, via `skills.ini`) would make
  these numbers wrong while the names stayed right.
- **The name-entry dialog isn't read out.** Pressing `N` in the editor opens a
  text field. The mod correctly stays on "character creation" rather than
  announcing something wrong, but it doesn't speak the field or what you type.
- **Age and gender** aren't announced yet.
- **Addresses are absolute**, confirmed against the retail Steam
  `fallout2.exe`. They survive game restarts (verified), but AoB signatures are
  needed before this works on GOG or plain 1.02d.
- Only the three named screens are covered. In-game play is not.

## Layout

    f2access.py              entry point
    fallout2_access/
      memory/                attach, read, scan
      msg/                   read the game's .msg lists from memory
      game/chargen.py        character creation state
      speech/                NVDA / SAPI / accessible_output2
      input/                 window focus + synthesized keys (dev tools only)
      offsets/               confirmed addresses
    tools/                   the reverse-engineering harness (see HARNESS.md)
