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

| Numpad + | **left click on the hex the look cursor is on** |

(Numpad / repeats the last thing said, which covers re-reading a hex.)

The mod asks the game where the pointer is several times per click, using the
apostrophe key. It isn't a key you need, and it is deliberately one nobody
reaches for.

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

A hex that reads `blocked` will not be clicked at all — there is nothing on it
to interact with and no way to walk into it, so the mod says `That hex is
blocked` rather than spending a click finding that out.

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

**The mod sets the cursor mode for you, from what you told it.** Leaving that to
you and preserving your choice was tried and cannot be made to work: reading the
world changes the cursor as a side effect, aiming reads the world several times,
and the restore that undoes the engine's meddling undoes yours along with it.
Your right click would be quietly reverted before the button ever went down.

So the mode is derived from things you actually expressed — a skill you armed
from the number row, or an enemy on the hex you picked, or neither, which means
walking. That is the same choice a sighted player makes by looking at what they
are pointing at. Numpad 0 remains the explicit reset, and is the only thing that
disarms a skill.

What has not changed is the refusal to click on a maybe: the pointer goes onto
the hex you chose, and if the game will not confirm it is really there, nothing
is sent and the mod says so.

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

## How you are doing

**Press `;` at any time** for the three numbers the interface bar shows a
sighted player permanently:

    Health 48 of 48. 8 of 10 action points. Armor class 8.

Health first, then action points, then armour class. It works everywhere � on
the map, in a fight, with the inventory open � because those are exactly the
moments you want it, and a key that only worked on the map would be missing all
of them.

Action points are only a live figure during a fight. Outside one you get the
maximum, worded as a capacity rather than a remainder: the engine keeps a
running count out of combat, but it is not a number anyone is spending, so
reading it back would be true of nothing.

All three come from the engine. None is computed here � armour class in
particular has modifiers this mod knows nothing about.

## Saving and loading

**Use F6 and F7.** They are the engine's own quick save and quick load, and they
need no screen, no list and no pointer — which makes them the only way to save
that works without sight.

They did not work out of the box, and the reason is worth writing down. sfall's
`AutoQuickSave` ships disabled, and its own comment explains what that costs:
quick saving with F6 "without picking a slot beforehand" needs it turned on.
With it off, F6 falls back to opening the save screen — and picking a slot there
needs a mouse. So the only route to a first save ran through the one screen that
cannot be used, and every test meant replaying from character creation.

`install.py` turns it on, and puts the quick saves on **their own page** so the
ten ordinary slots are left alone. F6 cycles through its page and overwrites as
it goes, which is not something to point at saves you are keeping.

| Key | Action |
|---|---|
| F6 | quick save |
| F7 | quick load |
| F4 or Ctrl-S | the save screen |
| F5 or Ctrl-L | the load screen |

The mod now watches the savegame folder and says what happened:

    Saved to slot 1.
    Slot 1 saved over.
    Game loaded.

That is deliberately read off the **disk** rather than asked of the engine.
There is no sfall hook for saving, and what a save definitely does is write a
file — so this reports a save that *happened*, not a key that was *sent*. The
distinction is the same one the mod draws before every click.

"Saved to slot 1" and "slot 1 saved over" are different on purpose. Quick save
uses the same slot repeatedly, so the interesting case is the one where you have
landed on a slot that already held a game.

### The save and load screens

Arriving on either one names it, says which page you are on, and reads the
highlighted row:

    Load game. Page 2 of 2. Slot 11, QUICK: 20/08/2026 - 01:06:20.

**The arrow keys already work.** Up and down move the highlight, and the mod
speaks each row as you land on it — the screen was navigable all along and
simply silent. Enter loads or saves the highlighted slot; Escape backs out.

The description read is the one *you* typed when saving, taken from inside
`SAVE.DAT` — confirmed byte-for-byte against five real saves. Whether a row
holds a game at all is the **engine's** answer, not the folder's, because that
is what the screen is showing and what you are about to act on.

