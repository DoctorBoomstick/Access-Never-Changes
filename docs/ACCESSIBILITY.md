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

Each SPECIAL stat is read with the word the editor prints beside it —
"Strength, 6, Good". The game abbreviates that word on screen to fit the panel
("Avrg", "Exclnt"); what you hear is the same word untruncated, because an
abbreviation is a measurement in pixels rather than something anyone reads
aloud.

`N`, `A` and `S` each open a small dialog, and the mod names it and reads its
current value: "Sex. Male.", "Age 25.", "Name. Empty." Left and right change
age and gender, and every change is spoken. **Escape cancels and the old value
is spoken back**, so a dialog you opened by accident costs nothing.

The name field is the one place the mod cannot follow you keystroke by
keystroke: the game keeps the half-typed name somewhere no address can reach,
and only writes it down when you accept it. The finished name is announced then.
If you want to hear each letter as you type it, that is your screen reader's own
"speak typed characters" setting, which works here because the mod is not
competing with it.

## The character screen, in a loaded game

Press `C` in the game and the mod reads the sheet: the seven attributes with
their rating words, the ten derived stats, the eighteen skills, your condition,
and your level and experience. The screen navigates with its own keys — Tab
moves between sections, the arrows move within one — exactly as it does
during character creation, because it is the same panel.

What changed is where the numbers come from. The mod used to read the engine's
stat table and compute the rest with the character-creation formulas, which is
right while you are making a character and wrong the moment you have one:

| | mod said | screen said | why |
|---|---|---|---|
| Perception | 8 | 6 | a drug penalty, kept in a separate table |
| Small Guns | 37% | 47% | tag skills and the points you have spent |
| Damage Resistance | 0 | 8% | your armour, added when the row is drawn |

Every one of those is a modifier the engine already totals up, so it is asked
instead — `get_critter_stat` and `has_skill` return exactly what the panel
is showing. The names are still the game's own, out of `stat.msg` and
`skill.msg`, so a translated game reads out translated.

Your condition is read from the engine's own flags, and **only what is actually
set**. The box on screen is a fixed column of labels with the applicable ones
lit, so reading the column out would announce that you are blind and missing
both legs when you are fine.

## The Skilldex, and stealth

`S` opens the Skilldex and the mod reads it out, with the key that arms each
one and how good you are at it:

    Skilldex. 1 Sneak, 49 percent. 2 Lockpick, 24 percent. 3 Steal, 24 percent.
    4 Traps, 22 percent. 5 First Aid, 37 percent. 6 Doctor, 31 percent.
    7 Science, 15 percent. 8 Repair, 17 percent.

The key number is the panel's position, not the skill's index — Sneak is
skill 8 and is armed with 1.

Arming any of them but Sneak switches the cursor, which is announced, so you
know it took. **Sneak is a toggle with no cursor**, and the game prints nothing
when it flips, so the panel now reports it: opening the Skilldex says
"Sneaking." or "Not sneaking." along with the list. Press 1 and re-open it to
hear where you ended up.

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

**You hear a short tick for each hex you cross**, and the arrival is announced
when you stop: `Moved 3 hexes.`

The tick is not an announcement. It does not interrupt, does not queue and does
not have to be listened to — its rhythm is your pace, which is what footsteps
are for a sighted player. It exists because the alternative was several seconds
of silence in the middle of a walk, and silence is also what a mod that has
stopped working sounds like: a walk across a room was being read as the mod not
responding, or the game running slowly, when a character was moving at exactly
the speed Fallout moves.

Speech could not fill that gap. Twelve "moved 1 hex" in a row is why the
arrival is announced at the end instead, and that decision was right.

`python f2access.py --no-step-sound` turns it off. The tone is generated rather
than shipped, so there is no file to replace — and no file written anywhere
either.

Readings sound like `Tree, 12 hexes` or `Radscorpion, 3 hexes`. A hex with
nothing named on it is either **empty** — you can walk there — or **blocked**,
meaning you cannot.

Your own hex names you and says which way you are looking:

    Tara, facing north east

