"""Set off across the world map, and only say so once the engine agrees.

Two ways to start travelling, because the engine has two and they are good at
different things.

**The list of places.** The world map's right-hand panel holds seven buttons
with consecutive event codes from 350, backed by an array of area indices the
engine builds when the map opens. Pressing one sets the destination to that
area's world position -- the engine's own code at 0x004C034E looks the row up,
checks the area is known, and calls the same "go here" routine a click on the
map calls. This is the better route whenever the target is a place: the buttons
never move, so nothing has to be scrolled into view first, and the destination
that comes back is the area's exact coordinates rather than wherever a pointer
happened to land.

**A click on the map.** For everywhere else -- an empty square, somewhere the
player has not been, a spot a quest described rather than named. The conversion
is exact in both directions (see worldmap.to_screen), so this is a matter of
putting the pointer on a computed point, which `pointer.aim_to` already does by
nudging and reading back rather than by trusting a mouse command.

Either way **the destination is read out of the engine afterwards and checked
before anything is spoken.** That is the rule the rest of the mod follows, and
here it is unusually strong: the engine stores the destination as two integers,
so the check is an exact match rather than a tolerance. If the click missed, or
landed on a different square, or the engine declined it, the numbers say so and
the mod says so instead of announcing a journey that is not happening.
"""

from __future__ import annotations

import time
from typing import List, Optional, Tuple

from ..input.send import guarded_click, guarded_tap, require_focus
from ..memory.process import Process
from . import pointer, uiwindow, worldmap
from ..i18n import tr

# The world map window, and the button that identifies it. Size alone will not
# do -- the character sheet, the Pip-Boy and the save screen are all 640x480 --
# so it is named by a control only it has. Code 84 is the town-view button, and
# 350 is the first row of the list of places.
PANEL_W = worldmap.WINDOW_W
PANEL_H = worldmap.WINDOW_H
TOWN_VIEW_CODE = 84
ROW_CODE_BASE = 350

# How long to give the engine to record a destination after a click. It is set
# synchronously inside the input handler, so this only has to outlast one frame;
# a fifth of a second is many frames and still short enough that a failure is
# reported while the player still has the key press in mind.
CONFIRM_SECONDS = 0.25
CONFIRM_POLL = 0.02

# Scrolling the view to bring a square into it. The engine binds the arrow keys
# to this itself, so the mod presses the game's own keys rather than reaching
# for a button -- but how far one press scrolls is not written down anywhere, so
# it is measured: press, read the offset back, and stop when the target is in
# view or the offset stops moving. Sixteen presses covers the width of the world
# at any plausible step size, and stopping when nothing moved catches the edge.
MAX_SCROLLS = 16


def panel(proc: Process) -> Optional[uiwindow.Window]:
    """The world map window, with its buttons."""
    return uiwindow.live_window_with(proc, PANEL_W, PANEL_H,
                                     release=TOWN_VIEW_CODE)


def _rows(win: uiwindow.Window) -> List[uiwindow.Button]:
    """The seven list buttons, top row first."""
    found = []
    for i in range(worldmap.ROWS_VISIBLE):
        button = win.by_code(ROW_CODE_BASE + i)
        if button is not None:
            found.append(button)
    return sorted(found, key=lambda b: b.top)


def _destination_is(proc: Process, want: Tuple[int, int],
                    deadline: float) -> bool:
    while time.time() < deadline:
        if worldmap.destination(proc) == want:
            return True
        time.sleep(CONFIRM_POLL)
    return worldmap.destination(proc) == want


def travel_to_area(proc: Process, hwnd: int, area: worldmap.Area,
                   log_path: Optional[str] = None) -> Tuple[bool, str]:
    """Travel to a place by pressing its row in the engine's own list.

    Returns (started, what to say). The engine ignores a row whose area is the
    one already being stood on, so that case is caught here and named rather
    than left to look like a click that failed.
    """
    win = panel(proc)
    if win is None:
        return False, tr("worldmap.closed", "The world map is not open.")

    rows = worldmap.town_rows(proc)
    if area.index not in rows:
        return False, ""          # not in the list; the caller falls back

    if worldmap.current_area(proc) == area.index:
        return False, tr("travel.already_there", "You are already at {place}.",
                         place=area.name)

    wanted = rows.index(area.index)
    buttons = _rows(win)
    if not buttons:
        return False, ""

    # Scroll the list until the wanted entry is one of the seven on screen. The
    # engine scrolls in pixels and divides by the row height, so the top row is
    # read back rather than counted -- the same reason nothing else in this mod
    # keeps its own idea of a scroll position.
    for _ in range(len(rows) + worldmap.ROWS_VISIBLE):
        top = worldmap.town_scroll_row(proc)
        if top <= wanted < top + len(buttons):
            break
        arrow = win.by_code(401 if wanted > top else 397)
        if arrow is None:
            return False, ""
        if not _press(proc, hwnd, win, arrow, log_path):
            return False, tr("travel.list_unreachable", "Could not reach {place} in the list.",
                             place=area.name)
    else:
        return False, tr("travel.list_unreachable", "Could not reach {place} in the list.",
                         place=area.name)

    top = worldmap.town_scroll_row(proc)
    index = wanted - top
    if not 0 <= index < len(buttons):
        return False, ""
    if not _press(proc, hwnd, win, buttons[index], log_path):
        return False, tr("travel.list_unpressed", "Could not press {place} in the list.",
                         place=area.name)

    if _destination_is(proc, (area.x, area.y),
                       time.time() + CONFIRM_SECONDS):
        return True, tr("travel.going", "Travelling to {place}.", place=area.name)
    return False, tr("travel.refused", "The game did not take that. Still here.")


