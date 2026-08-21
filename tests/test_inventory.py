"""Speaking the inventory, loot and barter windows.

The fixtures are the lines gl_inven.ssl actually writes. The window has three
lists that mean different things, and most of what is tested here is that the
wording tells them apart -- an empty hand and an empty container are both
"nothing", and only one of them is worth hearing about.
"""

import unittest

from fallout2_access.game import inventory
from fallout2_access.game.inventory import (
    SIDE_MINE,
    SIDE_THEIRS,
    SIDE_WORN,
    InventoryWatcher,
)


def entry(side, index, total, name, count=1, weight=0, slot=-1):
    return "INVEN:entry {}|{}|{}|{}|{}|{}|{}|".format(
        side, index, total, name, count, weight, slot
    )


class TestOpening(unittest.TestCase):
    def setUp(self):
        self.w = InventoryWatcher()

    def test_a_container_is_named_with_what_is_in_it(self):
        # mode 0x10000 is INTFACELOOT
        said = self.w.handle("INVEN:open 65536|Pot|3|2|")
        self.assertEqual(len(said), 1)
        self.assertIn("Pot", said[0])
        self.assertIn("3 items", said[0])
        self.assertIn("carrying 2 items", said[0])
        self.assertTrue(self.w.open)
        self.assertEqual(self.w.container, "Pot")

    def test_an_empty_container_still_says_so(self):
        """Silence and 'nothing in it' are different answers, and only one of
        them can be acted on."""
        said = self.w.handle("INVEN:open 65536|Pot|0|2|")
        self.assertIn("0 items", said[0])

    def test_your_own_inventory_names_no_container(self):
        # mode 0x1000 is INVENTORY
        said = self.w.handle("INVEN:open 4096||0|5|")
        self.assertIn("Inventory", said[0])
        self.assertIn("carrying 5 items", said[0])
        self.assertIsNone(self.w.container)

    def test_one_item_is_singular(self):
        said = self.w.handle("INVEN:open 65536|Footlocker|1|1|")
        self.assertIn("1 item.", said[0])
        self.assertNotIn("1 items", said[0])

    def test_closing_is_announced_once(self):
        self.w.handle("INVEN:open 65536|Pot|3|2|")
        self.assertEqual(self.w.handle("INVEN:close|"), ["Closed."])
        self.assertEqual(self.w.handle("INVEN:close|"), [])
        self.assertFalse(self.w.open)


class TestItems(unittest.TestCase):
    def setUp(self):
        self.w = InventoryWatcher()
        self.w.handle("INVEN:open 65536|Pot|3|2|")

    def test_an_item_says_where_it_is_in_the_list(self):
        said = self.w.handle(entry(SIDE_THEIRS, 0, 3, "Knife", count=1, weight=1))
        self.assertEqual(said, ["Knife, 1 pound. 1 of 3."])

    def test_a_stack_says_how_many(self):
        said = self.w.handle(entry(SIDE_THEIRS, 1, 3, "Bottle Caps", count=24))
        self.assertEqual(said, ["Bottle Caps, 24. 2 of 3."])

    def test_a_single_item_does_not_say_one(self):
        """A quantity of one on every item is noise on every item."""
        said = self.w.handle(entry(SIDE_MINE, 0, 2, "Rope", count=1))
        self.assertNotIn(", 1.", said[0])

    def test_weightless_items_say_nothing_about_weight(self):
        said = self.w.handle(entry(SIDE_MINE, 0, 2, "Bottle Caps", count=24, weight=0))
        self.assertNotIn("pound", said[0])

    def test_an_unnamed_entry_still_says_something(self):
        """Silence is the one answer that cannot be acted on -- it sounds
        exactly like the key not arriving, and was reported as exactly that
        when a bad item count invented three items the engine would not name."""
        said = self.w.handle(entry(SIDE_MINE, 1, 4, "", count=0, weight=0))
        self.assertEqual(said, ["Unnamed item. 2 of 4."])

    def test_the_last_thing_said_can_be_repeated(self):
        self.w.handle(entry(SIDE_THEIRS, 0, 3, "Knife", weight=1))
        self.assertEqual(self.w.repeat(), "Knife, 1 pound. 1 of 3.")

    def test_an_empty_list_says_so(self):
        self.assertEqual(self.w.handle("INVEN:none 1|"), ["Nothing there."])

    def test_an_empty_list_reads_as_a_place_you_can_stand(self):
        """Empty lists are reachable now -- an emptied carried list is exactly
        where an unequipped item has to go -- so each needs a sentence that
        works as a destination."""
        self.assertEqual(self.w.handle("INVEN:none 0|"), ["Carrying nothing."])
        self.assertEqual(self.w.handle("INVEN:none 2|"), ["Wearing nothing."])

    def test_an_empty_list_clears_the_selection(self):
        """Standing on an empty list, there is no item to pick up -- and the
        mover has to be able to tell that from a stale name left behind by the
        list the player just stepped off."""
        self.w.handle(entry(SIDE_MINE, 0, 1, "Spear"))
        self.w.handle("INVEN:none 0|")
        self.assertIsNone(self.w.selected)
        self.assertEqual(self.w.total, 0)


class TestWornSlots(unittest.TestCase):
    """The three fixed slots down the middle. An empty one is a real answer."""

    def setUp(self):
        self.w = InventoryWatcher()
        self.w.handle("INVEN:open 4096||0|5|")

    def test_a_worn_slot_leads_with_its_own_name(self):
        said = self.w.handle(entry(SIDE_WORN, 0, 3, "Leather Armor", slot=0))
        self.assertEqual(said, ["Armor, Leather Armor."])

    def test_an_empty_hand_is_announced_not_skipped(self):
        said = self.w.handle(entry(SIDE_WORN, 2, 3, "", count=0, slot=2))
        self.assertEqual(said, ["Item 2, empty."])

    def test_slots_are_named_in_window_order(self):
        self.assertEqual(
            self.w.handle(entry(SIDE_WORN, 1, 3, "Spear", slot=1)),
            ["Item 1, Spear."],
        )


