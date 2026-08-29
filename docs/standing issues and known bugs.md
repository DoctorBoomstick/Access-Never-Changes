# Standing issues and known bugs

## Fixed since the list was written, and worth remembering why

**12. The dialogue reply keys never worked for anyone.** Not a Num Lock
problem, though Num Lock is how it hid. These three are the mod's only hotkeys
read as Windows virtual keys rather than as scancodes inside the game, and
pynput delivers keys in two shapes: an ordinary key as a `KeyCode`, which has a
`vk`, and anything it calls special as a `Key` enum member, which keeps its `vk`
one level down in `Key.up.value.vk`. The listener read `key.vk` and dropped
everything else.

So numpad 8 worked with Num Lock on — a `KeyCode`, vk 104 — and disappeared with
it off, when Windows reports VK_UP and pynput calls that `Key.up`. And binding
the arrows changed nothing, because an arrow is precisely the shape being
dropped. `key_vk` asks both shapes now. The test drives real pynput objects: a
fake with a `vk` attribute would have passed throughout the bug's life.

**3. The numpad is out of the inventory and loot windows.** Arrows only. Numpad
`/` re-reads the selected item, which is all numpad 5 ever did. **Numpad 0 is
still bound and is not a player key** — it makes the script report the totals,
and the mod presses it itself to check whether a moved item actually moved. A
keypress is the only channel there is for asking that script anything.

**2. The save and load screen has no mod keys at all.** Numpad + and - are dead
there, silently. They drove the page arrows with the pointer before anybody
tried left and right, and then briefly spoke a reminder instead, which is still
a binding and still a sentence nobody asked for.

## Still open

**13. The display strip reads out heap noise once its anchor goes stale.**
Seen live while testing the Pip-Boy: `D?`, `pE?`, `??`, spoken over and over on
top of everything else. `displaywin.py` now refuses to speak a record that
cannot be a sentence — control characters, or a scrap two characters long — and
that stops the noise reaching the player, but **it is a guard and not a cure**.
The cause is that the anchor the message ring is read from goes stale when the
engine moves the ring, and every read after that is of somebody else's memory.
The right fix is to notice that and go looking again, the way `pump_display`
already does when a new game loads. Until then the mod goes quiet about the
game's own sentences rather than talking nonsense, which is the safer of the
two failures but is still a failure.

**1. The race tab RPU adds to character creation.** Identified: it is sfall's
Hero Appearance Mod, `EnableHeroAppearanceMod=1` in `ddraw.ini`, with the
race/style art in `appearance/`. sfall gives its window a game mode of its own —
`HEROWIN`, 0x40000 — which this mod already reads and, probably wrongly, names
"party member screen" in `screens.py`. So the detector may already exist under
the wrong label. Confirm the mode first, then read the window's buttons.

**10. Speech check chances during dialogue.** No evidence found. The dialogue
option struct has no chance field, nothing in `ddraw.ini` enables such a
display, and a speech check is a `roll_vs_skill` call inside an individual map
script, worked out at the instant you pick the line — so there is nothing
sitting anywhere to read. If you have seen a percentage on screen, an example
would settle it.

**11. The Pip-Boy — done, apart from the automap list.** The panel is a screen
of its own: announced, walked with the arrows, driven by clicking the engine's
own rectangles. The alarm clock is read and operated in full, the clock's
arithmetic is pinned against three real `SAVE.DAT` headers, and Status,
holodisks and Video archives are read out.

None of that content is on the screen to be read, and that is a negative result
rather than an unfinished search:

- Every string address in `pipboy.msg` and `quests.msg` — 1,322 — searched for
  across all writable memory with the panel open. The only arrays holding any
  of them are the two message lists themselves.
- `"Rest for ten minutes"`, visibly on screen at the time, occurs **exactly
  once** in the process. The engine does not copy a line before drawing it.
- No runs of `{char* text, int flag}` anywhere.

