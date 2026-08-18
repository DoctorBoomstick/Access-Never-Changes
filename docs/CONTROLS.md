# Fallout 2 controls, screen by screen

Reference for building the accessibility mod against the game as it actually
is, rather than as we guess it to be. Every keybinding below is tagged with
where it came from, because this project has already lost a session to treating
a documentation claim as fact.

| tag | means |
|---|---|
| **[manual]** | Fallout 2 manual, Appendix 9 "Quick Keys" and the interface chapters. Official, but describes vanilla 1998. |
| **[ini]** | Read out of this installation's `ddraw.ini`. True for *this* machine; a different sfall config differs. |
| **[live]** | We confirmed it against the running retail exe ourselves. |
| **[unverified]** | Believed, not tested. Do not build on these without checking. |

A note on the manual: sfall's documentation said cursor modes 4–10 were
Skilldex skills. Live logs showed those values tracking the direction the view
had just scrolled. The manual is a better source than sfall's notes, but it is
still a 1998 document describing an engine that has been patched since.

---

## Anywhere in the game

**[manual]**

| Key | Action |
|---|---|
| F1 | Help |
| F2 / F3 | Master volume down / up |
| F4 or Ctrl-S | Save game |
| F5 or Ctrl-L | Load game |
| F6 / F7 | Quick save / quick load |
| F10 or Ctrl-X | Exit to main menu |
| F12 | Save screenshot |
| Ctrl-P | Pause |
| `-` / `+` | Brightness down / up |

`F10` and `Ctrl-X` drop you to the main menu without warning. Treat them the
way we treat Escape: destructive, and never sent by a tool that has not
confirmed which screen it is on.

---

## Main menu

**[live]** — confirmed by reading the engine and by playing it.

| Key | Action |
|---|---|
| N | New game |
| L | Load game |
| I | Intro |
| O | Options |
| C | Credits |
| E or Esc | Exit |

**There is no arrow-key navigation and no highlighted-button index.** Letter
hotkeys are the entire interface. This is why the mod needs no memory symbols
here — there is no selection state to read, only six letters to announce.

*Mod status: covered.*

---

## Character selection (premades)

**[live]**

| Key | Action |
|---|---|
| Left / Right | Cycle the three premade characters |
| C | Create your own character |
| M | Modify the selected premade |
| T | Take the selected premade as-is |
| B or Esc | Back |

*Mod status: covered — name, SPECIAL, tags and traits are announced on arrival
and on each cycle.*

---

## Character creation / character editor

**[live]** for the keys, **[manual]** confirms Tab and the arrows.

| Key | Action |
|---|---|
| Tab | Next section: SPECIAL → traits → condition → derived → skills |
| Up / Down | Move within a section |
| Left / Right, or `-` / `+` | Lower / raise the selected value |
| N | Edit name |
| A | Edit age |
| S | Toggle gender |
| O | Options |
| D or Enter | Done |
| C or Esc | Cancel |

`N` opens a text field that swallows every following keystroke. This has ruined
a test run before — see the note in `screens.py` about why tools must detect the
screen before sending anything.

*Mod status: covered for all 59 items. **Not** covered: the name-entry field,
age, gender.*

---

## Local map — normal exploration

**[manual]**, Appendix 9.

| Key | Action |
|---|---|
| A | Attack — starts combat |
| C | Character screen |
| I | Inventory |
| P | Pipboy |
| Z | Pipboy alarm clock (rest) |
| S | Skilldex |
| O or Esc | Options |
| B | Toggle active items |
| M | Toggle mouse mode (movement ↔ command cursor) |
| N | Toggle active item mode |
| 1–8 | Arm a Skilldex skill: 1 Sneak, 2 Lockpick, 3 Steal, 4 Traps, 5 First Aid, 6 Doctor, 7 Science, 8 Repair |
| ? | Show date and time |
| `<` / `>` | Rotate character counter-clockwise / clockwise |
| Tab | Automap |
| Home | Centre the screen on your character |
| Enter | DONE (outside combat) |

Mouse: left-click acts with the current cursor; **right-click toggles the cursor
mode**, which is why the mod uses an explicit "force movement cursor" instead —
a toggle is a coin flip when you cannot see which state you are in.

Two things worth flagging for us:

- **`M` is the vanilla equivalent of our numpad 0**, except it toggles rather
  than sets. Ours is the safer verb.
- **`1`–`8` arm a skill cursor.** This is almost certainly how a skill got armed
  during an early session and made every click test fail — a stray number key,
  not the Skilldex panel.

*Mod status: hex cursor, object reading and aimed click-to-move all work. **Not**
covered: any of the keys above are announced or explained in play.*

---

## Combat

**[manual]**

