"""Attack modes, the called-shot window, and the action menu's new lists."""

import unittest

from fallout2_access.app import App, CalledShotWatcher
from fallout2_access.game import calledshot, screens, worldlog
from fallout2_access.game.combat import CombatWatcher, bar_words


def _bar(hand=1, act=1, mode=2, aim=0, kind=3, ap=3, item="Sledgehammer"):
    return [str(hand), str(act), str(mode), str(aim), str(kind), str(ap), item, ""]


class TheAttackBar(unittest.TestCase):
    """What N cycles: the line gl_combat.ssl prints when it changes."""

    def test_a_weapon_attack_says_its_kind_and_cost(self):
        self.assertEqual(bar_words(_bar()), "Sledgehammer, swing, 3 AP.")

    def test_an_aimed_attack_says_so(self):
        self.assertEqual(bar_words(_bar(act=4, mode=3, aim=1, kind=4, ap=5)),
                         "Sledgehammer, thrust, aimed, 5 AP.")

    def test_a_gun_on_burst(self):
        self.assertEqual(
            bar_words(_bar(act=3, mode=3, kind=7, ap=6, item="SMG")),
            "SMG, burst, 6 AP.")

    def test_reload_is_named_by_hit_mode(self):
        self.assertEqual(
            bar_words(_bar(act=5, mode=7, kind=0, ap=2, item="10mm Pistol")),
            "10mm Pistol, reload, 2 AP.")

    def test_empty_hands_and_an_unarmed_special(self):
        self.assertEqual(bar_words(_bar(mode=9, kind=0, ap=3, item="")),
                         "Unarmed, hammer punch, 3 AP.")

    def test_an_item_that_is_used_rather_than_swung(self):
        self.assertEqual(bar_words(_bar(act=0, mode=-1, ap=-1, item="Stimpak")),
                         "Stimpak, use.")

    def test_no_cost_when_the_engine_could_not_be_asked(self):
        """Without unsafe scripting the script sends -1 for the cost."""
        self.assertEqual(bar_words(_bar(ap=-1)), "Sledgehammer, swing.")

    def test_the_hand_is_named_only_when_it_changed(self):
        cw = CombatWatcher()
        first = cw.handle("COMBAT:bar " + "|".join(_bar(hand=1)))
        same = cw.handle("COMBAT:bar " + "|".join(_bar(hand=1, act=2, aim=1)))
        swapped = cw.handle("COMBAT:bar " + "|".join(
            _bar(hand=0, kind=0, mode=4, item="", ap=3)))
        self.assertEqual(first, ["Sledgehammer, swing, 3 AP."])
        self.assertEqual(same, ["Sledgehammer, swing, aimed, 3 AP."])
        self.assertEqual(swapped, ["Left hand. Unarmed, punch, 3 AP."])


class TheChancesTheWindowDraws(unittest.TestCase):
    def test_kept_silently_by_body_part(self):
        cw = CombatWatcher()
        self.assertEqual(cw.handle("COMBAT:aim 0|42|Head|Giant Ant|"), [])
        self.assertEqual(cw.aims[0], (42, "Head"))
        self.assertEqual(cw.aim_target, "Giant Ant")

    def test_a_new_target_starts_a_fresh_table(self):
        cw = CombatWatcher()
        cw.handle("COMBAT:aim 0|42|Head|Giant Ant|")
        cw.handle("COMBAT:aim 3|80|Torso|Rat|")
        self.assertEqual(set(cw.aims), {3})