Both halves of that were missing. Everybody else on the map has been reported
with their facing for a while, because sneaking and stealing turn on where a
back is — and yours is the one a sighted player takes in without looking for
it, from which way the figure points. The `<` and `>` keys turn you on the spot
and said nothing at all when they did. And the word for you was "you", which is
nobody's name; it comes from `obj_name` now, the same question the readout asks
about every other critter, so it arrives however your game spells it.

Inside the mod your hex still says *you*, and has to: it is one of the words
that means "nothing here to point at", and your own character is the one thing
the engine will not confirm a pointer is over. The name goes in at the moment
the line is spoken.

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

**And yourself is a target like any other.** Numpad 5 brings the look cursor
back to you, so first aid on your own wounds is `5` to arm it, numpad 5 to come
home, numpad `+`. That used to answer *"that hex is behind a wall"* and the
wording sent everyone hunting for a wall. There was none. An armed skill puts
the cursor into a mode the click check did not recognise, so it refused every
hex that had nothing standing on it, and your own hex is always one of those —
the engine's question about what is under the pointer deliberately does not
answer "you". The refusal it was reaching for protects a *walk* from landing on
something drawn over the ground, and somebody who has just armed Doctor is not
walking.

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

## Talking to people

Put the look cursor on someone and press numpad `+`. That starts a conversation
the same way a sighted player does — a click on a person with the command
cursor talks to them. You can also press numpad `.` for the action menu and
choose **talk to it** from the list.

Then the mod reads the screen: what they said, and every reply you can give,
numbered.

    Conversation. Greetings, Chosen One! It is good to see you. How may I
    serve you? 3 replies. 1, Just thought I'd say hello. 2, Can you teach me
    anything? 3, [Done]. Press the reply's number to answer.

**Press the number to say it.** That is Fallout's own binding, not something
this mod added: the engine has always bound the replies to the number keys, and
each reply's button carries the key that presses it. So a reply is chosen with a
keypress, and nothing has to be aimed at. This is the one thing in the mod that
cannot land on the wrong target.

| Key | Action |
|---|---|
| `1` – `9` | **say that reply** — the game's own keys |
| Up / Down | previous / next reply |
| Numpad 5 | re-read the reply you are on |
| Numpad + | say the reply you are on |
| Numpad / | the whole list of replies again |
| Numpad . | just what they said, again |
| Numpad ✳ | all of it, from the top |
| `B` | barter, if they will trade |

### The numpad does not choose replies

Everywhere else the numpad is the hex cursor. In a conversation the game reads a
numpad digit as the same character as the number above it, so numpad 4 — west —
was saying the fourth thing on the list. Out loud. To whoever was standing
there.

`gl_dialog.ssl` exists to stop that, and it stops the whole numpad rather than
only the keys the mod uses, because the presses that matter are the ones you
make by mistake. The rule to remember:

**In a conversation, the number row chooses a reply. The numpad never does.**

### Why walking the list never worked

Up and down step the replies. Numpad 8 and 2 were meant to, and did not — for
anybody, from the day they were written, and the reason is worth writing down
because it is invisible from the outside.

These are the mod's only hotkeys read as **Windows virtual keys**. Every other
numpad binding is a DirectInput scancode read inside the game, and a scancode is
a fact about which key you pressed. A virtual key is a fact about what the key
*means*, and Num Lock changes it: with the lock off, numpad 8 arrives as Up.

That alone would have been survivable. What made it total is that pynput, which
delivers the keys, hands over two different shapes — an ordinary key as a
`KeyCode`, which carries its virtual key, and anything it recognises as special
as a `Key` enum member, which keeps its virtual key one level further down. The
listener asked for `key.vk`, got nothing, and dropped the press.

So the keys worked with Num Lock on, for whoever wrote them, and vanished for
everyone else — and binding the arrows as a fix changed nothing at all, because
an arrow is exactly the shape that was being dropped. One line asks for both
shapes now, and the test that covers it drives real pynput objects rather than
stand-ins, since a fake with a `vk` on it would have passed the whole time.

Long replies are never cut off or scrolled: the mod reads the whole line out of
memory, so the scroll arrows a sighted player needs do not exist for you.

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

**Press `;` at any time** for the numbers the interface bar shows a sighted
player permanently, and the two beside them on the level box:

    Health 48 of 48. 8 of 10 action points. Armor class 8.
    Level 2. 1550 experience to the next level.

