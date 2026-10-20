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
    SIDE_MY_OFFER,
    side_names,
    SIDE_THEIRS,
    SIDE_THEIR_OFFER,
    SIDE_WORN,
    InventoryWatcher,
)


def entry(side, index, total, name, count=1, weight=0, slot=-1,
          addr=None, ammo=None, capacity=None):
    """One INVEN:entry line, in either the old shape or the new one.

    The address and the ammunition fields were both appended rather than
    inserted, so a game running last session's compiled script still emits the
    short form. Both are produced here for the same reason: the reader has to
    keep working on either.
    """
    line = "INVEN:entry {}|{}|{}|{}|{}|{}|{}|".format(
        side, index, total, name, count, weight, slot
    )
    if addr is None and ammo is None:
        return line
    line += "{}|".format(addr if addr is not None else 0)
    if ammo is not None:
        line += "{}|{}|".format(ammo, capacity if capacity is not None else 0)
    return line


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


class TestAmmunitionIsCarriedButNotSpoken(unittest.TestCase):
    """The listing line stays as it was, whatever the script now sends.

    Saying what each gun in the pack holds was built and taken straight back
    out. `:` is the key for that question, and repeating the answer on every
    listing line adds words to the one place a player steps quickly -- in a
    sentence the mod would have to translate itself, where `:` quotes the game.

    The fields are still parsed, because what a reload actually did has to be
    read from the engine rather than assumed from a click. They are just never
    said.
    """

    def setUp(self):
        self.w = InventoryWatcher()
        self.w.handle("INVEN:open 4096||0|5|")

    def test_a_loaded_gun_reads_the_same_as_any_other_item(self):
        with_ammo = self.w.handle(entry(SIDE_MINE, 0, 3, "Pipe Rifle",
                                        weight=11, ammo=6, capacity=10))
        without = self.w.handle(entry(SIDE_MINE, 0, 3, "Pipe Rifle",
                                      weight=11))
        self.assertEqual(with_ammo, without)

    def test_an_empty_gun_is_not_called_empty(self):
        """"Empty" already means an empty worn slot on this screen, and a gun
        with no rounds is a different thing entirely."""
        said = self.w.handle(entry(SIDE_MINE, 0, 3, "Pipe Rifle", weight=11,
                                   ammo=0, capacity=10))
        self.assertNotIn("empty", said[0])

    def test_a_gun_in_a_hand_reads_as_the_slot_and_the_name(self):
        self.assertEqual(
            self.w.handle(entry(SIDE_WORN, 1, 3, "Pipe Rifle", slot=1,
                                ammo=6, capacity=10)),
            ["Item 1, Pipe Rifle."],
        )

    def test_the_previous_script_still_lists_an_inventory(self):
        """Appended, not inserted: a game running last session's compiled
        script has to keep working rather than fail to match and go silent."""
        said = self.w.handle(entry(SIDE_MINE, 0, 3, "Pipe Rifle", weight=11))
        self.assertIn("Pipe Rifle", said[0])

    def test_the_address_alone_is_still_understood(self):
        said = self.w.handle(entry(SIDE_MINE, 0, 3, "Pipe Rifle", weight=11,
                                   addr=178400960))
        self.assertIn("Pipe Rifle", said[0])


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


class TestBarterPrices(unittest.TestCase):
    """The two totals the barter screen prints.

    They are the whole game of bartering -- you add items until the piles
    balance -- and they were the one thing the mod could not say. They are also
    **not stored anywhere**: that was established by moving an item and
    comparing every four-byte value in the executable's static data before and
    after, and finding nothing. The engine works them out inside the routine
    that draws them and keeps neither.

    So they come from sfall's barter-price hook, which runs inside that
    calculation. The numbers here are the engine's, not this mod's arithmetic --
    which matters, because a total the mod computed could disagree with the one
    on screen and a player who cannot see the screen could not catch it.
    """

    def setUp(self):
        self.inv = InventoryWatcher()

    def price(self, asking, offering, caps=0, before=0):
        return self.inv.handle("INVEN:price {}|{}|{}|{}|"
                               .format(asking, offering, caps, before))

    def test_both_totals_are_said_together(self):
        """The question is never what one pile is worth, it is whether they
        balance -- and that is a comparison."""
        said = self.price(120, 40)
        self.assertEqual(len(said), 1)
        self.assertIn("120", said[0])
        self.assertIn("40", said[0])

    def test_it_says_how_far_short_you_are(self):
        """Working that out from two figures read a second apart is exactly
        the arithmetic this is meant to save."""
        self.assertIn("80 short", self.price(120, 40)[0])

    def test_it_says_when_the_offer_is_enough(self):
        self.assertIn("Enough", self.price(120, 120)[0])
        self.assertIn("Enough", self.price(120, 200)[0])

    def test_an_unchanged_price_is_not_repeated(self):
        """The hook fires twice on entry and again on every change, so it
        speaks far more often than it has anything new to say."""
        self.assertTrue(self.price(120, 40))
        self.assertEqual(self.price(120, 40), [])
        self.assertEqual(self.price(120, 40), [])

    def test_a_changed_price_is_said_again(self):
        self.price(120, 40)
        self.assertTrue(self.price(120, 90))

    def test_clearing_the_table_says_so_rather_than_reading_two_zeroes(self):
        self.price(120, 40)
        self.assertEqual(self.price(0, 0), ["Nothing on the table."])

    def test_the_first_reading_of_an_empty_table_is_still_reported(self):
        """Entering a barter with nothing on the table should not be silent --
        silence is indistinguishable from the hook never having fired."""
        said = self.price(0, 0)
        self.assertEqual(len(said), 1)

    def test_closing_forgets_the_price(self):
        """Otherwise the next barter opens by comparing against the last one
        and says nothing at all."""
        self.price(120, 40)
        self.inv.handle("INVEN:close|")
        self.assertIsNone(self.inv.price)
        self.assertTrue(self.price(120, 40))


