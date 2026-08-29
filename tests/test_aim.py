"""Choosing which object on a hex the player meant.

Both bugs covered here were caught in a live debug.log rather than reasoned
about, and both come from the same place: the hex readout is prose written for
a listener, and it was being parsed back as if it were a data format.

The fixtures are the exact lines that session logged.
"""

import unittest

from fallout2_access.game import aim
from fallout2_access.game.worldlog import HexReading


def hex_reading(contents, tile=24308, distance=1):
    return HexReading(tile=tile, distance=distance, contents=contents)


class TestHexNames(unittest.TestCase):
    """What `HexReading.names()` has to get right."""

    def test_a_door_hex_names_the_door(self):
        """The bug, in one line.

        Every sliding door in the game sits on a Door Track, so the hex holds
        two objects. Taking the first field meant insisting on the track while
        the engine kept answering "Door" -- thirty-two probes, every one
        discarded, and "cannot point at that" spoken about a door the pointer
        was sitting on.
        """
        self.assertEqual(hex_reading("Door Track, Door").names(),
                         ["Door Track", "Door"])

    def test_a_locked_door_is_still_one_object(self):
        """obj_label appends state with the SAME comma that separates objects,
        so nothing about the string distinguishes "Door, locked" from
        "Door Track, Door". The state words are the mod's own, so they can be
        named and dropped without touching a translation."""
        self.assertEqual(hex_reading("Door, locked").names(), ["Door"])
        self.assertEqual(hex_reading("Foot Locker, open").names(),
                         ["Foot Locker"])

    def test_a_body_is_one_object_and_keeps_its_name(self):
        """", dead" is a state word like ", locked", and arrives by the same
        comma. Left in NOT_A_NAME's gap it would come back as an object called
        "dead" -- and worse, the corpse's real name would still be there beside
        it, so the hex would read as two things and a click could be aimed at
        the word."""
        self.assertEqual(hex_reading("Warrior, dead").names(), ["Warrior"])
        self.assertEqual(hex_reading("you, Cameron, dead").names(), ["Cameron"])

    def test_a_facing_is_not_an_object(self):
        """"Klint, facing north east" is ONE critter. The suffix arrives by the
        same comma that separates objects, and unmatched it becomes an object
        called "facing north east" -- which a click could then be aimed at, and
        which would sit in the list looking exactly like a second thing on the
        hex. Matched by prefix because the bearing varies."""
        self.assertEqual(hex_reading("Klint, facing north east").names(),
                         ["Klint"])
        self.assertEqual(hex_reading("Klint, facing west").names(), ["Klint"])

    def test_a_corpse_keeps_its_state_word_and_loses_no_name(self):
        """Dead critters get ", dead" and no facing -- they are not looking at
        anything. Both suffixes together must still leave one object."""
        self.assertEqual(hex_reading("you, Warrior, dead").names(), ["Warrior"])

    def test_the_words_that_mean_no_object(self):
        for contents in ("empty", "blocked", "you"):
            self.assertEqual(hex_reading(contents).names(), [],
                             "{!r} is a description, not an object".format(contents))

    def test_you_are_dropped_but_what_you_stand_on_is_not(self):
        self.assertEqual(hex_reading("you, Klint").names(), ["Klint"])

    def test_repeats_are_collapsed(self):
        self.assertEqual(hex_reading("Rocks, Rocks").names(), ["Rocks"])