Health first, then action points, then armour class, then the level.

Level and experience were readable all along and had nowhere to be heard: they
are on the character sheet, which is a screen you open, read and close, and
"what level am I" is a one-word answer. What you get is **how much further**
rather than the total the next level costs — the sheet prints the total because
a sighted player reads it against the figure on the line above, and two large
similar numbers read out one after the other leave the listener doing the
subtraction that was the question in the first place.

The threshold is arithmetic rather than something read out of the game, so it
is dropped rather than reported as a negative once you are past it. It works everywhere � on
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
| Left / Right | change page (the game's own keys) |
| Numpad / | repeat the highlighted row |
| Numpad * | the screen, the page, and how many games are on it |

**Navigation here is entirely the game's own keyboard**, and the mod adds
nothing to it. Numpad + and - used to page the screen by aiming the pointer at
the page arrows and clicking them, on the belief that sfall offered the pages to
the mouse alone. It does not — left and right had been turning them all along.
Both keys are now dead on this screen, deliberately and silently.

Turning the page speaks the new page and the row you land on, because all ten
rows have just changed underneath you and the one under the highlight is the
one about to be saved over.

### Confirming a save

Pressing Enter on a slot does not save straight away. The game puts up a small
confirmation box, and until now nothing said so — the screen simply went
quiet and saving looked like it had hung.

The box is now announced, with the slot it is about:

    Save game already exists, overwrite? Slot 11, QUICK: 22/08/2026 - 03:53:22.
    Enter to confirm, Escape to cancel.

    Save to slot 20? Enter to confirm, Escape to cancel.

Enter writes the file, Escape backs out and puts you back on the list. Nothing
is said on the way out of the box: a save that lands is announced by the mod
watching the savegame folder, and a cancel re-reads the row you are on.

The overwrite wording is the game's own sentence, read out of `lsgame.msg`, so
it arrives translated. The rest is the mod describing the situation rather than
reading the box — the box's text is drawn into the window and cannot be
read back, so what you hear is assembled from what can be: which slot the
highlight is on, whether the engine says that slot holds a game, and whether
this screen saves or loads.

If the box has only one button it is a notice rather than a question, and the
mod says exactly that rather than guessing at its wording.

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

## The Pip-Boy, and resting

Press **`P`** — the game's own key — and the Pip-Boy opens. It announces the
time and the five places you can go:

    Pip-Boy. 5:27 in the afternoon. Day 26 of month 7, 2241.
    Alarm clock. Status. Automaps. Video archives. Done, closes the Pip-Boy.
    Up and down move, numpad plus chooses, numpad minus comes back here.

| Key | Action |
|---|---|
| `P` | open it — the game's own key |
| `Z` | open it **on the alarm clock** — the game's own key |
| Up / Down | move through the list |
| Numpad + | choose what you are on |
| Numpad - | back out of a page to the main list |
| Numpad / | say the entry again |
| Numpad ✳ | the time, and where you are |
| Numpad . | the whole list |
| Escape | close the Pip-Boy — the game's own key |

**`Z` goes straight to resting**, which is the shortest route there is: the
panel opens with the thirteen rest options already drawn and no clicking
involved at all. The mod notices it arrived on a page rather than on the main
list and reads the page — being read the five destinations there would describe
a screen you are not looking at, and hide the one thing you pressed Z for.

The list is walked with the arrows because there is nothing to take them from:
the Pip-Boy is mouse-only in the engine, so unlike the conversation screen no
script has to swallow a key first.

### Resting

**This is the point of the screen.** Resting is how you heal without a doctor,
and it was unreachable — a menu of fourteen rows that could only be clicked.

Choose **Alarm clock** and it reads out what the engine is offering:

    Alarm clock.
    13 ways to rest. Rest for ten minutes, 1 of 13.

The names are the game's own, out of `pipboy.msg`, so a translated game reads
out translated. There are fourteen options — ten minutes through six hours, the
four "rest until" times, until healed, and until the party is healed — and the
last one is dropped when you are travelling alone, which is the only thing that
varies. That was checked at half past five in the afternoon, when two of the
four "rest until" times had already passed that day and all four were still
listed, which rules out the obvious wrong rule: that the list is trimmed by the
clock. If the row count is ever something the rule cannot account for, the rows
are numbered instead of named, because a wrong name here rests you six hours
when you asked for ten minutes.

**What you hear afterwards is what happened, not what was asked for:**

    Rest for ten minutes.
    Rested 10 minutes. 5:37 in the afternoon. Day 26 of month 7, 2241.

That is the rule the rest of the mod follows, and here it solves a problem that
looked unsolvable. The game's refusal — *"You cannot rest at this location!"* —
is painted onto the panel like everything else on it and cannot be read at all.
But a refused rest is a clock that did not move, and the clock **can** be read
exactly. So:

    The clock has not moved, so no time passed. Either you cannot rest here,
    or there was nothing to rest for.

which also covers resting until healed when you are already well.

### The clock

The date and time come from the engine's tick counter, and the arithmetic on it
is a measurement rather than a reading. Fallout 2 writes both the raw tick count
and the in-game date into every `SAVE.DAT` header, so three real saves settle it:

| ticks | date the engine wrote | ticks ÷ 864,000 |
|---|---|---|
| 302,677 | 25/07/2241 | 0 |
| 322,141 | 25/07/2241 | 0 |
| 1,488,625 | 26/07/2241 | 1 |

A day is 864,000 ticks and day zero is 25 July 2241, stated three times by the
game itself. The first of those saves was taken 27 seconds into a new game and
302,400 ticks is exactly 08:24:00 — so the game begins at 08:24 and there is no
free number left to guess at.

**The month is said as a number, and that is deliberate.** Fallout draws month
names as art — a picture of twelve words — so there is no string in the game to
quote, and writing "July" here would be this mod inventing an English word for
something a translated game shows in its own language. It is the same call
already made about the body parts struck in combat, and the game sets the
precedent itself: the save screen prints its dates as numbers too. Evening
starts at six because the alarm clock's own row says *Rest until evening
(1800)*, and the mod disagreeing with the row directly under it would be worse
than either wording.

## Your quests, and your holodisks

Choose **Status** and the mod tells you where you have something to do, and what
you are carrying to read:

    Status.
    1 place. Numpad plus reads one out. Arroyo, 1 of 1.

Move to a place and press numpad `+` again:

    Arroyo. 3 tasks.
    1. Rescue Nagor's dog, Smoke, from the wilds.
    2. Retrieve the GECK for Arroyo.
    3. Find Vic the Trader.

A task you have finished says so — `Kill the rat god. Done.` — and that is not
the mod being helpful, it is the mod reading out something the screen already
shows. The engine keeps two thresholds for every quest, one for when it appears
and one for when it is complete, and when the second is reached **it draws that
line in a different colour**. Colour is not available to a screen reader, so it
arrives as a word instead. The comparison the mod makes is the engine's own, to
the instruction: `>=` against the same field.

The numbering matches the screen too. The engine formats each line as `"%d. %s"`
— it numbers them itself — so "task 3" means the same thing to you as it does to
somebody reading it.

The holodisks you are carrying are listed under the places, and numpad `+` reads
one from end to end:

    Power Plant Operations. 10 pages of text.
    Page 1. Memo: A.E.C., Status Brief. From: Tom Murray, Chairman, Atomic
    Energy Commission...

**The lines are joined back up.** The engine stores a holodisk hard-wrapped to
the width of the panel, about sixty characters a line. That wrapping is a fact
about the panel, not about the writing, and a screen reader has no column to
respect — so the pieces are put back together into paragraphs. Hearing a
sentence delivered in six fragments is worse than hearing it.

**Nothing is clicked for either of these.** The mod already knows what the page
would draw, because it worked the list out itself, so there is nothing to point
at and no second of pointer-driving to wait through. It is the same choice the
world's action menu makes: act on the thing you picked, by identity, rather than
by aiming at it.

### Where the words come from, since they are not on the screen

The panel keeps none of its own text. That is not a search that was given up on;
it is a negative result, checked three ways on a live game with the panel open:

- Every string address in `pipboy.msg` and `quests.msg` — 1,322 of them — was
  searched for across all writable memory. The only arrays holding any of them
  are the two message lists themselves. Nothing holds a list of the lines a page
  is drawing.
- The text of a line that was visibly on screen occurs **exactly once** in the
  whole process, in the message list it was loaded into. So the engine does not
  copy a line before drawing it either.
- A scan for the shape such a list would have — runs of `{char* text, int
  flag}` — found none anywhere.

So the list is rebuilt the way the engine builds it. What the engine has, and
the mod now reads, is the tables it parses when the panel opens:

| from | records | what each holds |
|---|---|---|
| `quests.txt` | 157 | place, task, which global variable it lives in, and the values at which it appears and is finished |
| `holodisk.txt` | 20 | which global variable says you have it, its name, and where its text starts |

The place names come out of `map.msg` and the task text out of `quests.msg`, so
both arrive in whatever language the game is running in. **Every word of a quest
is the game's own**; the only English this mod adds to that page is "tasks",
"Done." and the numbering, and even the numbering is the shape the engine uses.

**And there is no more to be had.** A quest record has five fields and that is
all the game knows: where it belongs, one sentence, which variable tracks it,
and the two thresholds. There is no step list, no giver, no reward, no location
marker, no longer description — the sentence *is* the quest. The whole Status
page, for a sighted player, is a place name and a numbered column of those
sentences, some in a different colour. That is now all read out.

**The rule was read out of the engine, not guessed at**, and the difference
mattered. The obvious rule — a place is listed once one of its quests has
started — predicted one row where the panel drew two, and an afternoon went into
trying to explain the extra one. Disassembling the drawing loop settled it in
minutes: the rule was right all along, and **the Status page creates one row
button more than it has entries**. The spare is the engine's own. Counting
buttons instead of entries would have put a phantom task at the bottom of every
list.

The loop itself, for the record: walk the quest table in order; a quest counts
once its variable has reached its display threshold; the first quest that counts
puts its place on the list, and the rest of that place's quests are then skipped.
The threshold is `>=` and it can be zero — *Retrieve the GECK* needs nothing set
at all, which is why Arroyo is listed from the first minute of the game.

### Why this is allowed to be spoken

A reconstruction that cannot be compared against anything is a guess with extra
steps. This one is checked against the engine's **own count of the lines it
drew**, which it keeps in memory while drawing them — separately for the places
and for the holodisks. If either disagrees, the rule is wrong for this state and
the entries are numbered rather than named, the same refusal the alarm clock
makes when its row count does not fit. It is better to say *"Entry 2 of 3"* than
to name somebody's quests wrongly.

**The row buttons are deliberately not part of that check.** The engine already
creates one button past the end of this list, and sfall's
`UseScrollingQuestsList` — on by default in the Restoration Project's
`ddraw.ini` — adds controls of its own on top. How many rows there are is a fact
about your install rather than about your quests, and nothing is clicked on this
page anyway, so counting them would only make the mod go quiet on somebody
else's configuration.

### Video archives, and automaps

**Video archives** lists the films you have watched, by name, out of
`pipboy.msg`. The engine keeps one byte per film, and the page walks films 2 to
15 and lists the ones set — so this is read rather than reconstructed. Choosing
one plays it.

**Automaps** is counted rather than named, and that is a decision rather than an
omission. An automap is the auto-drawn floor plan of a place you have been: a
top-down schematic of walls and rooms that fills in as you explore, generated
from tile data, with no text in it anywhere. Naming the *list* would be a small
job — the names look like they come from the same `map.msg` the quest locations
use — but what it would take you to is a picture, and a picture is not something
a screen reader can be handed. So the page says what it holds and goes no
further:

    1 entry. The Pip-Boy paints this page as a picture, so they can be
    counted and chosen but not read out.

Said once, on arrival, and never per row — a working list that made no
explanation would read as a broken one.

**One holodisk cannot be named**: the Vault 13 holodisk is the only one of the
twenty-one that the engine does not keep in the table parsed from
`holodisk.txt`, so there is no record of it here to rebuild from. It is left out
rather than invented.

### How it is driven

Every control on this panel has its event code in the **release** field, and
every one is above 256 — so unlike the loot window's `TAKE ALL`, no key presses
any of them and each has to be pointed at. The mod reads each control's
rectangle out of the engine and puts the pointer there, the same job it does for
a hex and for an inventory row. Nothing is measured off a screenshot, so another
resolution moves the panel and changes nothing here.

One wrinkle worth knowing about, because it would be invisible from outside:
**the engine does not destroy a page's rows when you leave it.** Open Status,
then the alarm clock, and the panel holds both sets — and opening the same page
twice adds a second copy of its rows. Counting the leftovers would have said the
alarm clock offers fifteen ways to rest and named every one of them wrongly. GNW
puts new buttons at the head of its list, so the live page is the run at the
head, and the mod takes exactly that run and stops — checking both that the codes
keep counting and that the rows keep stepping down the same twenty-pixel ladder.
The second test is what makes it safe: codes alone would merge a live page
starting at 510 into a stale page whose rows ended at 509, which becomes
reachable as soon as a player has three quest locations.

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
| `Ctrl+[` / `Ctrl+]` | **category** — critters, items, scenery, exits |
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

### The way out — the fourth category

    Ctrl+]    Exits. Exit Grid Map Marker, 3, nearest north east 6 hexes. 1 of 1.

