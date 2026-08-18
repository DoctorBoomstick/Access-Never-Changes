# Fallout 2 accessibility — memory harness

Phase 0 of the mod. This finds and **proves** the engine addresses everything
else will be built on. No speech code gets written until the symbols below are
confirmed against what is actually on screen.

## Why this exists

The main menu and character creation are engine screens. sfall global scripts
do not run during either, so scripts cannot see them. The old `bridge.py`
worked around this by keeping its own idea of the menu position and counting
arrow keys — shadow state, with no way to notice when it drifted.

This design inverts that: **the game's memory is the only source of truth.**
Every tick we re-read state rather than remembering it. Desync stops being
possible, and a mis-click is self-correcting because you hear what actually
happened, not what we assumed.

## Ground rules

- **Read-only.** The process is never opened for writing. We observe; we drive
  the game through normal input.
- **Signatures, not hardcoded addresses.** Ship AoB patterns, resolve at attach
  time. One build then works on Steam, GOG and plain 1.02d.
- **Fail loudly.** An unresolved signature must be reported by name. A wrong
  address is far worse than a missing one — it speaks confident nonsense.
- **Indices from memory, text from `.msg`.** Read *which* skill is selected out
  of memory, then look the name up in the game's own `skill.msg`. Never
  hardcode `"Strength"`. This is what makes the mod language-agnostic and
  keeps it compatible with content mods rather than fighting them.
- **Windowed mode is mandatory.** `WINDOWED=1` in `f2_res.ini`. Exclusive
  fullscreen DX9 starves the low-level keyboard hook.

## Running it

Start Fallout 2 first, then:

    python tools/f2mem.py

`help` lists commands. Addresses are hex; scan values are decimal unless
`0x`-prefixed. Confirmed addresses are recorded with `name` into
`fallout2_access/offsets/found.json`.

## The core loop

`base` captures a snapshot. You then change something in the game, and a filter
(`changed`, `= 6`, `inc`, ...) keeps only the addresses that moved to match.
Repeat until one or two survive, then `mon` to watch them live and confirm.

By default the haystack is the exe's writable regions — a few megabytes, where
Fallout 2 keeps its globals. `where all` widens to every writable region if
something turns out to be heap-allocated.

## The engine's own keyboard map

Confirmed from fallout2-ce's `mainmenu.cc`, `character_selector.cc` and
`character_editor.cc` (a faithful reimplementation of this engine). **All three
screens are fully keyboard-driven — no mouse needed.** This is why the mod is
mostly "read state and announce" rather than "synthesize clicks".

Main menu — letter hotkeys only, **no arrow navigation, no selection index**:

| Key | Action |
|---|---|
| `N` | New game |
| `L` | Load game |
| `I` | Intro |
| `O` | Options |
| `C` | Credits |
| `E` or Escape | Exit |

Premade character selection:

| Key | Action |
|---|---|
| Left / Right | previous / next premade |
| `C` | Create character (into the editor) |
| `M` | Modify the selected premade |
| `T` | Take the selected premade as-is |
| `B` or Escape | Back |

Character editor:

| Key | Action |
|---|---|
| Tab | cycle section: stats → skills → traits → folders → derived |
| Up / Down | move selection |
| Left / Right, or `-` / `+` | decrease / increase the selected value |
| `N` | edit name |
| `A` | edit age |
| `S` | edit gender |
| `O` | options |
| `D` or Enter | Done |
| `C` or Escape | Cancel |

## Recipes

### `characterEditorSelectedItem` — do this one first

The linchpin. One global says what is focused, across stats, skills, derived
stats and traits. Everything the editor announces hangs off it.

It moves by exactly 1 per arrow press, which makes `delta` a very sharp filter:

    type i32
    base
    <press Down once>
    delta 1
    base
    <press Down once>
    delta 1
    base
    <press Up once>
    delta -1
    mon              <arrow around and confirm it tracks>
    name char_editor_selected 0xXXXXXXXX i32

fallout2-ce's index ranges are roughly: 0-6 SPECIAL, 7-9 level/exp, 10-42
folder view, 43-50 conditions, 51-60 derived stats, 61-78 skills, 82-97 traits.
**Treat those as provisional** — they come from a reimplementation, and the
exact boundaries must be confirmed by tabbing around with `mon` running and
writing down what index each real item reports.

### SPECIAL stats

Two ways in. Adjusting is the direct one — select Strength, then:

    type i32
    = 5
    <press Right, Strength becomes 6>
    = 6
    <press Left twice, Strength 4>
    = 4
    mon
    name char_stat_strength 0xXXXXXXXX i32

Cycling premades on the *previous* screen is the sharper signal if you're
still there: each premade has entirely different SPECIAL, so `base` then
Left/Right then `changed` lights up the whole array at once.