class TestNameMatching(unittest.TestCase):
    """Is the engine's answer one of the things the player was told is here?"""

    def test_the_door_is_accepted_from_a_two_object_hex(self):
        """The regression. The engine says "Door"; the readout said
        "Door Track, Door"; that has to be a match."""
        acceptable = aim._wanted_names(hex_reading("Door Track, Door").names())
        self.assertTrue(aim._names_match("Door", acceptable))
        self.assertTrue(aim._names_match("Door Track", acceptable))

    def test_state_on_one_side_only_still_matches(self):
        """The script reads out "Door, locked" while obj_under_cursor answers
        with the bare "Door". Demanding equality would put the same bug back in
        a subtler form -- failing only on locked doors."""
        acceptable = aim._wanted_names(hex_reading("Door, locked").names())
        self.assertTrue(aim._names_match("Door", acceptable))

    def test_a_corpse_matches_the_living_name_the_menu_reports(self):
        """The same two-doors problem as the locked door, and the one that
        stops a body being looted: the hex readout says "Warrior, dead" because
        obj_label appends the state, while the action menu reports the bare
        obj_name the engine holds, which does not change when a critter dies.
        Refuse that and "use" on the corpse is discarded as the wrong thing."""
        acceptable = aim._wanted_names(hex_reading("Warrior, dead").names())
        self.assertTrue(aim._names_match("Warrior", acceptable))
        self.assertTrue(aim._names_match("Warrior, dead",
                                         aim._wanted_names("Warrior")))

    def test_a_dead_warrior_is_not_a_live_radscorpion(self):
        """Tolerance is not surrender -- the same guard the locked door has."""
        self.assertFalse(aim._names_match("Radscorpion",
                                          aim._wanted_names("Warrior, dead")))

    def test_a_facing_critter_matches_the_bare_name(self):
        """The menu reports obj_name, which knows nothing about facings, while
        the readout reports obj_label, which appends one. Same two-doors
        problem as the locked door -- refuse it and every living critter on the
        map becomes unclickable, which is a far bigger hole than the corpse."""
        acceptable = aim._wanted_names(
            hex_reading("Klint, facing north east").names())
        self.assertTrue(aim._names_match("Klint", acceptable))
        self.assertTrue(aim._names_match("Klint, facing west",
                                         aim._wanted_names("Klint")))

    def test_a_door_is_not_the_track_it_slides_on(self):
        """"Door" is a substring of "Door Track", and the test used to be a
        substring test either way round -- so a caller that knew exactly what
        it wanted still accepted the rail underneath it. The action menu names
        one object and means that object."""
        self.assertFalse(aim._names_match("Door Track",
                                          aim._wanted_names("Door")))
        self.assertTrue(aim._names_match("Door, locked",
                                         aim._wanted_names("Door")))

    def test_something_drawn_over_the_hex_is_rejected(self):
        """The case the filter exists for: an item on the floor beside a door
        answered "Impenetrable Door" to every probe, and without this the click
        was set up for the door and walked onto the item instead."""
        acceptable = aim._wanted_names(hex_reading("Plastic Explosives").names())
        self.assertFalse(aim._names_match("Impenetrable Door", acceptable))

    def test_no_expectation_accepts_anything(self):
        """An empty list means the caller did not say what it wanted, which is
        not the same as wanting nothing."""
        self.assertEqual(aim._wanted_names(None), [])
        self.assertEqual(aim._wanted_names([]), [])

    def test_one_name_or_many(self):
        """The action menu is handed a single name by the script; the click
        passes everything the readout said."""
        self.assertEqual(aim._wanted_names("Klint"), ["klint"])
        self.assertEqual(aim._wanted_names(["Door Track", "Door"]),
                         ["door track", "door"])

    def test_an_unreadable_answer_matches_nothing(self):
        self.assertFalse(aim._names_match("", aim._wanted_names(["Door"])))
        self.assertFalse(aim._names_match("   ", aim._wanted_names(["Door"])))


class TestClearSteps(unittest.TestCase):
    """Stepping aside from something that really would swallow the click.

    Rewritten after the premise turned out to be false. These offsets used to
    reach 22 pixels either side, on the theory that a wider search finds more
    clear ground -- but a Fallout hex is smaller than that. Rastered live from a
    confirmed anchor on hex 20314, offsets at +16 and -10 across were already on
    neighbouring tiles, and probes on the wrong tile are discarded, so the wider
    box bought nothing but several seconds of silence per click.
    """

    def test_the_search_starts_where_the_aim_left_the_pointer(self):
        """The aim already confirmed that spot is on the right hex, so it is
        the one candidate guaranteed not to have drifted off it."""
        self.assertEqual(aim.CLEAR_STEPS[0], (0, 0))

    def test_every_probe_stays_within_a_hex(self):
        """Measured: a three pixel move was enough to change which hex the
        pointer was over. Anything reaching out to twenty-odd pixels is
        sampling the neighbours and throwing the answers away."""
        for dx, dy in aim.CLEAR_STEPS:
            self.assertLessEqual(abs(dx), 12, "{},{} leaves the hex".format(dx, dy))
            self.assertLessEqual(abs(dy), 12, "{},{} leaves the hex".format(dx, dy))

    def test_no_probe_is_repeated(self):
        """Every probe costs a round trip to the game, and a duplicate buys
        nothing but silence after a keypress."""
        self.assertEqual(len(aim.CLEAR_STEPS), len(set(aim.CLEAR_STEPS)))

    def test_the_search_is_short(self):
        """It only runs in the narrow case where a click really would act on
        something else, and it sits between a keypress and a walk."""
        self.assertLessEqual(len(aim.CLEAR_STEPS), 12)