Exit grids get a category of their own, because "how do I leave" is a different
question from "what is around me" and it has two or three answers on any map.
`/` walks the look cursor onto one and numpad `+` takes you there.

They were invisible to every part of this mod, twice over. An exit grid is a
MISC object, and the scanner asked the engine for critters, ground items and
scenery — three of its six lists, none of them that one. And it is drawn with
the blank placeholder art, so the filter below would have dropped it even if a
list had held it.

Both of those rules are right about everything except this. What a sighted
player sees of an exit is not the object at all: it is the shimmering border
drawn into the *floor*, which is tile art and belongs to no object anyone can
ask about. The invisible object is the only handle there is on a thing that is
plainly on screen. So the exemption is exactly one category wide.

The category currently reports everything in the engine's MISC list rather than
exit grids alone, and names each entry with the game's own name for it, so
anything else living there arrives under its own name and can be stepped past.
Narrowing it needs a rule about the engine's proto numbering that has not been
measured here yet — and the script now logs every MISC object it considers,
which is the same route the art filter itself came by.

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

### What can I do to this? — numpad .

Point the look cursor at a hex and press **numpad .**. If more than one thing is
on that hex you are asked which you mean, and then what to do to it. Two short
lists, both worked the same way:

    2 things here. Door track, 1 of 2.
    Door, 2 of 2.
    Use it, 1 of 4.