Either way, follow up with `dump <addr> 40`. Fallout 2 stores SPECIAL as a
contiguous array, so one confirmed address should yield all seven.

### Character points remaining

Starts at 5 and falls as you spend. `base`, press Right on a stat, then `dec`.

### Tagged skills

Untagged slots hold `-1`.

    type i32
    base
    <tag a skill>
    changed
    list

Expect an array of 4 ints plus a "tags remaining" counter nearby.

### Traits

Same shape: a short array of indices, `-1` when empty, plus a remaining count.

### Character name

A char buffer, so scan bytes rather than ints. Press `N`, type `Xyzzy`, then:

    aob 58 79 7A 7A 79

### Main menu — nothing to scan

The main menu has **no arrow-key navigation and no highlighted-button index**.
It is letter hotkeys only (see the keyboard map above). There is no selection
state in memory to read, so the main menu needs no symbol at all: detect the
screen, announce the options and their letters once, and let the player press
one.

This is worth stating plainly because the previous design got it wrong. The old
`bridge.py` phantom menu cycled a 5-item list on Up/Down and acted on Enter —
keys the main menu does not bind. It was narrating a selection the game did not
have.

### Screen discriminator

The poll loop needs to know which screen is showing. Find a global that differs
between main menu and char creation: `base` at the menu, enter chargen, then
`changed` and `between 0 20`. Confirm it returns to its menu value on exit.

## Known risks to test early

- **HRP moves widget rectangles.** Mostly defused: since both screens are
  keyboard-driven we don't need click targets for the near-term goal. It comes
  back if we ever synthesize clicks, and the *state* globals should be
  untouched by HRP regardless — it changes layout and rendering, not variables.
- **Some state may be heap-allocated**, in which case its address changes per
  run and needs a pointer path or a signature-resolved static root. `where all`
  finds it; a stable path is then required before it can be shipped.

## Status

Confirmed against the retail Steam `fallout2.exe` (image base `0x00400000`,
sfall 4.4.8 + built-in HRP). Full detail in `fallout2_access/offsets/found.json`.

| Symbol | Address | RVA | How confirmed |
|---|---|---|---|
| `char_editor_selected` | `0x005709EC` | `0x1709EC` | prediction test: +3 after 3x Down, returns after 3x Up |
| `char_editor_condition_name_ptr` | `0x005700F4` | `0x1700F4` | walked all 8 condition items |
| `char_editor_trait_name_ptr` | `0x005705B8` | `0x1705B8` | walked all 16 traits |
| `char_editor_trait_desc_ptr` | `0x005705CC` | `0x1705CC` | walked all 16 traits |
| `msg_editor` | `0x0056FCA8` | `0x16FCA8` | count 255 matches array |
| `msg_stat` | `0x0066817C` | `0x26817C` | count 97, holds SPECIAL 100-106 |
| `msg_skill` | `0x00668080` | `0x268080` | count 96, holds 18 skills 100-117 |
| `msg_trait` | `0x0066BE38` | `0x26BE38` | count 32 |
| `msg_perk` | `0x006642D4` | `0x2642D4` | count 234 |

### Measured section map

Tab cycles five sections. Ranges are **measured, not borrowed** — they differ
from fallout2-ce's, and two contain genuine non-contiguous outliers that were
verified stable across ~200 samples each.

| Section head | Items | Indices | Meaning |
|---|---|---|---|
| 0 | 7 | 0-6 | SPECIAL |
| 10 | 8 | 10-17 | Condition (HP, poisoned, radiated, eye, 4 crippled limbs) |
| 18 | 10 | 18-23, **83**, 24-26 | Derived stats |
| 28 | 18 | 28-45 | Skills |
| 55 | 16 | 55-67, **94**, 69-70 | Optional traits |

`83` and `94` are real indices, not read races. `94` is "Sex Appeal", sitting
exactly where the standard trait order puts it.

### Label sources per section

| Section | Source |
|---|---|
| SPECIAL | `msg_stat` 100-106 |
| Condition | `char_editor_condition_name_ptr`, or `msg_editor` 311-318 |
| Derived | `msg_editor` 305-318 / `msg_stat` 107+ |
| Skills | `msg_skill` 100-117 |
| Traits | `char_editor_trait_name_ptr` / `_desc_ptr` |

### Still open

- **Values** — SPECIAL numbers, skill percentages, unspent character points,
  tag and trait counters. Labels are solved; the numbers beside them are not.
- **Screen discriminator** — which screen is showing, for the poll loop.
- **AoB signatures** — everything above is an absolute address. Signatures are
  required before this ships against GOG or 1.02d.