class ScriptedProbes(unittest.TestCase):
    """A base for the tests that drive `prepare` with canned probe answers.

    The answers are the tuples `_probe` builds out of a `WORLD:prepare` line,
    so a fixture here is a log line with the parsing already done.
    """

    class _Aimer(aim.Aimer):
        """An Aimer whose probes are scripted instead of sent to a game."""

        def __init__(self, answers):
            self.answers = list(answers)
            self.hwnd = 0
            self.blocked_by = None
            self.moves = 0

        def _probe(self, per_step=0.25):
            return self.answers.pop(0) if self.answers else None

    def _prepare(self, answers, want_object=False, wanted=None):
        import fallout2_access.game.aim as mod

        moved = []
        real = mod.move_mouse_relative
        mod.move_mouse_relative = lambda dx, dy, **kw: moved.append((dx, dy))
        try:
            a = self._Aimer(answers)
            return a.prepare(want_object=want_object, wanted=wanted), a, moved
        finally:
            mod.move_mouse_relative = real


class TestWalkingPastScenery(ScriptedProbes):
    """The correction that mattered: a sprite over a hex does not block a walk.

    `obj_under_cursor` names something almost everywhere on a Fallout map, and
    this file treated every such name as "the click would hit that instead".
    It was never checked against an actual click. With the movement cursor the
    engine walks to the tile under the pointer and ignores what is drawn over
    it -- confirmed on hex 20314, where every probe that stayed on the hex
    answered "Wall" or "Cave Wall", and clicking anyway produced
    WORLD:arrive 20314 dist 2 at a cost of the 2 action points the walk was
    worth.
    """

    def test_a_wall_over_a_walkable_hex_does_not_stop_the_walk(self):
        """mode 0 is the movement cursor: the click walks, wall or no wall."""
        (name, _off), a, moved = self._prepare(
            [(0, "Cave Wall", 20314, 20314, False)])
        self.assertIsNone(name, "None means 'go ahead and click'")
        self.assertIsNone(a.blocked_by)
        self.assertEqual(moved, [], "it should not have needed to step aside")

    def test_bare_ground_still_works(self):
        (name, _off), a, _moved = self._prepare([(0, "", 20314, 20314, False)])
        self.assertIsNone(name)

    def test_an_item_drawn_over_the_hex_is_still_stepped_around(self):
        """A non-movement cursor is the real case: an item across a walkable
        tile arms the command cursor, and a click picks it up instead of
        walking. Step aside, and take the first spot that is clear."""
        (name, _off), a, moved = self._prepare([
            (1, "Rat Meat", 20314, 20314, False),   # command -- would grab it
            (0, "Cave Wall", 20314, 20314, False),  # movement again -- fine
        ])
        self.assertIsNone(name)
        self.assertTrue(moved, "it should have stepped aside once")

    def test_nowhere_to_stand_is_still_refused_and_named(self):
        answers = [(1, "Rat Meat", 20314, 20314, False)] * len(aim.CLEAR_STEPS)
        (name, _off), a, _moved = self._prepare(answers)
        self.assertIs(name, False, "False means 'do not click'")
        self.assertEqual(a.blocked_by, "Rat Meat")