| Key | In either list |
|---|---|
| Up / Down | move through the entries |
| Enter | choose |
| Escape | back out |

A hex holding one thing skips straight to the actions, so the usual case costs
no extra keystroke.

**You are in the list.** Standing on your own hex and pressing numpad . offers
"yourself", which is how you use an item on yourself — healing powder, a
stimpak. Nothing else could reach that: everything the mod does with a pointer
asks the engine what is under it, and that question is asked in a form that
deliberately excludes your own character.

**Nothing is aimed.** The list is read straight out of the hex, and the action
runs on the thing you chose by identity rather than by pointing at it. That is
why it is instant where it used to pause for several seconds, and why it cannot
act on the wrong object — there is no pointer to land in the wrong place.
It is also why the actions offered are the mod's own short list rather than the
engine's icon strip: reading that strip means holding the button on the object,
which is the pointer trip being avoided. Use it, use an item on it, look at it
and talk to it, with talk offered only for something alive. An action the game
will not perform is still offered, and the game refuses it in its own words.

### What can I do with this item? — numpad .

Select an item with the numpad, then press **numpad .** inside the inventory.
Same idea as the map's action menu, same keys:

    Plastic Explosives. 2 actions. Use it, 1 of 2.

| Key | In the list |
|---|---|
| Up / Down | move through the actions |
| Enter | do the selected one |
| Escape | back out |

