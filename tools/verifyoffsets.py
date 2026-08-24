#!/usr/bin/env python3
"""Do the resolved addresses hold what their names claim?

Signatures prove that a pattern matched once and that the operand came back out
of it. They do not prove the address means anything. A pattern can be unique,
resolve cleanly, and point at the wrong variable -- and that failure is silent,
because the read succeeds and returns a number.

So this asks the only question that catches it: on the screen that owns a
value, is the value plausible? Seven SPECIAL stats between 1 and 10 is not
something a wrong address produces by accident. Neither is a name buffer that
reads as text, nor a window count that is small and positive.

    python tools/verifyoffsets.py

Reports on whatever screen is currently up and says which checks it could not
run, so nothing is silently skipped. Walk the game through the main menu,
premade selection, the character editor, a loaded save and the load screen to
cover everything.

Nothing here presses a key. Driving the game belongs in the harness with the
safe-navigation table in game/screens.py, which exists because Escape means
"back" in the editor and "quit" at the main menu.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fallout2_access.game import (                            # noqa: E402
    actions, chargen, dialogue, pointer, premade, screens, slotscreen,
    uiwindow,
)
from fallout2_access.memory import resolve                    # noqa: E402
from fallout2_access.memory.process import (                  # noqa: E402
    FALLOUT_EXE_NAMES, Process, ProcessNotFound,
)

OK, BAD, SKIP = "ok", "WRONG", "skipped"


def check(proc, screen):
    """(label, verdict, detail) for every check that applies here."""
    out = []

    def add(label, verdict, detail=""):
        out.append((label, verdict, detail))

    # -- always readable -----------------------------------------------------
    count = proc.read_i32(uiwindow.WINDOW_COUNT)
    add("WINDOW_COUNT small and positive",
        OK if count is not None and 0 < count <= 51 else BAD,
        "reads {}".format(count))

    live = uiwindow.live_window_addresses(proc)
    add("WINDOW_LIST gives real windows",
        OK if live else BAD, "{} open".format(len(live)))

    mx = proc.read_i32(pointer.MOUSE_X)
    add("MOUSE_X on screen",
        OK if mx is not None and -1 <= mx <= 4096 else BAD,
        "reads {}".format(mx))

    # -- screen flags --------------------------------------------------------
    menu = proc.read_i32(screens.MENU_FLAG)
    editor = proc.read_i32(screens.EDITOR_FLAG)
    window = proc.read_i32(screens.EDITOR_WINDOW)
    if screen == screens.MAIN_MENU:
        add("MENU_FLAG is 1 here", OK if menu == 1 else BAD, str(menu))
    elif screen == screens.SELECT:
        add("EDITOR_FLAG is 1 here", OK if editor == 1 else BAD, str(editor))
        c = proc.read_i32(premade.COUNTER_ADDR)
        add("PREMADE_COUNTER readable",
            OK if c is not None and 0 <= c < 1 << 20 else BAD, str(c))
    elif screen == screens.CHARGEN:
        add("EDITOR_WINDOW >= 0 here", OK if (window or -1) >= 0 else BAD,
            str(window))
    else:
        add("screen flags", SKIP, "not a pre-game screen")

    # -- the character editor's own tables -----------------------------------
    if screen in (screens.CHARGEN, screens.SELECT):
        stats = [proc.read_i32(chargen.SPECIAL_ADDR + 4 * i) for i in range(7)]
        good = all(s is not None and 1 <= s <= 10 for s in stats)
        add("SPECIAL is seven values in 1..10", OK if good else BAD, str(stats))

        age = proc.read_i32(chargen.AGE_ADDR)
        add("AGE is plausible", OK if age is not None and 16 <= age <= 99
            else BAD, str(age))
        sex = proc.read_i32(chargen.SEX_ADDR)
        add("SEX is 0 or 1", OK if sex in (0, 1) else BAD, str(sex))

        name = proc.read_cstring(chargen.NAME_ADDR, max_len=32)
        add("NAME reads as text",
            OK if name and name.isprintable() and name.strip() else BAD,
            repr(name))

        tags = [proc.read_i32(chargen.TAGS_ADDR + 4 * i) for i in range(4)]
        good = all(t is not None and (t == -1 or 0 <= t < 100) for t in tags)
        add("TAG_SKILLS are indices or -1", OK if good else BAD, str(tags))

        traits = [proc.read_i32(chargen.TRAITS_ADDR + 4 * i) for i in range(2)]
        good = all(t is not None and (t == -1 or 0 <= t < 32) for t in traits)
        add("TRAITS are indices or -1", OK if good else BAD, str(traits))
    else:
        add("editor tables", SKIP, "not on an editor screen")

    # -- the message lists ---------------------------------------------------
    for label, addr in (("MSG_STAT", chargen.MSG_STAT),
                        ("MSG_SKILL", chargen.MSG_SKILL),
                        ("MSG_TRAIT", chargen.MSG_TRAIT)):
        n = proc.read_i32(addr)
        add("{} holds a message count".format(label),
            OK if n is not None and 0 < n < 4096 else BAD, "reads {}".format(n))

    # -- dialogue ------------------------------------------------------------
    n = proc.read_i32(dialogue.OPTION_COUNT)
    handle = proc.read_i32(dialogue.WINDOW)
    if handle is not None and handle >= 0:
        add("DLG_OPTION_COUNT sane while talking",
            OK if n is not None and 0 <= n <= 30 else BAD, str(n))
    else:
        add("dialogue", SKIP, "no conversation open")

    # -- the slot list -------------------------------------------------------
    if screen == screens.SLOTS:
        sel = proc.read_i32(slotscreen.SELECTION)
        add("SLOT_SELECTION in range",
            OK if sel is not None and 0 <= sel <= 20 else BAD, str(sel))
    else:
        add("save/load slots", SKIP, "not on the slot screen")

    # -- the engine's action menu -------------------------------------------
    n = proc.read_i32(actions.MENU_COUNT)
    add("ACTION_MENU_COUNT is small",
        OK if n is not None and 0 <= n <= 16 else BAD, "reads {}".format(n))

    return out


def main() -> int:
    try:
        proc = Process.attach(FALLOUT_EXE_NAMES)
    except (ProcessNotFound, OSError):
        print("Fallout 2 is not running.")
        return 1

    result = resolve.bind(proc)
    print("executable {}...".format(result.exe_sha256[:12]))
    print("{} addresses, {} by scan\n".format(
        len(result.addresses), "resolved" if result.scanned else "recognised"))

    screen = screens.detect(proc, in_game=False, mode=None)
    print("screen: {}\n".format(screen))

    rows = check(proc, screen)
    width = max(len(r[0]) for r in rows)
    bad = 0
    for label, verdict, detail in rows:
        if verdict == BAD:
            bad += 1
        print("  {:<{}}  {:<8} {}".format(label, width, verdict, detail))

    ran = sum(1 for r in rows if r[1] != SKIP)
    print("\n{} checked here, {} wrong, {} not applicable on this screen"
          .format(ran, bad, len(rows) - ran))
    if bad:
        print("A wrong reading means the signature found a real instruction "
              "that references the wrong variable. Re-derive that name.")
    return 2 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