So it is rebuilt instead, from the tables the engine parses when the panel
opens. Addresses, all confirmed live and all signatured:

    0x0051C128 / 0x0051C12C   quests.txt, 157 records of 20 bytes:
                              place (map.msg), task (quests.msg), global
                              variable, display threshold, done threshold
    0x0051C130 / 0x0051C134   holodisk.txt, 20 records of 12 bytes:
                              global variable, name (pipboy.msg 401-420),
                              where its text starts (pipboy.msg 2000+)
    0x0051C138                how many rest options the alarm clock offers
    0x005186C0                the game's global variables
    0x00596C78                one byte per film, 1 once watched
    0x00631D48                map.msg -- the place names
    0x00664410                quests.msg -- the task text
    0x00664418, 0x0066444C    the engine's own count of the lines it drew
    0x00664520, 0x0066450C    for Status, Archives and Automaps

**Two hours went on a wrong assumption that a disassembler settled in five
minutes.** The obvious filter — a place is listed once one of its quests has
started — predicted one row where the Status page drew two, and the gap was
chased through three different theories about what the rows were. `dumpbin
/disasm` (which ships with Visual Studio and was already on the machine)
showed the drawing loop: the rule was right, and **the Status page simply
creates one row button more than it has entries**. Read the code sooner.

`pipboy.msg` 500–516 are the archive films, and 1000 upward is holodisk body
text with `**END-PAR**` and `**END-DISK**` markers, hard-wrapped to the panel.

**The automap list is deliberately not named.** An automap is a floor plan
drawn from tile data with no text in it, so naming the list would only take you
to a picture. Not worth doing, decided rather than forgotten. If that is ever
revisited: the count is at 0x0066450C, the renderer at 0x00499150, and the
names look like they come from the same `map.msg` the quest locations use.

**Still open: the Vault 13 holodisk**, the one of twenty-one that is not in the
table parsed from `holodisk.txt`, so there is no record of it to name.

The original dump, kept because the codes are still the map of the panel:

    window id 5, at (192,94), 640x480, 7 buttons

    id  rect (window-relative)   size    release
    11  (124, 13)-(151, 36)      28x24   504
    12  (140,334)-(150,347)      11x14   768
    13  (140,348)-(150,361)      11x14   769
    14  ( 53,340)-( 67,355)      15x16   500
    15  ( 53,394)-( 67,409)      15x16   501
    16  ( 53,423)-( 67,438)      15x16   502
    17  ( 53,449)-( 67,464)      15x16   503

The four at x=53 are the menu lights, top to bottom, which by the on-screen
description are STATUS, AUTOMAPS, ARCHIVES and CLOSE. 768 and 769 are a small
pair, almost certainly a list's up and down. 504 sits alone at the top.

**Every code is in the release field, and every one is above 256.** So no key
presses any of them — this is the inventory-row case, not the TAKE ALL case, and
each has to be clicked by its rectangle. The mod already does exactly that for
inventory rows and for the save screen's page arrows, so the route exists.

Both open questions in that dump have since been answered. The other pages were
looked at, from a freshly opened panel each time so nothing was left over:

    STATUS      500   2 rows, codes 507 508, at y=66 and 86
    AUTOMAPS    501   1 row,  code  507
    ARCHIVES    502   2 rows, codes 507 508
    ALARM CLOCK 504   13 rows, codes 510 to 522, y=96 to 336

A row is 350x10 at x=254 and rows sit 20 pixels apart. Row codes are 505 plus
the engine's line number, so the number a page starts at is how many header
lines it draws above its list. **Rows leak**: leaving a page does not destroy
them and re-rendering one adds a second set, which `pipboy.rows` handles by
taking only the run at the head of GNW's list.

And the game mode read 1024 — `PIPBOY`, 0x400 — throughout, which is what
`screens.detect` now keys off.

**Still unidentified: the pair at (140,334) and (140,348), codes 768 and 769.**
They are present on every page. Nothing is bound to them, deliberately — this
project does not ship a key whose effect it has not watched.