| Key | Action |
|---|---|
| A | Start combat |
| Space | End turn |
| Enter | End combat |

Action Points are shown as a row of lights on the interface bar; they glow only
during your turn, and blink off one at a time as you spend them. Opening the
inventory during combat costs AP; outside combat it is free.

**This is the next frontier and it is almost entirely unbuilt.** Nothing
announces whose turn it is, how many AP remain, what hit what, or for how much.
`get_game_mode`'s COMBAT bit (0x40) is already wired up, so entering combat
announces itself and nothing else does.

*Mod status: entering and leaving combat is announced. Everything else is
missing.*

---

## Dialogue

**[manual]**, pages 65–68.

> "Select a line of dialogue for your character to say by moving the mouse
> cursor over an option, and when the line highlights, click the left-button."

**Dialogue is mouse-only.** The manual documents no keyboard selection at all.
Arrow keys scroll the REVIEW window, and that is the only keyboard involvement
described.

This is the single largest accessibility gap in the game, and it needs the same
treatment we built for hexes: enumerate the options, let the player choose one
by keyboard, then aim the pointer at it and click. The difference is that the
targets are UI rectangles rather than map hexes, so `tile_under_cursor` is no
help — we will need the dialogue window's geometry, probably via
`get_window_attribute`.

*Mod status: nothing.*

---

## Inventory

**[manual]** for the list keys, **[ini]** for the sfall modifiers.

| Key | Action |
|---|---|
| Home / End | Jump to top / bottom of the list |
| PgUp / PgDn | Jump one screen up / down |
| Left Shift | Move or drop a whole stack without the "Move Items" window |
| Left Ctrl | Move items between lists by clicking, no dragging |

When moving part of a stack you can type the quantity directly on the keyboard,
up to 99999, instead of using the `+`/`-` buttons.

*Mod status: nothing.*

---

## Barter and trade

**[manual]** — drag items between the lists and the table, press TRADE or
BARTER. No keyboard equivalent documented. Same problem as dialogue.

*Mod status: nothing.*

---

## Other screens

**[manual]**, all mouse-driven with no documented hotkeys beyond the global set:
Pipboy, Skilldex, character screen, automap (Tab), world map, save, load,
preferences.

Save and load: single-click a slot to select, double-click or press DONE to
commit; type a description and press Enter.

*Mod status: nothing.*

---

## Conflicts with this installation

**[ini]** — read from `ddraw.ini`, `[Input]`.

**Ctrl + numpad 0–6 changes the game speed.** The configured scancodes are
`SpeedKey0=0x52` through `SpeedKey6=0x4d`, which are numpad 0, 1, 2, 3, 4, 5, 6
— *exactly* the keys our hex cursor uses. The modifier is `SpeedModKey=-1`,
meaning either Ctrl key, so the two only collide while Ctrl is held.

> **Don't hold Ctrl while moving the look cursor**, or you will silently change
> the game speed. Setting `SpeedModKey=0` in `ddraw.ini` would disable the
> modifier entirely and make the collision unconditional — do not do that.

Other configured keys: `MiddleMouse=48` (middle button sends `B`),
`ItemFastMoveKey=42` (left Shift), `ItemMoveSkipDragKey=29` (left Ctrl).

**`BackgroundKeyboard=1` and `BackgroundMouse=1` are set.** The game accepts
keyboard and mouse input even when it is not the foreground window. This cuts
both ways for us: our synthetic input can reach the game without focus, and
input meant for another window can reach the game too. It does **not** make our
focus guards redundant — `require_focus` exists to stop keystrokes landing in
the terminal, which is a separate failure — but it does mean "the game was not
focused" is not a reliable explanation for input that appears to have gone
missing.

---

## Suggested build order

Ranked by how much of the game each unlocks per unit of work:

1. **Combat.** Turn and AP announcements first — not knowing whose turn it is
   makes every other combat feature pointless. Then damage and death, which
   `HOOK_COMBATDAMAGE` and `HOOK_ONDEATH` already deliver; both fired reliably
   in the old `gl_speech.ssl`.
2. **Dialogue.** The biggest gap, and the most mechanically involved, because it
   needs UI-rectangle aiming rather than hex aiming. Everything narrative in
   Fallout 2 is behind it.
3. **Inventory.** Has real keyboard navigation already (Home/End/PgUp/PgDn), so
   it is mostly a matter of reading the list selection out of memory — closer to
   the character-editor work than to the dialogue work.
4. **Interface bar and status.** HP, AP, active item, and what the six buttons
   do. Cheap, and useful in every other screen.
5. **Barter, Pipboy, world map.** Each needs the dialogue-style UI aiming, so
   they get much cheaper once dialogue is solved.