def travel_to_point(proc: Process, hwnd: int, wx: int, wy: int,
                    log_path: Optional[str] = None) -> Tuple[bool, str]:
    """Travel to a world position by clicking the map."""
    win = panel(proc)
    if win is None:
        return False, tr("worldmap.closed", "The world map is not open.")
    if worldmap.travelling(proc):
        return False, tr("travel.already", "Already travelling.")

    if not _bring_into_view(proc, hwnd, wx, wy):
        return False, tr("travel.no_scroll", "Could not scroll that square into view.")

    where = worldmap.to_screen(proc, wx, wy, win.left, win.top)
    if where is None:
        return False, tr("travel.off_screen", "That square is not on screen.")

    ok, landed, why = pointer.aim_ui(proc, hwnd, where[0], where[1],
                                     log_path=log_path)
    if not ok:
        return False, why or tr("travel.no_pointer", "Could not put the pointer there.")
    guarded_click(hwnd, "left")

    # What the engine recorded, checked against where the pointer really ended
    # up rather than against where it was asked to go. `aim_to` reports arrival
    # within a couple of pixels, and the engine stores exactly the world
    # position under the pointer -- so the two can be compared exactly, and a
    # click that landed on the neighbouring square says so instead of being
    # announced as the square that was asked for.
    offset = worldmap.scroll(proc)
    expected = None
    if landed is not None and offset is not None:
        expected = worldmap.to_world(offset[0], offset[1],
                                     landed[0] - win.left, landed[1] - win.top)
    deadline = time.time() + CONFIRM_SECONDS
    got = None
    while time.time() < deadline:
        got = worldmap.destination(proc)
        if got is not None:
            break
        time.sleep(CONFIRM_POLL)
    if got is None:
        return False, tr("travel.refused", "The game did not take that. Still here.")
    if expected is not None and got != expected:
        # The engine took a destination, but not the one this click made. Say
        # so rather than reporting the journey that was asked for.
        return False, tr("travel.elsewhere",
                         "The game read that click somewhere else. Not travelling.")
    # Which square the engine actually accepted, which is the honest answer even
    # when it is one over from the one aimed at.
    landed_square = (got[0] // worldmap.SUBTILE, got[1] // worldmap.SUBTILE)
    if landed_square != (wx // worldmap.SUBTILE, wy // worldmap.SUBTILE):
        return True, tr("travel.off_by_one", "Travelling, one square off the one you picked.")
    return True, ""


def _bring_into_view(proc: Process, hwnd: int, wx: int, wy: int) -> bool:
    """Scroll until a world position is inside the viewport.

    Presses the arrow keys, which are the engine's own scroll controls -- there
    is no need for a button and no need to know how far one press goes, because
    the scroll offset is read back after every press. A press that moves nothing
    means the edge, and stops the loop.
    """
    shape = worldmap.layout(proc)
    if shape is None:
        return False
    require_focus(hwnd)
    for _ in range(MAX_SCROLLS):
        offset = worldmap.scroll(proc)
        if offset is None:
            return False
        vx, vy = wx - offset[0], wy - offset[1]
        if 0 <= vx < worldmap.VIEW_W and 0 <= vy < worldmap.VIEW_H:
            return True
        if vx < 0:
            key = "left"
        elif vx >= worldmap.VIEW_W:
            key = "right"
        elif vy < 0:
            key = "up"
        else:
            key = "down"
        guarded_tap(hwnd, key, settle=0.06)
        if worldmap.scroll(proc) == offset:
            # The view did not move, so this is as far as it goes. Say whether
            # the target happens to be visible anyway rather than assuming it
            # is not: at the edges the viewport shows past the clamp.
            offset = worldmap.scroll(proc) or offset
            vx, vy = wx - offset[0], wy - offset[1]
            return 0 <= vx < worldmap.VIEW_W and 0 <= vy < worldmap.VIEW_H
    return False


def _press(proc: Process, hwnd: int, win: uiwindow.Window,
           button: uiwindow.Button, log_path: Optional[str]) -> bool:
    """Click a button of the world map panel, by its own rectangle."""
    x, y = button.centre(win)
    ok, _landed, _why = pointer.aim_ui(proc, hwnd, x, y, log_path=log_path)
    if not ok:
        return False
    guarded_click(hwnd, "left")
    time.sleep(0.05)
    return True


def standing_on(proc: Process) -> Optional[worldmap.Area]:
    """The place the player's marker is on, or None in open country."""
    index = worldmap.current_area(proc)
    if index is None:
        return None
    table = worldmap.areas(proc)
    return table[index] if 0 <= index < len(table) else None


def enter_here(proc: Process, hwnd: int,
               log_path: Optional[str] = None) -> Tuple[bool, str]:
    """Go into the place the player is standing on, whichever way the engine
    offers.

    There are two ways in and the engine chooses between them on the spot, in
    one dispatch at 0x004C0206. **This cost a real playthrough five minutes of
    silence, and the fault was the mod's.** A place you have travelled to but
    never entered is KNOWN, not VISITED, and the town view is only for VISITED
    places -- so `T` at Klamath is ignored by the engine, correctly, and the
    first version of this refused with "you have not been inside Klamath yet",
    which is true, useless, and reads as a dead end. It is not one: the way in
    is the other branch.

    **Visited, with a picture** -- the town view, opened with the engine's own
    `T` so nothing has to be aimed at.

    **Anything else** -- a click on the player's own marker, which the engine
    routes to the first entrance marked known and walks you straight in. That
    is how anywhere is entered the first time.
    """
    if worldmap.travelling(proc):
        return False, tr("travel.busy", "Not while you are travelling.")
    area = standing_on(proc)
    if area is None:
        return False, tr("travel.nowhere", "You are not at a place.")

    if area.shows_town_map:
        guarded_tap(hwnd, "t", settle=0.2)
        return True, ""

    if not area.enters_directly:
        return False, tr("travel.no_way_in", "There is no way into {place} from here.",
                         place=area.name)

    win = panel(proc)
    if win is None:
        return False, tr("worldmap.closed", "The world map is not open.")

    # The marker has to be on screen to be clicked, and Home is the engine's own
    # key for putting it there. Cheaper and more exact than scrolling by hand,
    # and it is what a sighted player would do.
    here = worldmap.player(proc)
    if here is None:
        return False, tr("travel.unknown_position", "Cannot read where you are.")
    if worldmap.to_screen(proc, here[0], here[1], win.left, win.top) is None:
        guarded_tap(hwnd, "home", settle=0.15)
    where = worldmap.to_screen(proc, here[0], here[1], win.left, win.top)
    if where is None:
        return False, tr("travel.no_marker", "Cannot find your marker on screen.")

    ok, _landed, why = pointer.aim_ui(proc, hwnd, where[0], where[1],
                                      log_path=log_path)
    if not ok:
        return False, why or tr("travel.marker_unreachable",
                                "Could not put the pointer on your marker.")
    guarded_click(hwnd, "left")
    way = area.first_way_in
    if way is not None and way.name:
        return True, tr("travel.entering_by", "Entering {place}, {way}.",
                        place=area.name, way=way.name)
    return True, tr("travel.entering", "Entering {place}.", place=area.name)


def town_key_explanation(proc: Process) -> Optional[str]:
    """Why `T` did nothing, or None when it is about to do something.

    `T` belongs to the engine and the mod does not press it -- binding it would
    press it twice. But a key that is silently ignored is indistinguishable from
    a mod that has stopped working, and silence is this project's worst failure
    mode. So the key is watched rather than taken: when the engine is going to
    act, this says nothing and the town view reads itself out; when it is not,
    this says which of the engine's conditions failed and what to press instead.
    """
    if worldmap.travelling(proc):
        return tr("travel.busy", "Not while you are travelling.")
    area = standing_on(proc)
    if area is None:
        return tr("travel.town_nowhere", "T shows a town map, and you are not at a place.")
    if area.shows_town_map:
        return None
    if area.enters_directly:
        way = area.first_way_in
        if way is not None and way.name:
            return tr("travel.town_unvisited_by",
                      "You have not been inside {place} yet, so there is no "
                      "town map. Enter goes in, {way}.",
                      place=area.name, way=way.name)
        return tr("travel.town_unvisited",
                  "You have not been inside {place} yet, so there is no town "
                  "map. Enter goes in.", place=area.name)
    return tr("travel.no_town_map", "{place} has no town map.", place=area.name)