class TheCalledShotWindow(unittest.TestCase):
    def test_every_body_part_has_exactly_one_button(self):
        self.assertEqual(sorted(calledshot.CODE_TO_LOC), list(range(8)))
        self.assertEqual(sorted(calledshot.ORDER), list(range(8)))
        for loc in range(8):
            self.assertEqual(calledshot.CODE_TO_LOC[calledshot.LOC_TO_CODE[loc]], loc)

    def test_the_list_reads_the_games_names_and_chances(self):
        cw = CombatWatcher()
        cw.handle("COMBAT:aim 0|42|Head|Giant Ant|")
        cw.handle("COMBAT:aim 6|12|Eyes|Giant Ant|")
        shot = calledshot.CalledShot(None, None, cw)
        self.assertEqual(shot.say(), "Head, 42%, 1 of 8.")
        self.assertEqual(shot.step(1), "Eyes, 12%, 2 of 8.")

    def test_the_games_lowercase_names_are_capitalised(self):
        cw = CombatWatcher()
        cw.handle("COMBAT:aim 1|40|left hindleg|Rat|")
        shot = calledshot.CalledShot(None, None, cw)
        self.assertEqual(shot.label(4), "Left hindleg, 40%")

    def test_an_error_from_the_game_is_not_read_out(self):
        cw = CombatWatcher()
        cw.handle("COMBAT:aim 0|30|Error|Rat|")
        self.assertEqual(calledshot.CalledShot(None, None, cw).label(), "Head, 30%")

    def test_a_part_with_no_chance_is_still_named(self):
        shot = calledshot.CalledShot(None, None, CombatWatcher())
        shot.index = 2
        self.assertEqual(shot.label(), "Torso")

    def test_the_list_does_not_wrap(self):
        shot = calledshot.CalledShot(None, None, CombatWatcher())
        shot.step(-1)
        self.assertEqual(shot.index, 0)
        for _ in range(20):
            shot.step(1)
        self.assertEqual(shot.index, 7)


class _Silent:
    def answer(self, *_a, **_k):
        pass

    say = answer


class _Recording(CalledShotWatcher):
    def __init__(self):
        self.calls = []

    def step(self, ann, delta):
        self.calls.append(("step", delta))

    def choose(self, ann):
        self.calls.append(("choose",))

    def cancel(self, ann):
        self.calls.append(("cancel",))

    def repeat(self, ann):
        self.calls.append(("repeat",))


def _drive(what, screen=screens.CALLED_SHOT):
    app = App.__new__(App)
    app.ann = _Silent()
    app.screen = screen
    watcher = _Recording()
    app.watchers = {screens.CALLED_SHOT: watcher}
    App._do_action(app, what)
    return watcher.calls


class TheWindowsKeys(unittest.TestCase):
    def test_arrows_step_the_list(self):
        self.assertEqual(_drive("dlg_prev"), [("step", -1)])
        self.assertEqual(_drive("num2"), [("step", 1)])

    def test_enter_fires(self):
        self.assertEqual(_drive("enter"), [("choose",)])

    def test_the_mouse_buttons_do_nothing_here(self):
        """Escape is the game's own cancel; numpad plus is the map's."""
        self.assertEqual(_drive("click"), [])
        self.assertEqual(_drive("rclick"), [])

    def test_keys_it_has_no_use_for_reach_nothing(self):
        """A modal loop of the engine's is running; nothing may reach past it."""
        self.assertEqual(_drive("barter_offer"), [])

    def test_enter_does_nothing_on_the_map(self):
        class _NotTalking:
            def talking(self):
                return False
        app = App.__new__(App)
        app.ann = _Silent()
        app.screen = "world"
        app.world = _NotTalking()
        app.watchers = {}
        App._do_action(app, "enter")


class TheMenusSecondLists(unittest.TestCase):
    def test_the_skill_list(self):
        self.assertEqual(
            worldlog.menu_line("WORLD:menu sub skill|7|Lockpick, 45%|"),
            "Which skill? Lockpick, 45%, 1 of 7.")

    def test_the_body_part_list(self):
        self.assertEqual(
            worldlog.menu_line("WORLD:menu sub aim|8|Head, 30%|"),
            "Aim where? Head, 30%, 1 of 8.")

    def test_stepping_keeps_the_games_capitals(self):
        self.assertEqual(
            worldlog.menu_line("WORLD:menu at First Aid, 30%|4|7|"),
            "First Aid, 30%, 4 of 7.")

    def test_an_attack_held_back_says_why(self):
        self.assertIn("Aimed", worldlog.attack_line("WORLD:attack aimnow|"))


if __name__ == "__main__":
    unittest.main()
