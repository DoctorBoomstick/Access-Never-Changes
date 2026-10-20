# Developing Access Never Changes

The player's manual is `docs/manual.html`. This is everything else: how the pieces fit, how to change them, and how to cut a release.

## The layout

    f2access.py              the program: settings, speech, hotkeys, launcher, and the install and uninstall subcommands
    install.py               copies the scripts into a game and sets its ini lines
    build.py                 compiles scripts/*.ssl into build/*.int
    fallout2_access/         the Python side: reads the game, says what changed
    scripts/gl_*.ssl         the in-game side: four sfall global scripts
    build/gl_*.int           the compiled scripts, committed so playing needs no compiler
    config/access.ini        the settings file players get
    lang/english.ini         the mod's words, made from the code
    docs/manual.html         the manual, and the source of README.md
    installer/               freezing the program and the Inno Setup script
    tools/                   generators, and the memory tools the addresses came from
    tests/                   python -m unittest discover -s tests -t .

The two halves meet in a log file. The scripts write lines to the game's `debug.log`; the Python side tails it and reads the game's memory directly for the screens where no script runs (the menus and character creation).

## Running from the repo

    python install.py                 put the scripts and settings into the game
    python f2access.py                run the mod against a running game
    python build.py --install         recompile the scripts, then install them

`install.py` remembers the game folder in `.game-path`; pass a path to use another. Changing a `.ssl` script needs the game restarted: global scripts bind when a save loads. The compiler comes from the sfall modders pack, found with `--compiler` and `--headers` when it is not next to the repo.

## The mod's words

Every sentence the mod says is written where it is used, in English, with a key:

    tr("combat.dies", "{name} dies.", name=who)

- Blanks are named, never `{}`, so a translation can reorder them.
- Call `tr` when the sentence is said, never at import: a module-level constant is translated before the language file has been read.
- The F1 key tables (`Binding(...)`) and screen titles (`TITLE = ...`) are translated under keys made from their own English (`i18n.tr_text`).
- The in-game scripts cannot read the language files. They write English, which the Python side parses, and `worldlog.say_script` translates the fixed phrases on the way out. A new phrase in a script needs an entry there.

After changing any of this, run `python tools/mklang.py` to rebuild `lang/english.ini`; `tests/test_locale.py` fails while it is out of date. `python tools/findstrings.py` lists string literals that still look spoken.

## The manual

Edit `docs/manual.html`, then run `python tools/mkreadme.py`. It copies the manual's body into `README.md`, which is how GitHub shows the whole manual on the repository's front page. `tests/test_manual.py` fails when the two disagree, or when a Contents link has no heading to go to.

## Releasing

1. Set the version in `fallout2_access/version.py`. The owner moves MAJOR and MINOR; PATCH moves with every change.
2. Run the tests, `tools/mklang.py --check` and `tools/mkreadme.py --check`.
3. Commit, push, then tag and push the tag: `git tag v1.0.1`, `git push origin v1.0.1`.

The tag starts `.github/workflows/release.yml`: it runs the tests, freezes the program with PyInstaller (`installer/freeze.py`, one folder), checks the frozen program runs `install.py`, builds `installer/AccessNeverChanges.iss` with Inno Setup, and attaches `AccessNeverChanges-<version>-setup.exe` to a **draft** release. Read the draft over and publish it by hand. The workflow can also be run from the Actions tab without a tag; the installer is then a download on the run. It is built there because pip on the development machine cannot reach PyPI.

What the installer does:

- asks where Fallout 2 is, suggesting a copy from Steam's or GOG's registry entries, and refuses one without sfall and the Restoration Project (`mods\rpu.dat`), saying where to get them;
- installs into `<Fallout 2>\Access Never Changes\`, which ordinary users can write to, so `access.ini` and `lang\` can be edited without admin;
- runs `AccessNeverChanges.exe install "<game>"` (that is `install.py`), offering `install.log` if anything needs the player's attention;
- adds shortcuts to the Start menu's Lights Not Included folder, each named for this mod because the folder is shared by the brand's games and mods, and the Windows 11 Start menu shows no folder inside a folder: Fallout 2 (Access Never Changes) for the game and mod together, then Access Never Changes mod only, manual, settings and folder, and Uninstall Access Never Changes. The desktop shortcut, if asked for, is also Fallout 2 (Access Never Changes).

Uninstalling runs `AccessNeverChanges.exe uninstall`, which removes the scripts and sets back only the settings the mod changed, to the values in its backups.

## Finding the game's addresses

Every engine global the mod reads is in `fallout2_access/offsets/signatures.json` as the bytes of an instruction that references it, with the operand wildcarded. The build the mod was measured against is recognised by hash and needs no scan; any other build is scanned at start, and a name that cannot be found is said out loud rather than read from the wrong place. `tools/mksignatures.py` makes the file; `tools/verifyoffsets.py` checks it against a running game.

Two ways to find something new:

- **Watch it change.** Start the game, then `python tools/f2mem.py` (`help` lists its commands). `base` takes a snapshot; change something in the game; a filter (`changed`, `= 6`, `inc`, `delta 1`) keeps only what moved to match. Repeat until one or two addresses survive, `mon` them to confirm, and `name` the survivor into `fallout2_access/offsets/found.json`.
- **Read the engine's code.** Visual Studio's `dumpbin` disassembles `fallout2.exe` (run it from PowerShell: `dumpbin /nologo /disasm:nobytes`), and grepping the output for an address finds every instruction that touches it. The same works on sfall's `ddraw.dll`. Most of the engine calls the scripts make through `call_offset` were found this way, and the notes beside them in the scripts say where.

Rules the whole mod follows, worth keeping: read state every tick rather than remembering it; take numbers from memory and words from the game's own `.msg` files; and never act on a click until the game confirms where the pointer is.