**Use it** is how an explosive gets armed, a stimpak gets used, and anything
else with a use gets used. It ends in a click on the interface bar's item slot —
the only route to using a carried item that exists, since no cursor mode means
"use an item" and the inventory window has no Use button at all. The mod swaps
your active hand if it needs to, closes the inventory, and clicks.

The item has to be **in one of your hands**; from your pack it says so. And the
mod checks which item is live before clicking, because that slot acts on the
*active* item — clicking it with a weapon live **attacks**.

**Drop it** puts the item on the ground at your feet.

One honest difference from the map's menu: **this list is the mod's, not the
engine's.** Fallout keeps no action list for inventory items — holding the mouse
button on every carried row and every worn slot left the map's action array
unchanged, still reading whatever object it was last built for. So this menu can
only ever offer what somebody here thought of, where the map's grows by itself.

### Using what is in your hand — U

On the map, **U** uses whatever is in your active hand. That is the shortcut for
the thing you will do constantly; the menu above is for everything else.

    Using Plastic Explosives.

If a **weapon** is live it refuses and says so, rather than clicking:

    Spear is a weapon. Using it from here would attack, so it is refused.

That is not caution for its own sake — the interface bar's item slot acts on the
active item, and clicking it with a weapon in hand starts a fight. It did,
during development, and dropped a live charge on the floor doing it.

