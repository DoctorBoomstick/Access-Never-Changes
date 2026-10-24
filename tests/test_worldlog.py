"""Parsing the in-game script's output.

debug.log is the only channel the engine gives a script for getting text out, so
everything the mod knows about the live world arrives as lines in this file --
and the engine writes its own debug output into the same file, sometimes without
a newline. These tests use real captured lines, noise included.
"""

import os
import tempfile
import unittest

from fallout2_access.game import worldlog
from fallout2_access.game.worldlog import WorldLog


class LogFixture:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "debug.log")
        open(self.path, "w").close()
        self.log = WorldLog(self.path)

    def write(self, *lines):
        with open(self.path, "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        return self.log.poll()

    def truncate(self):
        open(self.path, "w").close()


class TestWorldLog(unittest.TestCase):
    def setUp(self):
        self.f = LogFixture()

    def test_hex_reading(self):
        self.f.write("WORLD:hex 17488 dist 0 : you|")
        self.assertEqual(self.f.log.last_hex.tile, 17488)
        self.assertEqual(self.f.log.last_hex.contents, "you")
        self.assertEqual(self.f.log.last_hex.announce(), "you")

    def test_a_russian_game_is_read_in_its_own_codepage(self):
        """The scripts write the game's bytes; Russian ones are cp1251."""
        from fallout2_access import codepage

        codepage.set_language("russian")
        try:
            with open(self.f.path, "ab") as fh:
                fh.write("WORLD:hex 17488 dist 0 : Куст|\n".encode("cp1251"))
            self.f.log.poll()
            self.assertEqual(self.f.log.last_hex.contents, "Куст")
        finally:
            codepage.set_language("english")

    def test_distance_is_pluralised(self):
        self.f.write("WORLD:hex 17687 dist 1 : empty|")
        self.assertEqual(self.f.log.last_hex.announce(), "empty, 1 hex")
        self.f.write("WORLD:hex 17686 dist 2 : Tree|")
        self.assertEqual(self.f.log.last_hex.announce(), "Tree, 2 hexes")

    def test_engine_noise_after_the_terminator_is_discarded(self):
        """Captured verbatim: the engine appended its own line to ours."""
        self.f.write("WORLD:hex 25911 dist 1 : Giant Ant|sequencing attack...")
        self.assertEqual(self.f.log.last_hex.contents, "Giant Ant")

    def test_an_exit_is_said_instead_of_empty(self):
        """The hex is not empty, it is the way out."""
        self.f.write("WORLD:hex 19850 dist 3 : empty|exit:Exit to Downtown|")
        self.assertEqual(self.f.log.last_hex.exit, "Exit to Downtown")
        self.assertEqual(self.f.log.last_hex.announce(),
                         "Exit to Downtown, 3 hexes")

    def test_an_exit_follows_whatever_else_is_there(self):
        self.f.write("WORLD:hex 19850 dist 0 : you|exit:Exit to Downtown|")
        self.assertEqual(self.f.log.last_hex.announce("Tara"),
                         "Tara, Exit to Downtown")

    def test_an_exit_is_not_something_to_aim_at(self):
        """Every name is something a click hunts for under the pointer, and no
        pointer is ever confirmed over "Exit to Downtown". Walking onto an exit
        would have become "cannot point at that"."""
        self.f.write("WORLD:hex 19850 dist 3 : empty|exit:Exit to Downtown|")
        self.assertEqual(self.f.log.last_hex.names(), [])

    def test_engine_noise_is_never_an_exit(self):
        self.f.write("WORLD:hex 25911 dist 1 : Giant Ant|sequencing attack|")
        self.assertEqual(self.f.log.last_hex.exit, "")

    def test_cursorok_reports_the_mode_too(self):
        """Only parsing `cursormode` left the mode unknown exactly when nothing
        had changed -- which is the common case, and the one the click path
        needs an answer for."""
        self.f.write("WORLD:cursorok 2|")
        self.assertEqual(self.f.log.cursor_mode, 2)
        self.f.write("WORLD:cursormode 0|")
        self.assertEqual(self.f.log.cursor_mode, 0)

    def test_game_mode_and_session_liveness(self):
        self.assertFalse(self.f.log.session_live)
        self.f.write("WORLD:ready")
        self.assertTrue(self.f.log.session_live)
        self.f.write("WORLD:gamemode 64")
        self.assertEqual(self.f.log.game_mode, 64)

    def test_combat_lines_are_passed_through(self):
        out = self.f.write("COMBAT:turn 1|you|")
        self.assertEqual(out, ["COMBAT:turn 1|you|"])

    def test_combat_ready_marks_the_session_live(self):
        self.f.write("COMBAT:ready|")
        self.assertTrue(self.f.log.session_live)

    def test_relaunch_resets_everything(self):
        """The game truncates debug.log on launch, so a shrinking file means a
        new session and every remembered fact belongs to a dead one."""
        self.f.write("WORLD:ready", "WORLD:gamemode 0", "WORLD:hex 1 dist 0 : you|")
        self.assertTrue(self.f.log.session_live)
        self.f.truncate()
        self.f.write("WORLD:hex 2 dist 0 : you|")
        self.assertEqual(self.f.log.last_hex.tile, 2)

    def test_missing_file_is_survivable(self):
        log = WorldLog(os.path.join(self.f.dir, "nope.log"))
        self.assertEqual(log.poll(), [])

    def _pumped(self, *lines):
        """Feed lines and let a WorldWatcher consume them.

        Written straight to the file rather than through the fixture, because
        the fixture polls as it writes and would eat the line first.
        """
        from fallout2_access.app import WorldWatcher

        w = WorldWatcher(self.f.log)
        with open(self.f.path, "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        w.pump()
        return w

    def test_arrive_distance_drops_the_terminator(self):
        """Heard as "Moved 2| hexes." -- the line gained a trailing separator
        to keep engine noise out, and the parse took the bar with the number."""
        w = self._pumped("WORLD:arrive 17686 dist 2|")
        self.assertEqual([t for t, _u in w._queue], ["Moved 2 hexes."])

    def test_prepare_lines_are_not_spoken(self):
        """Heard as "prepare 6|". It is the click setting its own cursor."""
        w = self._pumped("WORLD:prepare 6|Door, locked|")
        self.assertEqual(w._queue, [])

    def test_unrelated_lines_are_ignored(self):
        out = self.f.write("Gsound: playing ambient map sfx: animal1")
        self.assertEqual(out, [])

    def _walked(self, *lines):
        """Feed lines to a watcher holding a ticker that counts instead of
        playing, and report how many ticks it produced."""
        from fallout2_access.app import WorldWatcher

        class Counter:
            def __init__(self):
                self.ticks = 0

            def step(self):
                self.ticks += 1

        counter = Counter()
        w = WorldWatcher(self.f.log, ticker=counter)
        with open(self.f.path, "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        w.pump()
        return counter.ticks, w

    def test_each_hex_walked_makes_a_sound(self):
        """The line was always here and always silenced -- correctly, since
        twelve "moved 1 hex" across a room is why the arrival is announced at
        the end instead. What that left was several seconds of nothing in the
        middle of a walk, which is what a stopped mod also sounds like."""
        ticks, w = self._walked("WORLD:dude 17488|", "WORLD:dude 17489|",
                                "WORLD:dude 17490|")
        self.assertEqual(ticks, 3)

    def test_walking_still_says_nothing(self):
        """A tick is not an announcement. It does not interrupt and does not
        queue, which is the whole reason it can happen twelve times."""
        _ticks, w = self._walked("WORLD:dude 17488|")
        self.assertEqual(w._queue, [])

    def test_your_name_is_not_a_footstep(self):
        """"WORLD:dudename" shares four letters with the line above it, and a
        prefix test without the space would tick once per map change and say
        nothing about why."""
        ticks, _w = self._walked("WORLD:dudename Tara|")
        self.assertEqual(ticks, 0)



class TestWeaponLine(unittest.TestCase):
    """What is in your hand, and whether it is loaded.

    The interface bar shows a sighted player the weapon, a green bar for the
    rounds left in it, the firing mode and what that mode costs. All four were
    unreachable, which is a missing convenience right up until you have a gun,
    and then it is a weapon you cannot tell is empty.
    """

    LOADED = ("WORLD:weapon 1|Pipe Rifle|1|6|10|10mm JHP|6|5|0|0|0|0|4|"
              "Sharpened Spear|")

    def test_the_gun_its_load_and_its_ammunition(self):
        said = worldlog.weapon_line(self.LOADED)
        self.assertIn("Pipe Rifle", said)
        self.assertIn("6 of 10", said)
        self.assertIn("10mm JHP", said)

    def test_an_empty_gun_says_empty_rather_than_nought(self):
        """"0 of 10" is a sentence the listener has to finish, and the moment
        it matters is the moment something is biting them."""
        said = worldlog.weapon_line(
            "WORLD:weapon 1|Pipe Rifle|1|0|10|10mm JHP|6|5|6|6|0|0|4||")
        self.assertIn("empty", said)
        self.assertNotIn("0 of 10", said)

    def test_the_firing_mode_and_what_it_costs(self):
        said = worldlog.weapon_line(
            "WORLD:weapon 1|SMG|1|30|30|10mm AP|6|5|7|6|0|10|4||")
        self.assertIn("Single shot, 5 AP", said)
        self.assertIn("Burst of 10, 6 AP", said)

    def test_one_mode_twice_is_said_once(self):
        """Plenty of weapons carry the same number in both slots, and "single
        shot, then single shot" is noise on a readout that has to be quick."""
        said = worldlog.weapon_line(
            "WORLD:weapon 1|Pipe Rifle|1|6|10|10mm JHP|6|5|6|5|0|0|4||")
        self.assertEqual(said.count("Single shot"), 1)

    def test_the_same_mode_at_a_different_cost_is_two_answers(self):
        """A cheaper and a dearer way to use the same weapon are two choices,
        not one said twice -- dropping the second would hide the option."""
        said = worldlog.weapon_line(
            "WORLD:weapon 1|Pipe Rifle|1|6|10|10mm JHP|6|5|6|6|0|0|4||")
        self.assertEqual(said.count("Single shot"), 2)
        self.assertIn("5 AP", said)
        self.assertIn("6 AP", said)

    def test_a_melee_weapon_has_no_ammunition_to_report(self):
        said = worldlog.weapon_line(
            "WORLD:weapon 0|Sharpened Spear|1|0|0||4|4|5|5|0|0|5||")
        self.assertNotIn("empty", said)
        self.assertNotIn(" of ", said)
        self.assertIn("Thrust, 4 AP", said)
        self.assertIn("Throw, 5 AP", said)

    def test_minimum_strength_is_left_to_the_weapons_own_description(self):
        """It is printed in the examine text, which the mod already reads
        aloud. A readout meant to be pressed mid-fight should not repeat what
        the description says at length."""
        self.assertNotIn("strength", worldlog.weapon_line(self.LOADED))

    def test_something_that_is_not_a_weapon_still_gets_an_answer(self):
        """The key means "what is in my hand". Answering only for guns would
        leave it silent exactly when the player has picked up something they
        cannot identify."""
        said = worldlog.weapon_line(
            "WORLD:weapon 1|Healing Powder|0|0|0||0|0|0|0|0|0|0||")
        self.assertIn("Healing Powder", said)
        self.assertIn("Not a weapon", said)

    def test_an_empty_active_hand_names_the_other_one(self):
        """"Your hands are empty" would be wrong, and unhelpful, in the common
        case of simply not having swapped hands."""
        said = worldlog.weapon_line(
            "WORLD:weapon 0||0|0|0||0|0|0|0|0|0|0|Pipe Rifle|")
        self.assertIn("Pipe Rifle", said)
        self.assertIn("other", said)
        self.assertIn("b", said)

    def test_both_hands_empty(self):
        said = worldlog.weapon_line("WORLD:weapon 0||0|0|0||0|0|0|0|0|0|0||")
        self.assertEqual(said, "Both hands empty.")

    def test_an_unparsable_line_is_not_spoken(self):
        self.assertIsNone(worldlog.weapon_line("WORLD:weapon garbage"))
        self.assertIsNone(worldlog.weapon_line("WORLD:status 48|48|8|10|8|1|"))


class TestAimingAtYourself(unittest.TestCase):
    """Using a stimpak on yourself used it on the wall behind you.

    Your own hex reports "you", which means "nothing here to point at" -- right
    for every ordinary click, since what you want is the ground you are standing
    on. But the aim then settles on the hex centre, which is your feet, and
    Fallout picks what a click hits by the sprite over that pixel. Measured
    live: the engine said "Wooden Wall" at the centre and "Tara" fifty-six
    pixels higher.
    """

    from fallout2_access.game import screens as _screens

    def _here(self, contents="you, facing north east", distance=0):
        return worldlog.HexReading(tile=18046, distance=distance,
                                   contents=contents)

    def test_an_armed_item_points_at_you(self):
        self.assertEqual(
            worldlog.aim_at_yourself(self._here(),
                                     self._screens.CURSOR_USE_ITEM, "Tara"),
            ["Tara"])

    def test_an_armed_skill_points_at_you(self):
        """First Aid on yourself is the common case, and it had the same
        failure for the same reason."""
        first_aid = sorted(self._screens.SKILL_CURSORS)[0]
        self.assertEqual(
            worldlog.aim_at_yourself(self._here(), first_aid, "Tara"),
            ["Tara"])

    def test_an_ordinary_click_still_means_the_ground(self):
        """Standing still and clicking your own hex is not a request to point
        at your own body."""
        self.assertIsNone(worldlog.aim_at_yourself(
            self._here(), self._screens.CURSOR_MOVEMENT, "Tara"))

    def test_another_hex_is_not_you(self):
        self.assertIsNone(worldlog.aim_at_yourself(
            self._here(distance=3), self._screens.CURSOR_USE_ITEM, "Tara"))

    def test_something_named_on_your_hex_still_wins(self):
        """A stimpak lying at your feet is a thing the readout named, and the
        aimer should go on hunting for that rather than for you."""
        self.assertIsNone(worldlog.aim_at_yourself(
            self._here(contents="you, Stimpak"),
            self._screens.CURSOR_USE_ITEM, "Tara"))

    def test_no_name_yet_means_no_hunt(self):
        """The name arrives on a map change. Before it does there is nothing to
        ask the engine to confirm, and hunting for None would refuse the click
        with a sentence about pointing at nothing."""
        self.assertIsNone(worldlog.aim_at_yourself(
            self._here(), self._screens.CURSOR_USE_ITEM, None))

    def test_no_reading_at_all(self):
        self.assertIsNone(worldlog.aim_at_yourself(
            None, self._screens.CURSOR_USE_ITEM, "Tara"))


class TestAmmoLine(unittest.TestCase):
    """A reload, noticed by the count going up rather than by a key going down.

    The forum thread that started this is the specification: the poster had
    reloaded successfully three times and could not tell, because the only
    feedback Fallout gives is a green bar refilling and the mode snapping back
    to the first one.
    """

    def test_a_reload_is_reported_with_the_new_load(self):
        said = worldlog.ammo_line("WORLD:ammo 10|10|")
        self.assertIn("Reloaded", said)
        self.assertIn("10 of 10", said)

    def test_a_partial_reload_says_what_actually_went_in(self):
        """Reload tops a gun up with the ammunition already in it, so a
        half-filled magazine is a real outcome and not a failure."""
        self.assertIn("4 of 10", worldlog.ammo_line("WORLD:ammo 4|10|"))

    def test_a_gun_with_no_stated_capacity_still_reports(self):
        self.assertIn("Reloaded. 1.", worldlog.ammo_line("WORLD:ammo 1|0|"))

    def test_an_unparsable_line_is_not_spoken(self):
        self.assertIsNone(worldlog.ammo_line("WORLD:ammo garbage"))
        self.assertIsNone(worldlog.ammo_line("WORLD:status 48|48|8|10|8|1|"))


class TestStatusLine(unittest.TestCase):
    """Health, action points and armour class -- the three numbers a sighted
    player reads off the interface bar without pressing anything."""

    def test_order_is_health_then_action_points_then_armour(self):
        said = worldlog.status_line("WORLD:status 48|48|8|10|8|1|")
        self.assertLess(said.index("Health"), said.index("action"))
        self.assertLess(said.index("action"), said.index("Armor"))

    def test_in_combat_action_points_are_a_remainder(self):
        said = worldlog.status_line("WORLD:status 31|48|3|10|8|1|")
        self.assertIn("3 of 10 action points", said)

    def test_out_of_combat_action_points_are_a_capacity(self):
        """The engine keeps a running count outside a fight, but it is not a
        number anyone is spending -- reporting it as a remainder would be true
        of nothing."""
        said = worldlog.status_line("WORLD:status 31|48|3|10|8|0|")
        self.assertIn("10 action points", said)
        self.assertNotIn("3 of", said)

    def test_damage_shows_in_the_health_figure(self):
        self.assertIn("Health 31 of 48",
                      worldlog.status_line("WORLD:status 31|48|0|10|8|0|"))

    def test_an_unparsable_line_is_not_spoken(self):
        self.assertIsNone(worldlog.status_line("WORLD:status garbage"))
        self.assertIsNone(worldlog.status_line("WORLD:hex 17488 dist 0 : you|"))


class TestLevelOnTheStatusLine(unittest.TestCase):
    """Level and experience, which had no key at all.

    Both are on the character sheet and always have been. The sheet is a screen
    you open, read and close, which is a long way to go for a one-word answer,
    so they ride along on the key that already reports how you are doing.
    """

    def test_the_level_is_read_out(self):
        said = worldlog.status_line("WORLD:status 48|48|8|10|8|0|2|1450|")
        self.assertIn("Level 2", said)

    def test_what_is_left_to_go_rather_than_the_total(self):
        """Level 2 wants 3,000 in total. Somebody with 1,450 wants 1,550 more,
        and that subtraction is not one to make in your head while a screen
        reader moves on to the next sentence."""
        said = worldlog.status_line("WORLD:status 48|48|8|10|8|0|2|1450|")
        self.assertIn("1550 experience to the next level", said)
        self.assertNotIn("3000", said)

    def test_it_comes_after_the_three_that_matter_in_a_fight(self):
        said = worldlog.status_line("WORLD:status 48|48|8|10|8|1|2|1450|")
        self.assertLess(said.index("Armor"), said.index("Level"))

    def test_the_old_six_field_line_still_works(self):
        """A game still running the previously compiled script must keep its
        status key. A regex demanding eight fields would not lose the level, it
        would match nothing and say nothing at all."""
        said = worldlog.status_line("WORLD:status 48|48|8|10|8|0|")
        self.assertIn("Health 48 of 48", said)
        self.assertNotIn("Level", said)

    def test_a_threshold_already_passed_is_dropped_rather_than_negative(self):
        """The threshold is arithmetic, not a reading, so a retabled
        progression or the level cap can put it behind you. The level is still
        a fact; a negative number of points to go is not."""
        said = worldlog.status_line("WORLD:status 48|48|8|10|8|0|21|9999999|")
        self.assertIn("Level 21", said)
        self.assertNotIn("experience", said)


class TestUseItemLine(unittest.TestCase):
    """Using the item in your hand on the thing the look cursor is on.

    The one action the engine's menu offered that nothing else could reach:
    walking, attacking, using an object and using a skill are all cursor modes,
    and "use an ITEM on that" is not.
    """

    def say(self, line):
        return worldlog.use_item_line(line)

    def test_the_attempt_names_both_halves(self):
        self.assertEqual(
            self.say("WORLD:useitem try Plastic Explosives|Impenetrable Door|"),
            "Using Plastic Explosives on Impenetrable Door.")

    def test_empty_hands_say_what_to_do_about_it(self):
        """A refusal that does not say how to proceed is a dead end to someone
        who cannot see the hand slots."""
        text = self.say("WORLD:useitem empty|")
        self.assertIn("empty", text)
        self.assertIn("Ready an item", text)

    def test_nothing_to_use_it_on(self):
        self.assertEqual(self.say("WORLD:useitem notarget 14322|"),
                         "Nothing there to use it on.")

    def test_finishing_says_nothing_and_that_is_deliberate(self):
        """The engine runs the object's own handler and reports the outcome in
        its own words through the display window, which the mod already reads.
        A verdict invented here would talk over the one voice that knows."""
        self.assertIsNone(
            self.say("WORLD:useitem done Plastic Explosives|Impenetrable Door|"))

    def test_an_unknown_outcome_is_silent_rather_than_raw(self):
        self.assertIsNone(self.say("WORLD:useitem wat|"))

    def test_a_line_that_is_not_ours_is_ignored(self):
        self.assertIsNone(self.say("WORLD:hex 14322 dist 1 : Door|"))


class TestUseObjLine(unittest.TestCase):
    """"Use it" -- the hand icon.

    Nothing could reach this before: the mod only ever selects the movement or
    targeting cursor, so a click on a door walked into it rather than opening
    it, and opening one needs the command cursor the mod never picks.
    """

    def test_the_attempt_names_the_target(self):
        self.assertEqual(
            worldlog.use_obj_line("WORLD:useobj try Impenetrable Door|"),
            "Using Impenetrable Door.")

    def test_nothing_there(self):
        self.assertEqual(worldlog.use_obj_line("WORLD:useobj notarget 14322|"),
                         "Nothing there to use.")

    def test_finishing_leaves_the_verdict_to_the_game(self):
        self.assertIsNone(
            worldlog.use_obj_line("WORLD:useobj done Impenetrable Door|"))


class TestMenuLine(unittest.TestCase):
    """The mod's own version of the icon strip a sighted player gets.

    Fallout's strip cannot be driven -- it is drawn as a mouse cursor, and
    nothing in the process tracks which icon is under the pointer. So the
    contents come from the engine and the presentation is ours: arrows move,
    Enter does it.
    """

    def say(self, line, aimed=None):
        return worldlog.menu_line(line, aimed)

    def test_opening_names_the_object_and_the_first_action(self):
        self.assertEqual(
            self.say("WORLD:menu open Impenetrable Door|4|use it|1|"),
            "Impenetrable Door. 4 actions. Use it, 1 of 4.")

    def test_moving_says_where_you_are_in_the_list(self):
        """Which is why there is no repeat key: moving re-announces, the way
        every list does."""
        self.assertEqual(self.say("WORLD:menu at look at it|2|4|"),
                         "Look at it, 2 of 4.")

    def test_a_stale_list_is_refused_rather_than_read_out(self):
        """The engine's array is never cleared, only overwritten, and it is
        never empty -- so a list read a moment too early is a confident menu
        for the PREVIOUS object and looks exactly like a good one. Python knows
        what it aimed at; the script names what it opened for."""
        text = self.say("WORLD:menu open Pot|4|use it|1|",
                        aimed="Impenetrable Door")
        self.assertIn("wrong thing", text)
        self.assertIn("Impenetrable Door", text)
        self.assertIn("Pot", text)

    def test_matching_names_read_normally(self):
        self.assertIn("Impenetrable Door. 4 actions.",
                      self.say("WORLD:menu open Impenetrable Door|4|use it|1|",
                               aimed="Impenetrable Door"))

    def test_a_locked_door_is_not_a_mismatch(self):
        """Both names come from the engine, through two doors that word them
        differently: the aim reports through obj_label, which appends the
        state, while the menu reports the bare obj_name. Compared for equality
        this cried wolf on every locked door and open container -- refusing a
        perfectly good menu for the one kind of object it matters most for."""
        text = self.say("WORLD:menu open Door|4|use it|1|", aimed="Door, locked")
        self.assertNotIn("wrong thing", text)
        self.assertIn("4 actions", text)

    def test_a_genuinely_different_object_is_still_caught(self):
        """Tolerance is not surrender: the stale-list check has to keep working
        or the safety it provides is gone."""
        self.assertIn("wrong thing",
                      self.say("WORLD:menu open Pot|4|use it|1|",
                               aimed="Door, locked"))

    def test_an_action_the_mod_cannot_do_says_so(self):
        """Silence after Enter reads as the key never arriving."""
        self.assertIn("no way to do it yet",
                      self.say("WORLD:menu noroute look at it|"))

    def test_nothing_to_act_on(self):
        self.assertEqual(self.say("WORLD:menu none|"),
                         "Nothing there to act on.")

    def test_an_object_with_no_actions(self):
        self.assertEqual(self.say("WORLD:menu empty Stone Bench|"),
                         "Stone Bench. Nothing you can do to it.")

    def test_backing_out(self):
        self.assertEqual(self.say("WORLD:menu closed|"), "Closed.")


class TestUseActiveLine(unittest.TestCase):
    """The U key: use whatever is in your hand.

    The script reports rather than acts, because using a carried item ends in a
    click on the interface bar's item slot and only the Python side has a
    pointer. The weapon flag is reported but no longer vetoes anything.
    """

    def test_a_usable_item_is_used(self):
        name, weapon, said = worldlog.use_active_line(
            "WORLD:useactive Plastic Explosives|0|")
        self.assertEqual(name, "Plastic Explosives")
        self.assertFalse(weapon)
        self.assertIn("Using Plastic Explosives", said)

    def test_a_weapon_is_used_and_said_to_be_one(self):
        """The slot attacks with a weapon live, and that is the player's call.

        It used to refuse and explain itself. A sighted player presses the same
        slot with the same spear in hand and the game does not argue; refusing
        on their behalf is a smaller game, not an accessible one. The flag is
        still SAID, because what is in your hand is the fact that makes the
        decision an informed one.
        """
        name, weapon, said = worldlog.use_active_line("WORLD:useactive Spear|1|")
        self.assertEqual(name, "Spear")
        self.assertTrue(weapon)
        self.assertIn("Using Spear", said)
        self.assertIn("weapon", said)
        self.assertNotIn("refused", said)

    def test_empty_hands_say_what_to_do(self):
        name, weapon, said = worldlog.use_active_line("WORLD:useactive empty|0||")
        self.assertIsNone(name)
        self.assertIn("Ready something", said)

    def test_an_empty_active_hand_names_what_the_other_one_holds(self):
        """The failure this was written for.

        The slot acts on the ACTIVE hand. With Healing Powder in one hand and
        the other empty and active, the script used to report the powder, the
        mod said "Using Healing Powder", the click landed correctly on the item
        slot, and nothing happened -- every part of the chain working except the
        question being asked. Saying where the thing actually is turns a key
        that looks broken into a state the player can fix.
        """
        name, weapon, said = worldlog.use_active_line(
            "WORLD:useactive empty|0|Healing Powder|")
        self.assertIsNone(name, "nothing to click the slot for")
        self.assertIn("active hand is empty", said)
        self.assertIn("Healing Powder", said)

    def test_an_older_compiled_script_still_parses(self):
        """The third field is new. A game running yesterday's gl_world.int
        emits the two-field form, and it must not read as a crash."""
        name, weapon, said = worldlog.use_active_line("WORLD:useactive empty|")
        self.assertIsNone(name)
        self.assertIn("Ready something", said)

    def test_a_line_that_is_not_ours(self):
        self.assertIsNone(worldlog.use_active_line("WORLD:hex 1 dist 0 : you|"))


class TestUseActiveArms(unittest.TestCase):
    """U arms the active item; the target the player then picks decides what it
    is used ON. That second step is not a gap to route around -- it is what
    lets one key serve a stimpak, a lockpick and a brick of explosive.

    Applying the item to the player directly was tried, through sfall's
    use_item_on_dude, and had to be reverted: it skips the action point cost,
    and it aims every item at the player, including the ones that should never
    be pointed there.
    """

    def test_a_usable_item_is_named_and_handed_on(self):
        name, weapon, said = worldlog.use_active_line(
            "WORLD:useactive Healing Powder|0||")
        self.assertEqual(name, "Healing Powder")
        self.assertFalse(weapon)
        self.assertIn("Using Healing Powder", said)

    def test_a_weapon_is_named_as_one_and_still_handed_on(self):
        name, weapon, said = worldlog.use_active_line("WORLD:useactive Spear|1||")
        self.assertEqual(name, "Spear")
        self.assertTrue(weapon)
        self.assertIn("weapon", said)


class TestPickLine(unittest.TestCase):
    """The target list: which thing on the hex you meant.

    It exists because "which object" used to be answered by where a mouse
    pointer ended up, and that was wrong twice in ways a player could not see --
    a door lost to the Door Track sharing its tile, and walkable ground refused
    because a wall was drawn across it. Choosing from a list cannot land on the
    wrong thing, because nothing is aimed.
    """

    def say(self, line):
        return worldlog.pick_line(line)

    def test_opening_says_how_many_and_which_one(self):
        """The count is the useful part: it says whether stepping the list is
        worth doing at all."""
        self.assertEqual(self.say("WORLD:pick open|Door Track|1|2|"),
                         "2 things here. Door track, 1 of 2.")

    def test_stepping_does_not_repeat_the_count(self):
        """Said once on the way in. Repeated on every step it would bury the
        thing being stepped to."""
        self.assertEqual(self.say("WORLD:pick at|Door|2|2|"), "Door, 2 of 2.")

    def test_an_empty_hex_says_so(self):
        self.assertEqual(self.say("WORLD:pick none|"), "Nothing here to act on.")

    def test_escape_is_confirmed(self):
        """Silence after a keypress is indistinguishable from the key never
        arriving, which is the misreading this project keeps designing against."""
        self.assertEqual(self.say("WORLD:pick closed|"), "Cancelled.")

    def test_a_target_that_went_away(self):
        self.assertEqual(self.say("WORLD:pick gone|"), "That is no longer there.")

    def test_you_are_a_target(self):
        """The pointer route could never offer this -- prepare_cursor asks
        obj_under_cursor with includeDude 0 and is blind to the player. Being
        nameable is what makes "use the powder on me" reachable."""
        self.assertIn("Yourself", self.say("WORLD:pick at|yourself|1|3|"))

    def test_a_line_that_is_not_ours(self):
        self.assertIsNone(self.say("WORLD:hex 1 dist 0 : you|"))


class TestWhoYouAreAndWhichWayYouFace(unittest.TestCase):
    """Your own hex used to read "you" and nothing else.

    Two things were missing from it. Every other critter on the map is reported
    with the direction it is looking, because sneaking and stealing turn on
    where a back is -- and yours was the one facing a sighted player reads off
    the screen at a glance and a blind player could not obtain at all. And the
    word for you was "you", which is nobody's name.

    The name is NOT sent in the readout. "you" is one of the words that tells
    the parser this hex holds nothing to point at, so a line reading "Tara"
    would put the click machinery to work aiming at a character the engine
    deliberately will not confirm a pointer is over. It is sent separately and
    put in at the moment the line is spoken.
    """

    def setUp(self):
        self.f = LogFixture()

    def test_the_name_arrives_on_its_own_line(self):
        self.f.write("WORLD:dudename Tara|")
        self.assertEqual(self.f.log.player_name, "Tara")

    def test_the_name_is_not_announced_when_it_arrives(self):
        """It is a fact to keep, not an event. Nobody wants their own name read
        out every time they walk through a door.

        Checked against the list that actually silences it rather than against
        the poll's output, which is where the first version of this test went
        wrong -- it polled a second time, got the empty list a consumed log
        always gives, and passed without testing anything.
        """
        from fallout2_access.app import WORLD_QUIET

        self.assertTrue("WORLD:dudename Tara|".startswith(WORLD_QUIET))

    def test_your_hex_says_your_name_and_your_facing(self):
        self.f.write("WORLD:dudename Tara|")
        self.f.write("WORLD:hex 17488 dist 0 : you, facing north east|")
        self.assertEqual(
            self.f.log.last_hex.announce(self.f.log.player_name),
            "Tara, facing north east")

    def test_without_a_name_it_still_says_you(self):
        """True, and better than a name nobody has checked."""
        self.f.write("WORLD:hex 17488 dist 0 : you, facing west|")
        self.assertEqual(self.f.log.last_hex.announce(), "you, facing west")

    def test_you_are_still_not_an_object_to_aim_at(self):
        self.f.write("WORLD:hex 17488 dist 0 : you, facing north east|")
        self.assertEqual(self.f.log.last_hex.names(), [])

    def test_something_else_on_your_hex_is_still_found(self):
        self.f.write("WORLD:dudename Tara|")
        self.f.write("WORLD:hex 17488 dist 0 : you, facing west, Rocks|")
        self.assertEqual(self.f.log.last_hex.names(), ["Rocks"])
        self.assertIn("Rocks",
                      self.f.log.last_hex.announce(self.f.log.player_name))

    def test_a_young_radscorpion_keeps_its_you(self):
        """The substitution is field by field and only on a whole field. A
        blanket replace would find the "you" inside this one, on a hex where
        being told the wrong thing has consequences."""
        self.f.write("WORLD:dudename Tara|")
        self.f.write("WORLD:hex 17490 dist 3 : Young Radscorpion, facing west|")
        self.assertIn("Young Radscorpion",
                      self.f.log.last_hex.announce(self.f.log.player_name))
        self.assertNotIn("Tara",
                         self.f.log.last_hex.announce(self.f.log.player_name))

    def test_a_relaunch_forgets_the_name(self):
        self.f.write("WORLD:dudename Tara|")
        self.f.truncate()
        self.f.log.poll()
        self.assertIsNone(self.f.log.player_name)




class TestRoofs(unittest.TestCase):
    def setUp(self):
        self.f = LogFixture()

    def test_a_roof_is_said_after_what_is_there(self):
        self.f.write("WORLD:hex 19850 dist 3 : Locker|roof|")
        self.assertTrue(self.f.log.last_hex.roofed)
        self.assertEqual(self.f.log.last_hex.announce(), "Locker, roofed, 3 hexes")

    def test_empty_and_roofed(self):
        self.f.write("WORLD:hex 19850 dist 1 : empty|roof|")
        self.assertEqual(self.f.log.last_hex.announce(), "empty, roofed, 1 hex")

    def test_with_an_exit(self):
        self.f.write("WORLD:hex 19850 dist 0 : you|exit:Exit to Downtown|roof|")
        self.assertEqual(self.f.log.last_hex.announce("Tara"),
                         "Tara, Exit to Downtown, roofed")

    def test_roofed_is_not_something_to_aim_at(self):
        self.f.write("WORLD:hex 19850 dist 3 : Locker|roof|")
        self.assertEqual(self.f.log.last_hex.names(), ["Locker"])

    def test_no_roof(self):
        self.f.write("WORLD:hex 19850 dist 3 : Locker|")
        self.assertFalse(self.f.log.last_hex.roofed)
        self.assertEqual(self.f.log.last_hex.announce(), "Locker, 3 hexes")


class TestLight(unittest.TestCase):
    def test_daylight(self):
        self.assertEqual(worldlog.light_line("WORLD:light 0|65536|0|0|2|"),
                         "100 percent light, bright.")

    def test_the_bands_are_the_engines(self):
        # At or below each limit, as determine_to_hit compares.
        self.assertIn("very dark: minus 40",
                      worldlog.light_line("WORLD:light 0|26214|0|0|2|"))
        self.assertIn("dark: minus 25",
                      worldlog.light_line("WORLD:light 0|26215|0|0|2|"))
        self.assertIn("dim: minus 10",
                      worldlog.light_line("WORLD:light 0|52428|0|0|2|"))
        self.assertIn("bright",
                      worldlog.light_line("WORLD:light 0|52429|0|0|2|"))

    def test_a_flare_lights_the_hex(self):
        said = worldlog.light_line("WORLD:light 60000|16384|0|0|4|")
        self.assertEqual(said, "92 percent light, bright, lit from nearby.")

    def test_your_own_glow_does_not_count_on_your_own_hex(self):
        said = worldlog.light_line("WORLD:light 30000|16384|1|20000|0|")
        # 30000 - 20000 = 10000, below ambient, so ambient it is.
        self.assertTrue(said.startswith("25 percent light, very dark"))
        self.assertNotIn("nearby", said)




class TestRoute(unittest.TestCase):
    def test_the_way_is_said(self):
        said = worldlog.route_line("WORLD:route way|0|16|12|0|2|1*6,0*10,|")
        self.assertEqual(said, "16 steps, 12 hexes straight. East 6, north east 10.")

    def test_a_zigzag_up_the_screen_is_north(self):
        runs = "0*1,5*1,0*1,5*1,1*3,"
        said = worldlog.route_line("WORLD:route way|0|7|5|0|5|" + runs + "|")
        self.assertEqual(said, "7 steps, 5 hexes straight. North 4, east 3.")

    def test_two_turns_are_not_a_zigzag(self):
        self.assertEqual(worldlog.route_turns([(0, 5), (5, 1)]),
                         [("north east", 5), ("north west", 1)])

    def test_doors_on_the_way(self):
        said = worldlog.route_line("WORLD:route way|0|3|3|1|1|1*3,|")
        self.assertTrue(said.endswith("Through 1 door."))

    def test_a_long_way_is_cut_short(self):
        runs = ",".join("{}*2".format(d) for d in (1, 2, 1, 2, 1, 2, 1, 2)) + ","
        said = worldlog.route_line("WORLD:route way|0|16|9|0|8|" + runs + "|")
        self.assertTrue(said.endswith(", and on."))

    def test_walking(self):
        self.assertEqual(worldlog.route_line("WORLD:route way|1|31|12|0|4|1*31,|"),
                         "Walking there, 31 steps.")

    def test_finding_it_again_on_the_way_is_not_news(self):
        self.assertIsNone(worldlog.route_line("WORLD:route way|2|31|12|0|4|1*31,|"))
        self.assertIsNone(worldlog.route_line("WORLD:route search|17488|"))

    def test_how_it_ended(self):
        self.assertEqual(worldlog.route_line("WORLD:route end|arrived|"), "Arrived.")
        self.assertEqual(worldlog.route_line("WORLD:route end|cancel|"), "Stopped.")
        # Said on their own lines, or by the screen that opened.
        self.assertIsNone(worldlog.route_line("WORLD:route end|door|"))
        self.assertIsNone(worldlog.route_line("WORLD:route end|screen|"))

    def test_a_door(self):
        self.assertEqual(worldlog.route_line("WORLD:route door|Door|"),
                         "Stopped at Door. The look cursor is on it.")

    def test_unreachable(self):
        self.assertEqual(worldlog.route_line("WORLD:route none|14|"),
                         "No way there from here.")


if __name__ == "__main__":
    unittest.main()
