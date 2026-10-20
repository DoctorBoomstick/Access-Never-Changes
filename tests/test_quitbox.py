"""Control and X over the map: the engine's quit box, which was silent."""

import time
import unittest
from unittest import mock

from fallout2_access import app as appmod
from fallout2_access.game import screens


class _Ann:
    def __init__(self):
        self.said = []

    def answer(self, text):
        self.said.append(text)


class _Box:
    def __init__(self, buttons=2, addr=0x100):
        self.buttons = [object()] * buttons
        self.addr, self.width, self.height = addr, 300, 90


class _Inventory:
    open = False


class _World:
    inventory = _Inventory()

    def talking(self):
        return False


class TestQuitBox(unittest.TestCase):
    def setUp(self):
        self.app = appmod.App.__new__(appmod.App)
        self.app.ann = _Ann()
        self.app.proc = object()
        self.app.world = _World()
        self.app.screen = screens.WORLD
        self.box = None
        patcher = mock.patch.object(appmod.slotscreen, "confirm_box",
                                    lambda proc: self.box)
        patcher.start()
        self.addCleanup(patcher.stop)
        quit_q = mock.patch.object(appmod.pausemenu, "quit_question",
                                   lambda proc: "Are you sure you want to quit?")
        quit_q.start()
        self.addCleanup(quit_q.stop)

    def test_control_x_names_the_question(self):
        self.app.quit_key_at = time.time()
        self.box = _Box()
        self.app._watch_box()
        self.app._watch_box()
        self.assertEqual(self.app.ann.said, [
            "Are you sure you want to quit? Y or Enter for yes, N or Escape for no."])

    def test_another_box_is_called_a_question(self):
        self.box = _Box()
        self.app._watch_box()
        self.assertIn("cannot read", self.app.ann.said[0])

    def test_no_box_says_nothing(self):
        self.app._watch_box()
        self.assertEqual(self.app.ann.said, [])


class TestLoadFromTheMainMenu(unittest.TestCase):
    """The main menu never leads straight to the editor, so a reading that
    says it did has to hold for longer before it is believed."""

    def test_menu_to_editor_waits(self):
        app = appmod.App.__new__(appmod.App)
        app.screen = screens.MAIN_MENU
        self.assertGreater(app._ticks_to_believe(screens.CHARGEN),
                           appmod.SCREEN_STABLE_TICKS)
        app.screen = screens.SELECT
        self.assertEqual(app._ticks_to_believe(screens.CHARGEN),
                         appmod.SCREEN_STABLE_TICKS)


if __name__ == "__main__":
    unittest.main()