| Key | Action |
|---|---|
| Up / Down | move the highlight (the game's own keys) |
| Numpad / | repeat the highlighted row |
| Numpad * | the screen, the page, and how many games are on it |
| Numpad + | next page |
| Numpad - | previous page |

Numpad + and - are the mouse-button keys everywhere else. On this screen there
is nothing worth clicking at, so they are given to the one control that does
need pointing at: the page arrows, which sfall only offers to the mouse.

### Pages

With `ExtraSaveSlots` on there are **a thousand** pages of ten slots, and quick
saves live on page 2 by default. So opening the load screen can easily land you
on an empty page a long way from your games.

Two things stop that mattering:

- **The load screen goes to your saves by itself.** If the page it opens on
  holds nothing and another page does, the mod walks there and says *"Went to
  the saved games."* first. The **save** screen never does this — there the page
  decides which slot gets overwritten, so it is not moved unless you move it.
- **Numpad \* tells you where they are** — *"Saved games on page 2."*

The page is read out of sfall's own memory, not counted from clicks, so
"Page 2" is a measurement. If it ever cannot be read, the mod says **"Page not
known"** and names rows by position (*"Row 3, a saved game"*) rather than
attaching a slot number it has not verified. On a screen that overwrites saved
games, a slot number nobody checked is worse than no slot number at all.

Descriptions are read from the row the engine is drawing, not looked up on disk
by slot number — so what you hear is what that row *is*.

## Combat

### Attacking

Same key as walking. Put the look cursor on the enemy with the numpad, press
numpad **+**.

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
the remainder as you spend it, since the total doesn't change. In a fight numpad
✳ reports whose turn it is and your AP, instead of the usual key reminder.

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

## Hotkeys this mod adds

These live on the numpad **operator** keys, since 0-9 belong to the in-game
script:

| Key | Action |
|---|---|
| Numpad + | **left mouse button** |
| Numpad - | **right mouse button** — cycles the cursor mode |
| Numpad ✳ | summary / where am I |
| Numpad / | repeat the current item |
| Numpad . | **what can I do to this?** (in a panel: full description) |

The two mouse buttons sit next to each other on `+` and `-`, unmistakable by
feel. Everything else on the numpad is a readout, so a misfire costs you a
sentence rather than an action.

### What can I do to this?

Point at something with the numpad and press **numpad .** on the map:

    Impenetrable Door. You can use it, look at it, use an item on it,
    use a skill on it.

That is not the mod's opinion. It is the list of icons Fallout itself would put
on screen if you held the mouse button on that object — the eye, the hand, the
backpack, the skilldex — read straight out of the engine, which decides it from
the object's own flags. So it stays right for things this mod has never heard
of.

Two things worth knowing:

- **It takes a couple of seconds**, because the pointer has to travel to the
  object first. It says "Checking…" so you know the key landed.
- **It only reads.** The menu is opened, the list is taken, and it is cancelled.
  Nothing is chosen — knowing an item *can* be used on a door is the missing
  piece; deciding to use one stays yours.

Compare two objects and you can see the engine discriminating: a pot offers
*use it*, a stone bench does not, because you cannot open a bench.

### Using an item on something — U

When the readout says **"use an item on it"**, that's the backpack icon, and it
is the one action with no cursor mode behind it. Walking, attacking, using an
object and using a skill are all "set the cursor and click"; applying one of
*your* items to something is not.

Ready the item in a hand slot, point at the target with the numpad, and press
**U**:

    Using Plastic Explosives on Impenetrable Door.

Then the game speaks for itself — whatever it would have told a sighted player
appears in the message window, which the mod already reads aloud. The mod does
**not** invent a verdict of its own; the engine knows whether the lock turned
and it doesn't.

No pointer is involved. The script already knows which hex your look cursor is
on and asks the engine to apply the item directly, so there's no aiming delay
and nothing to miss.

| It says | What happened |
|---|---|
| "Your hands are empty. Ready an item first." | nothing in the active hand |
| "Nothing there to use it on." | the hex holds no object |
| "Using X on Y." | the attempt is under way; listen for the game's reply |

**The explosive timer is still not readable.** Planting a charge opens a window
for setting the countdown, and that window has not been made usable yet — so U
will get the explosive onto the door and then leave you at a prompt the mod
cannot yet describe. That's the next piece of work, and the countdown stays
yours to choose.

A left click acts on the hex your look cursor is on: the mod moves the pointer
there first, because that is the part you cannot do yourself, then sets the
cursor mode to match what you selected.

Off the map — in the inventory, Pipboy, a dialog — numpad + doesn't aim. There
are no hexes there, so it just clicks where the pointer already is, and says
which panel is currently eating your clicks.

## Containers, looting and your inventory

Open a container the ordinary way — put the look cursor on it, press numpad `+`
— and the window announces itself with what is in it:

    Loot: Pot. 3 items. You are carrying 2 items.

The window has three lists, and the numpad walks them with the same spatial idea
as the hex cursor, so there is only one layout to learn:

| Key | Action |
|---|---|
| Numpad 8 / 2 | previous / next item in this list |
| Numpad 4 / 6 | previous / next list |
| Numpad 5 | re-read the selected item |
| Numpad 0 | totals — what you are carrying, against what you can carry |
| `A` | **take everything** in the container — the game's own TAKE ALL |

The three lists are **yours**, **theirs** (the container, the corpse, or the
person you are trading with) and **worn** — your armour and your two hands.
Opening a container starts you on its contents, because that is what you opened
it to find out.

Items read as name, how many, what they weigh, and where they are in the list:

    Knife, 1 pound. 1 of 3.
    Bottle Caps, 24. 2 of 3.
    Armor, Leather Armor.
    Item 2, empty.

An empty hand is announced rather than skipped. "Nothing in your right hand" is
the answer to "can I pick this up", and a list that silently omitted it would
leave that question unanswerable.

Lists that have nothing in them are skipped as you press 4 and 6 — your own
inventory window has no container list, and stepping onto an empty one to be
told it is empty is a key press that achieved nothing.

### Taking everything: press A

**In a loot window, `A` takes everything in the container.** It is the engine's
own TAKE ALL button, and it needs no pointer at all.

That was not in any manual — it came out of reading the engine's window
structures. Fallout draws its interface with GNW, which keeps a list of every
button in a window along with the event code each raises, and GNW's input loop
puts key presses and button presses in the *same stream*. So a button whose
event code happens to be below 256 is a button that a key already presses. The
loot window's TAKE ALL carries code 65, which is ASCII `A`.

Verified on a live game: a pot holding one Healing Powder, `A` pressed, and the
item was in the player's pack — no pointer involved.

### Moving one item

It takes two presses of **numpad +**, because a move has two ends:

1. Select the item and press numpad + — it says the item's name back.
2. Navigate to where it should go — the other list, or Armor, Item 1, Item 2 —
   and press numpad + again.

The first press sends nothing to the game at all; it is just the mod noting
what you chose. Fallout moves items by *dragging*, and a drag begun on one
keypress and finished on another would leave the game holding an item for
however long you took to navigate — a state you cannot see and the mod cannot
reliably detect. So the whole drag happens on the second press.

The six rows of each list are buttons too, but their codes are 1000–1005 and
2000–2005 — synthetic, far above the keyboard range — so unlike TAKE ALL these
need a real click. The mod reads each row's rectangle out of the engine and puts
the pointer there, which is the same job it does for a hex and for the same
reason: pointing is the part you cannot do yourself.

Three things about how it is done:

**The rectangles are the engine's, read live.** Nothing is measured off a
screenshot or computed from a layout table, so a different resolution or the
high-res patch moving a window changes nothing.

**The scroll position is caused, not read.** A list longer than six rows would
need to know how far it has scrolled. Rather than hunt for that number in
memory — another absolute address, in a project whose addresses are already why
it will not run on GOG — the scroll-up arrow is itself a button, so clicking it
more times than the list is long puts the list at the top *by construction*.

**It tells you what actually moved, not what it meant to move.** There is no way
to ask a UI "is the pointer on row three" the way the game will say which hex the
pointer is over. So the check happens afterwards: both lists are re-read and the
mod says `Moved Plastic Explosives` — or `Plastic Explosives did not move`, which
is the case you would otherwise have no way to notice.

Lists longer than six items are refused for now rather than guessed at, and say
so.

What the mod will *not* do is move items from inside the script. That would step
straight past carry weight, the action point cost of an inventory action in
combat, and whatever else the window enforces that nobody has thought of. Going
through the real interface means those rules apply because they are the same
code, not because we remembered to reimplement them.

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
- **Dialogue, the Pipboy and the world map are not covered.** Dialogue is the
  largest remaining gap and is mouse-only in the engine.
- **The inventory and loot windows are read but not operated.** You can hear
  everything in them; moving an item still needs the mouse.

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