class TestSummary(unittest.TestCase):
    def setUp(self):
        self.w = InventoryWatcher()

    def test_weight_is_reported_against_capacity(self):
        said = self.w.handle("INVEN:summary 4096|4|258|5|0|0|")
        self.assertIn("4 of 258 pounds", said[0])
        self.assertIn("Carrying 5 items", said[0])

    def test_a_container_is_included_when_there_is_one(self):
        said = self.w.handle("INVEN:summary 65536|4|258|5|3|0|")
        self.assertIn("3 items there", said[0])

    def test_action_point_cost_only_appears_in_a_fight(self):
        quiet = self.w.handle("INVEN:summary 4096|4|258|5|0|0|")
        self.assertNotIn("action", quiet[0])
        fighting = self.w.handle("INVEN:summary 4096|4|258|5|0|4|")
        self.assertIn("4 action points", fighting[0])


class TestNoise(unittest.TestCase):
    def test_diagnostics_are_never_spoken(self):
        w = InventoryWatcher()
        self.assertEqual(w.handle("INVEN:key 72 act 1|"), [])
        self.assertEqual(w.handle("INVEN:ready|"), [])

    def test_an_unparsable_line_is_silence_not_a_crash(self):
        """Every other reader here takes the same line: a line we do not
        understand is not a line to read out."""
        w = InventoryWatcher()
        self.assertEqual(w.handle("INVEN:entry garbage"), [])


class TestStateForMoving(unittest.TestCase):
    """What the item mover needs to know, gathered from the same lines that
    are spoken. Nothing extra is asked of the game for it."""

    def setUp(self):
        self.w = InventoryWatcher()
        self.w.handle("INVEN:open 65536|Pot|2|3|")

    def test_the_window_rectangle_is_remembered_and_not_spoken(self):
        said = self.w.handle("INVEN:rect 262|145|499|377|6|1024x768|")
        self.assertEqual(said, [])
        self.assertEqual(self.w.rect, (262, 145, 499, 377))

    def test_the_selection_is_tracked(self):
        self.w.handle(entry(SIDE_THEIRS, 1, 2, "Plastic Explosives", weight=5))
        self.assertEqual(self.w.side, SIDE_THEIRS)
        self.assertEqual(self.w.index, 1)
        self.assertEqual(self.w.total, 2)
        self.assertEqual(self.w.selected, "Plastic Explosives")

    def test_an_empty_worn_slot_selects_nothing(self):
        """There is no item to move out of an empty hand, and the mover has to
        be able to tell that from a selection it simply has not heard about."""
        self.w.handle(entry(SIDE_WORN, 2, 3, "", count=0, slot=2))
        self.assertIsNone(self.w.selected)

    def test_closing_forgets_the_window(self):
        self.w.handle("INVEN:rect 262|145|499|377|6|1024x768|")
        self.w.reset()
        self.assertIsNone(self.w.rect)
        self.assertIsNone(self.w.side)


if __name__ == "__main__":
    unittest.main()


class TestItemMenu(unittest.TestCase):
    """The map's action menu, for what you carry.

    Deliberately the same shape -- arrows move, Enter does it -- because it is
    the same idea, and a second set of habits to learn would be a worse answer
    than a slightly duller one. The contents differ in kind, though: the engine
    offers no action list for inventory items, so this list is the mod's own and
    can only ever hold what somebody thought of.
    """

    def test_opening_names_the_item_and_the_first_action(self):
        self.assertEqual(
            inventory.menu_line("INVEN:menu open|Plastic Explosives|2|use it|"),
            "Plastic Explosives. 2 actions. Use it, 1 of 2.")

    def test_moving_says_where_you_are(self):
        self.assertEqual(inventory.menu_line("INVEN:menu at|drop it|2|2|"),
                         "Drop it, 2 of 2.")

    def test_nothing_selected(self):
        self.assertEqual(inventory.menu_line("INVEN:menu none|"),
                         "Nothing selected.")

    def test_backing_out(self):
        self.assertEqual(inventory.menu_line("INVEN:menu closed|"), "Closed.")

    def test_an_item_that_went_away(self):
        self.assertEqual(inventory.menu_line("INVEN:menu gone|"),
                         "That item is no longer there.")

    def test_a_line_that_is_not_ours(self):
        self.assertIsNone(inventory.menu_line("INVEN:entry 0|0|1|Spear|1|4|-1|0|"))


class TestItemChoice(unittest.TestCase):
    """What Enter writes down for the Python side to carry out.

    It carries the side and index because the list cursor may have moved by the
    time anything acts on it, and whether the item is ACTIVE because "use it"
    ends in a click on the interface bar's item slot -- and that slot acts on
    the active item, attacking if a weapon is live.
    """

    def test_a_choice_parses(self):
        m = inventory._DO.match(
            "INVEN:do|use it|Plastic Explosives|2|1|3|1|")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "use it")
        self.assertEqual(m.group(2), "Plastic Explosives")
        self.assertEqual((m.group(3), m.group(4)), ("2", "1"))
        self.assertEqual(m.group(6), "1")

    def test_an_inactive_item_is_reported_as_such(self):
        m = inventory._DO.match("INVEN:do|drop it|Spear|2|2|3|0|")
        self.assertEqual(m.group(6), "0")
