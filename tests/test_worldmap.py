"""The world map: reading it, walking it, and what gets said about it.

Two things are worth testing here above all others, and both are places where a
wrong answer would sound perfectly reasonable.

**The indexing.** Subtiles are stored row-major inside their tile. Read
column-major the grid still parses, every read succeeds, and the mod reports the
terrain and the fog of a square that is somewhere else entirely -- which is
exactly what the first version did, and it took the game's own coastline to
notice. So the fake stores them where the engine stores them and the tests ask
for squares in different tiles.

**The fog.** An unexplored square must not have its ground named, because the
engine draws those black and the player is not looking at anything. That is the
mod's first rule, and it is one of the few places where the rule can be checked
rather than merely stated.
"""

import unittest

from fallout2_access.game import screens, worldcursor, worldmap
from tests import fakes


ARROYO = {"name": "Arroyo", "x": 184, "y": 133, "state": worldmap.VISITED,
          "entrances": [
              {"name": "Bridge", "map": 5, "x": 350, "y": 275},
              {"name": "Village", "map": 4, "x": 280, "y": 175},
              # Known, but with no place on the picture -- the engine draws no
              # button for this one, so the mod must not offer it.
              {"name": "Temple: Foyer", "map": 3, "x": -1, "y": -1},
          ]}
KLAMATH = {"name": "Klamath", "x": 373, "y": 122, "state": worldmap.KNOWN,
           "entrances": [{"name": "Downtown", "map": 9, "x": 309, "y": 203},
                         {"name": "Mall", "map": 10, "x": 155, "y": 264,
                          "known": 0}]}
DEN = {"name": "The Den", "x": 473, "y": 272, "state": worldmap.UNKNOWN,
       "entrances": []}


def _world(**kwargs):
    kwargs.setdefault("areas", (ARROYO, KLAMATH, DEN))
    kwargs.setdefault("rows", (0, 1))
    kwargs.setdefault("subtiles", {
        (3, 2): (1, worldmap.VISITED),      # Arroyo: mountains, walked
        (4, 2): (0, worldmap.KNOWN),        # desert, only seen
        (7, 2): (1, worldmap.KNOWN),        # Klamath
        (0, 0): (3, worldmap.VISITED),      # the coast, in another tile
        (8, 7): (2, worldmap.VISITED),      # a city, two tiles away
    })
    return fakes.memory_with_worldmap(**kwargs)


class TestLayout(unittest.TestCase):
    def test_the_grid_is_read_from_the_game_not_assumed(self):
        """28 by 30 is true of every stock install and is still not a constant.

        A mod that adds a row of tiles would leave every read succeeding and
        every square described wrongly, so the shape comes from the two numbers
        the engine keeps.
        """
        shape = worldmap.layout(_world())
        self.assertEqual((shape.width, shape.height), (28, 30))
        wider = worldmap.layout(_world(tiles_across=5, tile_count=30))
        self.assertEqual((wider.width, wider.height), (35, 36))

    def test_the_edge_of_the_world_is_outside_it(self):
        shape = worldmap.layout(_world())
        self.assertTrue(shape.contains(27, 29))
        self.assertFalse(shape.contains(28, 29))
        self.assertFalse(shape.contains(-1, 0))


class TestSubtiles(unittest.TestCase):
    def test_subtiles_are_row_major_within_their_tile(self):
        """The bug that reported the player's own square as unexplored.

        Column-major indexing produces a grid that looks plausible and is
        wrong. Squares in three different tiles, so a stride error cannot pass.
        """
        mem = _world()
        self.assertEqual(worldmap.subtile(mem, 3, 2).terrain, 1)
        self.assertEqual(worldmap.subtile(mem, 3, 2).state, worldmap.VISITED)
        self.assertEqual(worldmap.subtile(mem, 0, 0).terrain, 3)
        self.assertEqual(worldmap.subtile(mem, 8, 7).terrain, 2)
        self.assertEqual(worldmap.subtile(mem, 8, 7).state, worldmap.VISITED)

    def test_a_square_off_the_map_reads_as_nothing(self):
        mem = _world()
        self.assertIsNone(worldmap.subtile(mem, 28, 0))
        self.assertIsNone(worldmap.subtile(mem, 0, -1))

    def test_terrain_names_come_from_the_games_own_messages(self):
        self.assertEqual(worldmap.terrain_names(_world())[3], "Coast")