class TestAnArmedSkillIsNotAWalk(ScriptedProbes):
    """Arming a skill and clicking a hex was refused, whatever the hex held.

    Reported as first aid on yourself answering "that hex is behind a wall",
    and it was neither about walls nor about yourself. An armed skill sets the
    cursor to one of modes 4 to 10, the acceptance test here was `mode == 0`,
    and so every probe fell through to blocked_by until the search ran out.

    The stepping-aside this refusal belongs to protects a WALK from landing on
    a sprite. Somebody who armed Lockpick was not walking.
    """

    def test_a_skill_cursor_is_accepted_where_it_stands(self):
        (name, _off), a, moved = self._prepare(
            [(4, "Cave Wall", 20314, 20314, False)])   # 4 is First Aid
        self.assertIsNone(name, "None means 'go ahead and click'")
        self.assertIsNone(a.blocked_by)
        self.assertEqual(moved, [], "an armed skill needs no room made for it")

    def test_every_skill_cursor_is_accepted(self):
        """All seven, because the enum has a gap where Sneak would be and a
        range written out by hand is exactly the kind of thing that loses an
        end."""
        for mode in aim.SKILL_CURSORS:
            with self.subTest(mode=mode):
                (name, _off), a, _moved = self._prepare(
                    [(mode, "Wall", 20314, 20314, False)])
                self.assertIsNone(name)

    def test_your_own_hex_is_clickable_with_a_skill_armed(self):
        """Healing yourself, which is the case this was found on. Your own hex
        names no object -- the engine's question about what is under the
        pointer excludes your own character -- so the search runs on bare
        ground with a skill cursor set."""
        (name, _off), a, _moved = self._prepare(
            [(5, "", 17488, 17488, False)])            # 5 is Doctor
        self.assertIsNone(name)
        self.assertIsNone(a.blocked_by)

    def test_the_command_cursor_still_steps_aside(self):
        """The guard that was doing real work is untouched: mode 1 is not a
        skill anybody armed, it is the engine deciding a click would pick up
        what is drawn over the hex."""
        answers = [(1, "Rat Meat", 20314, 20314, False)] * len(aim.CLEAR_STEPS)
        (name, _off), a, _moved = self._prepare(answers)
        self.assertIs(name, False)
        self.assertEqual(a.blocked_by, "Rat Meat")


class TestTheDoorAndTheTrackUnderIt(ScriptedProbes):
    """The skill that was spent on a length of rail.

    Every sliding door in Fallout 2 sits on a Door Track, so its hex holds two
    objects and both are scenery with names the game chose. From tile 11307 the
    engine answered "Door Track" for the middle of hex 11108; the search took
    the first acceptable answer and stopped there, so `WORLD:prepare 6|Door
    Track|` went into the log seven times, each one a lockpick used on the
    track. From tile 11308 the same hex answered "Door, locked" -- and the same
    keypress read "You deftly pick the lock on the door."

    Both readings are in one session's debug.log, which is what makes this a
    pointing bug rather than anything to do with skills.
    """

    DOOR_HEX = 11108
    TRACK = (6, "Door Track", DOOR_HEX, DOOR_HEX, True)
    DOOR = (6, "Door, locked", DOOR_HEX, DOOR_HEX, False)
    NAMES = ["Door Track", "Door"]

    def test_the_track_does_not_end_the_search(self):
        """The bug itself. The track is a fair answer -- it really is on the
        hex -- and it is still not the one the player meant."""
        (name, _off), _a, _moved = self._prepare(
            [self.TRACK, self.DOOR], want_object=True, wanted=self.NAMES)
        self.assertEqual(name, "Door, locked")

    def test_the_pointer_ends_up_on_the_door(self):
        """The offset returned is where the click happens, so it has to be the
        spot the door answered at, not the spot the track did."""
        (_name, off), _a, _moved = self._prepare(
            [self.TRACK, self.DOOR], want_object=True, wanted=self.NAMES)
        self.assertEqual(off, aim.TARGET_OFFSETS[1])

    def test_a_hex_holding_only_flat_scenery_costs_nothing(self):
        """Told about one object, there is nothing to choose between, so the
        engine's answer is taken where it stands. Walking all thirty-two
        offsets to arrive back at the only candidate would be several seconds
        of silence after a keypress, which this project reads as a dead key."""
        answers = [self.TRACK] * len(aim.TARGET_OFFSETS)
        (name, off), a, _moved = self._prepare(
            answers, want_object=True, wanted=["Door Track"])
        self.assertEqual(name, "Door Track")
        self.assertEqual(off, aim.TARGET_OFFSETS[0])
        self.assertEqual(len(a.answers), len(aim.TARGET_OFFSETS) - 1,
                         "it should have probed exactly once")

    def test_the_track_is_still_reachable_when_the_door_never_answers(self):
        """The fallback, and the reason flat answers are kept rather than
        thrown away. Deprioritising is not the same as refusing: if nothing on
        an ambiguous hex ever stands up, the flat thing is what was meant, and
        the pointer goes back to where the engine said so."""
        answers = [self.TRACK] * len(aim.TARGET_OFFSETS)
        (name, off), _a, _moved = self._prepare(
            answers, want_object=True, wanted=self.NAMES)
        self.assertEqual(name, "Door Track")
        self.assertEqual(off, aim.TARGET_OFFSETS[0],
                         "the pointer has to go back to where it answered")

    def test_the_wrong_object_is_still_rejected_outright(self):
        """Standing up is not a licence to act on something the player was
        never told about."""
        answers = [(6, "Impenetrable Door", self.DOOR_HEX, self.DOOR_HEX,
                    False)] * len(aim.TARGET_OFFSETS)
        (name, _off), _a, _moved = self._prepare(
            answers, want_object=True, wanted=["Plastic Explosives"])
        self.assertIsNone(name)