`b` swaps which hand is active.

### Arming an explosive, and the countdown

Explosives do not get used *on* a door — the game does not work that way. You
arm one, set its countdown, and it is placed on the ground where you stand.

Put the charge in your **active** item slot (`b` swaps which hand is live), then
click the interface bar's item slot. The mod announces the timer:

    Explosive timer. Setting it to the shortest.
    10 seconds. Numpad plus and minus change it, Enter arms it, Escape cancels.

| Key | Action |
|---|---|
| Numpad + | ten seconds longer |
| Numpad - | ten seconds shorter |
| Numpad / | say the countdown again |
| Enter | arm it |
| Escape | cancel |

**Opening the timer places the charge on the floor.** That is the game's own
behaviour, not the mod's — so cancelling still leaves it at your feet to pick
back up.

**The mod cannot read that number, so it sets it instead.** On arrival it winds
the countdown down to its shortest by pressing the down arrow more times than
the range is long, which lands on ten seconds whatever it was showing before.
Every value after that is arithmetic the mod controls, so what it announces is
what it caused rather than what it guessed.

The number genuinely is not readable: it is not in the executable's globals, not
in sfall's, and the one heap candidate that looked right turned out to be a
tally of clicks — it rose on *both* buttons, 9 to 31 going down and 31 to 57
going up, and never clamped. Watching a value move is not evidence; watching it
move in opposite directions is.

If anything goes wrong mid-adjustment the mod says the countdown is **unknown**
rather than naming a number it no longer trusts. Escape and start again.


## Containers, looting and your inventory

Open a container the ordinary way — put the look cursor on it, press numpad `+`
— and the window announces itself with what is in it:

    Loot: Pot. 3 items. You are carrying 2 items.

The window has three lists, and the numpad walks them with the same spatial idea
as the hex cursor, so there is only one layout to learn:

| Key | Action |
|---|---|
| Up / Down | previous / next item in this list |
| Left / Right | previous / next list |
| Numpad / | re-read the selected item |
| `A` | **take everything** in the container — the game's own TAKE ALL |

**The numpad no longer does anything here.** It used to, and that was never a
design so much as an inheritance: the numpad is the hex cursor's keyboard
because a map has six directions and no north, and a list has two. These were
the only two screens in the mod that asked you to move your hand for a job the
arrows do everywhere else.

Re-reading needed no key of its own either. Numpad `/` is the repeat key on
every screen the mod has, and in this window it already says the selected item,
which is all numpad 5 ever did.

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
- **The world map's own list of places is reached through the scanner, not
  through the panel.** The seven rows down the right of the world map are the
  engine's list of places you know; `[` and `]` walk exactly that list, and
  travelling to one presses its row. The rows are never read out in the order
  the panel shows them, because the scanner sorts them by distance from you
  instead, which is the more useful order and the one that survives the list
  growing past seven.
- **Travelling to an arbitrary square scrolls the view to reach it.** The map
  shows 450×443 pixels of a 1400×1500 world, so a square that is off screen has
  to be scrolled into view before it can be clicked. That is done with the
  engine's own arrow keys, reading the scroll offset back after each press —
  but a journey to somewhere very distant will move the view several times
  before it starts.
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