class TestAreas(unittest.TestCase):
    def test_areas_are_named_from_map_msg_not_from_the_table(self):
        """city.txt's names are identifiers, not words for a player.

        The record's own `char name[40]` says "Sierra Army Base" where the game
        says "Sierra Army Depot", and "abbey" and "Car Outta Gas" are not names
        anybody should hear.
        """
        mem = fakes.memory_with_worldmap(
            areas=({"name": "Sierra Army Depot", "internal": "Sierra Army Base",
                    "x": 923, "y": 822, "state": worldmap.KNOWN},))
        self.assertEqual(worldmap.areas(mem)[0].name, "Sierra Army Depot")

    def test_only_places_the_game_has_shown_are_on_the_map(self):
        table = worldmap.areas(_world())
        self.assertEqual([a.name for a in table if a.on_map],
                         ["Arroyo", "Klamath"])

    def test_an_entrance_with_no_place_on_the_picture_is_not_offered(self):
        """The engine skips those, so the mod must not count them.

        Arroyo records three known entrances and draws two: "Temple: Foyer"
        carries -1, -1 and never gets a button.
        """
        arroyo = worldmap.areas(_world())[0]
        self.assertEqual([e.name for e in arroyo.ways_in],
                         ["Bridge", "Village"])

    def test_an_undiscovered_entrance_is_not_offered(self):
        klamath = worldmap.areas(_world())[1]
        self.assertEqual([e.name for e in klamath.ways_in], ["Downtown"])

    def test_entrances_carry_the_number_key_that_enters_them(self):
        """Their event codes are below 256, so GNW treats them as key presses.

        That is what makes the town view reachable without a pointer, and the
        key is the entrance's position in the array whether or not the ones
        before it were drawn.
        """
        arroyo = worldmap.areas(_world())[0]
        self.assertEqual([e.key for e in arroyo.entrances], ["1", "2", "3"])

    def test_the_town_list_is_read_rather_than_rebuilt(self):
        """Whatever the engine put in that array is what is on screen."""
        self.assertEqual(worldmap.town_rows(_world()), [0, 1])


class TestScreenAndWorld(unittest.TestCase):
    def test_the_conversion_inverts_the_engines_own(self):
        """worldmap.to_world is the engine's arithmetic; to_screen undoes it."""
        mem = _world(scroll=(300, 400))
        point = worldmap.to_screen(mem, 500, 600, 192, 144)
        self.assertIsNotNone(point)
        back = worldmap.to_world(300, 400, point[0] - 192, point[1] - 144)
        self.assertEqual(back, (500, 600))

    def test_off_the_viewport_is_an_answer_not_a_failure(self):
        """Most of a 1400x1500 world is off a 450x443 view at any moment."""
        self.assertIsNone(worldmap.to_screen(_world(), 1300, 1400, 192, 144))

    def test_centring_matches_what_the_engine_does(self):
        shape = worldmap.layout(_world())
        self.assertEqual(worldmap.centre_scroll(700, 800, shape), (497, 600))
        # And it clamps rather than scrolling past the edge, both ways.
        self.assertEqual(worldmap.centre_scroll(0, 0, shape), (0, 0))
        self.assertEqual(worldmap.centre_scroll(9999, 9999, shape), (950, 1057))