if __name__ == "__main__":
    unittest.main()


class TestLearnedResponse(unittest.TestCase):
    """The servo's model of how screen pixels map to hex rows and columns.

    This is the bug that broke every click in a session at once. The aimer
    lives as long as the mod runs, so a single bad measurement is not one bad
    aim -- it is every aim from then on, on every hex, until a restart.
    """

    def aimer(self):
        return aim.Aimer(hwnd=0, log_path="nowhere.log")

    def test_a_move_that_crossed_no_boundary_teaches_nothing(self):
        """The exact step from the live log: 22 pixels right, same hex.

            mouse=472,334  under=20465
            mouse=494,334  under=20465

        A hex is about thirty pixels across, so a twenty-odd pixel step landing
        inside the one it started in is ordinary. Believed as a measurement it
        says this axis moves nothing, which writes a row of zeros.
        """
        a = self.aimer()
        before = list(a.j)
        a._learn(22, 0, 0, 0)
        self.assertEqual(a.j, before, "a no-change move must not be learned from")

    def test_a_real_move_is_still_learned_from(self):
        a = self.aimer()
        a._learn(60, 0, 1, -2)
        self.assertAlmostEqual(a.j[0], 1 / 60.0)
        self.assertAlmostEqual(a.j[1], -2 / 60.0)

    def test_the_poisoning_sequence_no_longer_breaks_aiming(self):
        """End to end: take the step that killed it, then ask for a solve.

        Before, this returned None and the caller said "cannot work out which
        way to move" for the rest of the session.
        """
        a = self.aimer()
        a._learn(22, 0, 0, 0)
        step = a._solve(0, -1)
        self.assertIsNotNone(step)
        dx, dy = step
        self.assertTrue(abs(dx) > 1 or abs(dy) > 1,
                        "the solve must ask for a real move, got {}".format(step))

    def test_a_singular_model_recovers_instead_of_failing_for_ever(self):
        """The backstop, for whatever writes a bad row next. A wrong-but-sane
        model costs one clumsy aim that then re-measures itself; a singular one
        used to cost every click until the mod was restarted."""
        a = self.aimer()
        a.j = [0.0, 0.0, 0.0, 0.0]
        step = a._solve(1, 1)
        self.assertIsNotNone(step)
        self.assertEqual(a.j, [aim.J_ROW_PER_X, aim.J_COL_PER_X,
                               aim.J_ROW_PER_Y, aim.J_COL_PER_Y])

    def test_solve_never_returns_none(self):
        """The caller turns None into a refusal the player cannot act on."""
        a = self.aimer()
        for j in ([0, 0, 0, 0], [1, 2, 2, 4], list(a.j)):
            a.j = list(j)
            self.assertIsNotNone(a._solve(3, -2), "singular j={}".format(j))