class TestBarterSides(unittest.TestCase):
    """The barter window has four item lists, and the mod knew about two.

    You could hear everything for sale and never find out what you had put on
    the table, which is why it read out perfectly and was unplayable.
    """

    def test_the_two_offer_lists_have_names(self):
        for side in (SIDE_MY_OFFER, SIDE_THEIR_OFFER):
            with self.subTest(side=side):
                self.assertIn(side, side_names())
                self.assertTrue(side_names()[side])

    def test_the_offer_lists_are_distinct_from_the_inventories(self):
        names = [side_names()[s] for s in
                 (SIDE_MINE, SIDE_THEIRS, SIDE_WORN, SIDE_MY_OFFER,
                  SIDE_THEIR_OFFER)]
        self.assertEqual(len(names), len(set(names)))

    def test_an_empty_offer_reads_as_a_destination_not_a_complaint(self):
        """It is where an item goes when you put it on the table."""
        inv = InventoryWatcher()
        said = inv.handle("INVEN:none {}|".format(SIDE_MY_OFFER))
        self.assertEqual(said, ["You are offering nothing."])
        said = inv.handle("INVEN:none {}|".format(SIDE_THEIR_OFFER))
        self.assertEqual(said, ["They are offering nothing."])


class TestTheOffer(unittest.TestCase):
    """What became of a trade, read from the engine rather than from the click.

    sfall's barter-price hook fires again the moment an offer is made, with a
    flag saying that is what caused it. **An empty table afterwards is the
    acceptance**: the engine clears both sides when the goods change hands and
    leaves them untouched when the shopkeeper says no. So the outcome is read
    out of what the engine did, not out of what the mod asked for -- which
    matters here more than usual, because a click was sent and reporting a
    trade because a click was sent is exactly the claim this project refuses.
    """

    def setUp(self):
        self.inv = InventoryWatcher()

    def price(self, asking, offering, offered=0):
        return self.inv.handle("INVEN:price {}|{}|0|0|{}|0|"
                               .format(asking, offering, offered))

    def test_making_an_offer_is_announced_with_the_figures(self):
        self.price(90, 52)
        said = self.price(90, 52, offered=1)
        self.assertIn("Offered", said[0])
        self.assertIn("90", said[0])
        self.assertIn("52", said[0])

    def test_an_accepted_trade_names_both_sides(self):
        self.price(90, 52)
        self.price(90, 52, offered=1)
        self.assertEqual(self.price(0, 0),
                         ["Traded. You gave 52 and took 90."])

    def test_a_refusal_is_not_reported_as_a_trade(self):
        """The tables stay exactly as they were, which is the tell."""
        self.price(90, 10)
        self.price(90, 10, offered=1)
        said = self.price(90, 10)
        self.assertEqual(said, ["They would not take that."])
        self.assertNotIn("Traded", said[0])

    def test_giving_something_for_nothing_says_so(self):
        """Legal, and not usually a thing anyone means to do."""
        self.price(0, 52)
        self.price(0, 52, offered=1)
        self.assertEqual(self.price(0, 0),
                         ["Traded. You gave 52 for nothing."])

    def test_the_offer_state_does_not_survive_the_window_closing(self):
        self.price(90, 52)
        self.price(90, 52, offered=1)
        self.inv.handle("INVEN:close|")
        self.assertIsNone(self.inv.offered)

    def test_a_script_without_the_new_fields_still_reports_prices(self):
        """A regex that demanded them would not lose the offer flag, it would
        fail to match and take the prices with it."""
        said = self.inv.handle("INVEN:price 10|20|0|5|")
        self.assertEqual(len(said), 1)
        self.assertIn("Enough", said[0])