class TestCursor(unittest.TestCase):
    def setUp(self):
        self.mem = _world()
        self.cursor = worldcursor.WorldCursor()
        self.cursor.snap(self.mem)

    def test_it_starts_on_the_player(self):
        self.assertEqual((self.cursor.x, self.cursor.y), (3, 2))

    def test_all_eight_directions_are_real_ones(self):
        """The whole reason this is not the hex cursor.

        On a hex grid numpad 8 and 2 are a staircase of two other directions
        that drifts sideways; here one press is one square, north is north, and
        eight presses round the compass come back to where they started.
        """
        for name, (dx, dy) in worldcursor.STEPS.items():
            with self.subTest(name=name):
                self.cursor.goto(10, 10)
                self.cursor.step_by(self.mem, dx, dy)
                self.assertEqual((self.cursor.x, self.cursor.y),
                                 (10 + dx, 10 + dy))

    def test_the_edge_stops_it_and_says_so(self):
        """Silence here reads as the mod having stopped working."""
        self.cursor.goto(0, 5)
        moved, why = self.cursor.step_by(self.mem, -1, 0)
        self.assertFalse(moved)
        self.assertIn("Edge", why)
        self.assertEqual((self.cursor.x, self.cursor.y), (0, 5))

    def test_an_unexplored_square_does_not_have_its_ground_named(self):
        """The engine draws those black. Naming the terrain would hand over a
        map the game has not given."""
        self.cursor.goto(20, 20)
        said = self.cursor.say_step(self.mem)
        self.assertIn("Unexplored", said)
        for word in ("Desert", "Mountains", "City", "Coast"):
            self.assertNotIn(word, said)

    def test_a_seen_square_names_its_ground(self):
        self.cursor.goto(4, 2)
        self.assertIn("Desert", self.cursor.say_step(self.mem))

    def test_a_place_is_named_before_the_ground(self):
        self.cursor.goto(7, 2)
        said = self.cursor.say_step(self.mem)
        self.assertTrue(said.startswith("Klamath"), said)

    def test_it_says_where_it_is_relative_to_the_player(self):
        self.cursor.goto(7, 2)
        self.assertIn("East 4 squares", self.cursor.say_step(self.mem))
        self.cursor.goto(3, 2)
        self.assertIn("You are here", self.cursor.say_step(self.mem))

    def test_the_encounter_odds_are_never_spoken(self):
        """They are in every subtile record and the game never draws them."""
        for x, y in ((3, 2), (4, 2), (7, 2), (20, 20)):
            self.cursor.goto(x, y)
            for said in (self.cursor.say_step(self.mem),
                         self.cursor.say_full(self.mem)):
                self.assertNotIn("%", said)
                self.assertNotIn("chance", said.lower())

    def test_the_long_readout_distinguishes_seen_from_walked(self):
        """The engine draws those differently, so a sighted player has it.

        It is kept out of the short readout because that one is heard twenty
        times in a row.
        """
        self.cursor.goto(7, 2)
        self.assertIn("Seen but not travelled", self.cursor.say_full(self.mem))
        self.assertNotIn("Seen but not travelled",
                         self.cursor.say_step(self.mem))

    def test_the_games_own_words_are_not_restyled(self):
        """`str.capitalize` would turn "Temple: Foyer" into "Temple: foyer"."""
        self.cursor.goto(3, 2)
        said = self.cursor.say_full(self.mem)
        self.assertIn("Arroyo", said)
        self.assertNotIn("arroyo", said)


class TestBearings(unittest.TestCase):
    def test_the_axes_are_exact(self):
        self.assertEqual(worldcursor.bearing(0, -3), "north")
        self.assertEqual(worldcursor.bearing(0, 3), "south")
        self.assertEqual(worldcursor.bearing(4, 0), "east")
        self.assertEqual(worldcursor.bearing(-4, 0), "west")

    def test_a_diagonal_is_only_named_when_it_really_is_one(self):
        """Two squares east and nine south is south, not south east."""
        self.assertEqual(worldcursor.bearing(3, 3), "south east")
        self.assertEqual(worldcursor.bearing(2, 9), "south")
        self.assertEqual(worldcursor.bearing(-9, 2), "west")

    def test_distance_counts_presses_rather_than_measuring(self):
        """The cursor moves diagonally, so the larger component is the count."""
        self.assertEqual(worldcursor.steps_away(3, 3), 3)
        self.assertEqual(worldcursor.steps_away(-4, 1), 4)
        self.assertEqual(worldcursor.steps_away(0, 0), 0)


class TestScanner(unittest.TestCase):
    def setUp(self):
        self.mem = _world()
        self.cursor = worldcursor.WorldCursor()
        self.cursor.snap(self.mem)

    def test_it_only_offers_places_the_game_has_shown(self):
        """The area table is mostly encounter sites the player has not found."""
        self.assertEqual([a.name for a in self.cursor.places(self.mem)],
                         ["Arroyo", "Klamath"])

    def test_the_first_press_reads_the_nearest_rather_than_stepping_past_it(self):
        self.assertIn("Arroyo", self.cursor.scan(self.mem, 1))
        self.assertIn("Klamath", self.cursor.scan(self.mem, 1))

    def test_it_wraps_rather_than_ending(self):
        """A list you can fall off the end of makes you count your presses."""
        places = len(self.cursor.places(self.mem))
        first = self.cursor.scan(self.mem, 1)
        for _ in range(places - 1):
            self.cursor.scan(self.mem, 1)
        self.assertEqual(self.cursor.scan(self.mem, 1), first)

    def test_it_wraps_backwards_too(self):
        """`[` off the front comes round to the last, not to nothing."""
        self.cursor.scan(self.mem, 1)          # sits on the nearest
        self.assertIn("Klamath", self.cursor.scan(self.mem, -1))

    def test_slash_moves_the_cursor_and_says_nothing_itself(self):
        """The square readout that follows says where it landed; saying it
        twice helps nobody."""
        self.cursor.scan(self.mem, 1)
        self.cursor.scan(self.mem, 1)
        self.assertIsNone(self.cursor.scan_jump(self.mem))
        self.assertEqual((self.cursor.x, self.cursor.y), (7, 2))

    def test_an_empty_map_says_so_rather_than_failing(self):
        mem = fakes.memory_with_worldmap(areas=(DEN,))
        cursor = worldcursor.WorldCursor()
        cursor.snap(mem)
        self.assertIn("No places", cursor.scan(mem, 1))
        self.assertIn("No places", cursor.scan_jump(mem))