class TestBarterValues(unittest.TestCase):
    """What things are worth, before they go on the table and after."""

    def _barter(self):
        w = InventoryWatcher()
        w.handle("INVEN:open 131076|Maida|16|18|")
        return w

    def test_a_row_says_what_one_is_worth_while_trading(self):
        w = self._barter()
        said = w.handle("INVEN:entry 0|7|15|Stimpak|2|0|-1|10516288|-1|0|175|")
        self.assertIn("worth 175 each", said[0])

    def test_not_off_the_barter_screen(self):
        w = InventoryWatcher()
        w.handle("INVEN:open 4096||0|15|")
        said = w.handle("INVEN:entry 0|7|15|Stimpak|2|0|-1|10516288|-1|0|175|")
        self.assertNotIn("worth", said[0])

    def test_last_sessions_script_still_reads(self):
        """A row without the value field is still a row."""
        w = self._barter()
        said = w.handle("INVEN:entry 0|7|15|Stimpak|2|0|-1|10516288|-1|0|")
        self.assertIn("Stimpak", said[0])

    def test_giving_caps_for_nothing_is_asked_about(self):
        w = self._barter()
        w.handle("INVEN:price 0|457|0|0|0|0|")
        self.assertEqual(w.lopsided(), "You are offering 457 for nothing.")

    def test_a_fair_trade_goes_straight_through(self):
        w = self._barter()
        w.handle("INVEN:price 180|160|180|180|0|0|")
        self.assertIsNone(w.lopsided())

    def test_paying_double_is_asked_about(self):
        w = self._barter()
        w.handle("INVEN:price 50|457|50|50|0|0|")
        self.assertEqual(w.lopsided(),
                         "You are offering 457 for goods worth 50.")

    def test_a_companion_is_not_asked_about(self):
        w = self._barter()
        w.handle("INVEN:price 0|457|0|0|0|1|")
        self.assertIsNone(w.lopsided())

    def test_the_totals_can_be_asked_for(self):
        w = self._barter()
        w.handle("INVEN:price 180|160|180|180|0|0|")
        self.assertEqual(w.totals(),
                         "They want 180. You are offering 160. 20 short.")


class TestAmmunitionBoxesAndRounds(unittest.TestCase):
    """Sajag's 10mm JHP: four boxes, 96 rounds, 75 a box.

    The line used to carry the top box's rounds as the count, and said "24" --
    which sounds like a box of 24 and was four of them. The barter hook valued
    them at 300, four times 75, which is how it came out.
    """

    LINE = "INVEN:entry 1|0|12|10mm JHP|4|1|-1|11693480|-1|0|75|96|"

    def test_both_numbers_are_said(self):
        said = InventoryWatcher().handle(self.LINE)
        self.assertIn("4 boxes, 96 rounds", said[0])

    def test_one_box_is_just_its_rounds(self):
        said = InventoryWatcher().handle(
            "INVEN:entry 0|3|9|10mm JHP|1|1|-1|1|-1|0|75|23|")
        self.assertIn("10mm JHP, 23 rounds", said[0])
        self.assertNotIn("box", said[0])

    def test_the_price_is_a_box(self):
        w = InventoryWatcher()
        w.handle("INVEN:open 131076|Sajag|12|18|")
        said = w.handle(self.LINE)
        self.assertIn("worth 75 a box", said[0])

    def test_the_count_kept_for_moving_is_boxes(self):
        """The "Move Items" window counts boxes, so its maximum is four."""
        w = InventoryWatcher()
        w.handle(self.LINE)
        self.assertEqual(w.selected_count, 4)

    def test_not_ammunition_is_unchanged(self):
        said = InventoryWatcher().handle(
            "INVEN:entry 1|1|12|Money|203|0|-1|1|-1|0|1|-1|")
        self.assertIn("Money, 203", said[0])
        self.assertNotIn("round", said[0])


class TestTheCountOfWhatIsMoving(unittest.TestCase):
    """A move is two presses; by the second the cursor is on the destination."""

    def test_the_dragged_count_survives_the_cursor_moving(self):
        w = InventoryWatcher()
        w.handle("INVEN:entry 1|0|11|Money|203|0|-1|1|-1|0|1|-1|")
        w.start_moving(w.selected_count, now=100.0)
        w.handle("INVEN:entry 4|0|1|10mm JHP|4|1|-1|2|-1|0|75|96|")
        self.assertEqual(w.moving(now=101.0), 203)
        # Asked twice, as the window's watcher does on the way in.
        self.assertEqual(w.moving(now=101.5), 203)

    def test_an_old_drag_sizes_nothing(self):
        w = InventoryWatcher()
        w.start_moving(203, now=100.0)
        self.assertIsNone(w.moving(now=100.0 + w.MOVING_FOR + 1))

    def test_closing_forgets_it(self):
        w = InventoryWatcher()
        w.start_moving(203, now=100.0)
        w.reset()
        self.assertIsNone(w.moving(now=100.5))


if __name__ == "__main__":
    unittest.main()