class TestGettingIn(unittest.TestCase):
    """The two ways into a place, and the one that looked like a dead end.

    A place you have travelled to but never entered is KNOWN, not VISITED. The
    engine's T only opens a town map for VISITED places, so at Klamath it is
    silently ignored -- and the first version of this mod answered "you have not
    been inside Klamath yet", which is true and reads as there being no way in.
    There is: clicking your own marker walks you through the first known
    entrance, and that is how anywhere is entered the first time.
    """

    def setUp(self):
        from fallout2_access.game import worldtravel
        self.travel = worldtravel

    def _at(self, index):
        return _world(current_area=index)

    def test_a_visited_place_shows_its_town_map(self):
        arroyo = worldmap.areas(self._at(0))[0]
        self.assertTrue(arroyo.shows_town_map)
        self.assertFalse(arroyo.enters_directly)

    def test_a_place_you_have_only_heard_of_is_entered_directly(self):
        klamath = worldmap.areas(self._at(1))[1]
        self.assertFalse(klamath.shows_town_map)
        self.assertTrue(klamath.enters_directly)
        self.assertEqual(klamath.first_way_in.name, "Downtown")

    def test_a_place_with_no_picture_never_shows_a_town_map(self):
        """The engine tests the art id too, and -1 means there is none."""
        mem = fakes.memory_with_worldmap(
            areas=({"name": "Nowhere", "x": 100, "y": 100,
                    "state": worldmap.VISITED, "label_fid": -1,
                    "entrances": [{"name": "In", "map": 4}]},))
        self.assertFalse(worldmap.areas(mem)[0].shows_town_map)

    def test_t_is_explained_where_the_engine_ignores_it(self):
        """Silence is indistinguishable from a broken mod."""
        said = self.travel.town_key_explanation(self._at(1))
        self.assertIsNotNone(said)
        self.assertIn("Klamath", said)
        self.assertIn("Enter goes in", said)
        self.assertIn("Downtown", said)

    def test_t_is_not_explained_where_it_is_about_to_work(self):
        """Otherwise the mod talks over the thing it just opened."""
        self.assertIsNone(self.travel.town_key_explanation(self._at(0)))

    def test_t_in_open_country_says_what_it_is_for(self):
        said = self.travel.town_key_explanation(_world(current_area=-1))
        self.assertIn("not at a place", said)

    def test_t_while_travelling_says_so(self):
        said = self.travel.town_key_explanation(
            _world(current_area=1, travelling=1))
        self.assertIn("travelling", said)

    def test_standing_on_reads_the_place_under_the_marker(self):
        self.assertEqual(self.travel.standing_on(self._at(1)).name, "Klamath")
        self.assertIsNone(self.travel.standing_on(_world(current_area=-1)))


class _Ann:
    """Just enough Announcer to record what would have been said."""

    def __init__(self):
        self.said = []

    def answer(self, text):
        self.said.append(text)

    def say(self, text, interrupt=False, force=False):
        self.said.append(text)

    def heard(self):
        return " | ".join(self.said)


def _watcher(mem):
    from fallout2_access.app import WorldMapWatcher
    return WorldMapWatcher(mem, hwnd=None, log_path=None)


class TestTravelAnnouncements(unittest.TestCase):
    """Setting off, keeping going, and stopping -- read from the engine.

    The end of a journey is the part that matters. It has two causes that look
    identical in the flags -- you arrived, or something walked out of the desert
    at you -- and a player who cannot see the map has no other way to tell them
    apart. So the distinction is made from the distance to the destination, and
    it is worth a test because getting it wrong means announcing an arrival that
    did not happen.
    """

    def test_setting_off_is_noticed(self):
        mem = _world()
        watcher = _watcher(mem)
        ann = _Ann()
        watcher.enter(ann)
        ann.said.clear()
        mem.set_i32(worldmap.TRAVELLING, 1)
        mem.set_i32(worldmap.DEST_X, 373)
        mem.set_i32(worldmap.DEST_Y, 122)
        watcher.poll(ann)
        self.assertTrue(watcher._travelling)

    def test_arriving_names_the_place(self):
        mem = _world()
        watcher = _watcher(mem)
        ann = _Ann()
        watcher.enter(ann)
        mem.set_i32(worldmap.TRAVELLING, 1)
        mem.set_i32(worldmap.DEST_X, 373)
        mem.set_i32(worldmap.DEST_Y, 122)
        watcher.poll(ann)
        # Arrive: the marker reaches the destination and the flag drops.
        mem.set_i32(worldmap.WORLD_X, 373)
        mem.set_i32(worldmap.WORLD_Y, 122)
        mem.set_i32(worldmap.TRAVELLING, 0)
        ann.said.clear()
        watcher.poll(ann)
        self.assertIn("Arrived at Klamath", ann.heard())

    def test_being_stopped_short_is_not_reported_as_arriving(self):
        """An encounter interrupts the journey a long way from anywhere."""
        mem = _world()
        watcher = _watcher(mem)
        ann = _Ann()
        watcher.enter(ann)
        mem.set_i32(worldmap.TRAVELLING, 1)
        mem.set_i32(worldmap.DEST_X, 373)
        mem.set_i32(worldmap.DEST_Y, 122)
        watcher.poll(ann)
        mem.set_i32(worldmap.WORLD_X, 260)   # less than half way
        mem.set_i32(worldmap.TRAVELLING, 0)
        ann.said.clear()
        watcher.poll(ann)
        self.assertIn("Stopped short", ann.heard())
        self.assertNotIn("Arrived", ann.heard())

    def test_a_nudge_of_the_view_is_not_a_scroll(self):
        """A press of an arrow key moves the view tens of pixels. Anything
        smaller is the engine keeping the marker in frame, which nobody did."""
        mem = _world()
        watcher = _watcher(mem)
        ann = _Ann()
        watcher.enter(ann)
        ann.said.clear()
        mem.set_i32(worldmap.SCROLL_X, 3)
        watcher.poll(ann)
        self.assertEqual(ann.said, [])

    def test_the_view_being_dragged_along_by_a_journey_is_not_announced(self):
        """Travelling scrolls the map a long way, and it is not a thing the
        player did. The journey is already being reported on its own."""
        mem = _world(travelling=1, destination=(373, 122))
        watcher = _watcher(mem)
        ann = _Ann()
        watcher.enter(ann)
        ann.said.clear()
        mem.set_i32(worldmap.SCROLL_X, 200)
        watcher.poll(ann)
        self.assertNotIn("View", ann.heard())

    def test_scrolling_the_view_says_where_it_went(self):
        mem = _world()
        watcher = _watcher(mem)
        ann = _Ann()
        watcher.enter(ann)
        ann.said.clear()
        mem.set_i32(worldmap.SCROLL_X, 200)
        watcher.poll(ann)
        self.assertIn("View", ann.heard())
        self.assertIn("east", ann.heard())

    def test_the_summary_gives_the_date_the_panel_shows(self):
        mem = _world(current_area=0)
        mem.set_i32(0x0051C720, 10 * 24 * 60 * 60 * 10)   # GAME_TIME, ten days
        watcher = _watcher(mem)
        ann = _Ann()
        watcher.summary(ann)
        self.assertIn("Arroyo", ann.heard())
        self.assertIn("Day", ann.heard())


class TestScreenDetection(unittest.TestCase):
    def test_the_world_map_is_its_own_screen(self):
        mem = fakes.FakeMemory()
        self.assertEqual(
            screens.detect(mem, in_game=True, mode=screens.MODE_WORLDMAP),
            screens.WORLDMAP)

    def test_a_loaded_map_is_still_the_map(self):
        mem = fakes.FakeMemory()
        self.assertEqual(screens.detect(mem, in_game=True, mode=0),
                         screens.WORLD)
        self.assertEqual(
            screens.detect(mem, in_game=True, mode=screens.MODE_LOCALMAP),
            screens.WORLD)

    def test_a_panel_over_the_world_map_does_not_lose_it(self):
        """The escape menu opens over the world map and the world map is still
        what is underneath, exactly as it is on a loaded map."""
        mem = fakes.FakeMemory()
        self.assertEqual(
            screens.detect(mem, in_game=True,
                           mode=screens.MODE_WORLDMAP | screens.MODE_ESCMENU),
            screens.WORLDMAP)

    def test_the_pipboy_still_wins_over_it(self):
        mem = fakes.FakeMemory()
        self.assertEqual(
            screens.detect(mem, in_game=True,
                           mode=screens.MODE_WORLDMAP | screens.MODE_PIPBOY),
            screens.PIPBOY)

    def test_aiming_is_still_declined_on_the_world_map(self):
        """There are no hexes here, so a click must never be aimed at one."""
        self.assertFalse(screens.is_map_mode(screens.MODE_WORLDMAP))


if __name__ == "__main__":
    unittest.main()
