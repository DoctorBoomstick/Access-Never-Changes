"""What the installer relies on: settings, language files, uninstall, launch.

None of it is the installer itself -- that is Inno Setup, built on GitHub
Actions -- but everything it calls is here, and is testable without it.
"""

import os
import tempfile
import unittest
from unittest import mock

import f2access
import install
from fallout2_access import config, paths


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class _Dir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()


class TestSettings(_Dir):
    def test_no_file_is_every_default(self):
        self.assertEqual(config.load(os.path.join(self.root, "none.ini")),
                         config.defaults())

    def test_the_shipped_file_reads_cleanly(self):
        """Every line of config/access.ini is a setting the mod understands."""
        problems = []
        shipped = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "config", "access.ini")
        settings = config.load(shipped, problems)
        self.assertEqual(problems, [])
        self.assertEqual(settings.speech, "auto")
        self.assertTrue(settings.exit_with_game)

    def test_values_and_notes_beside_them(self):
        path = os.path.join(self.root, "access.ini")
        write(path, "[speech]\nbackend = SAPI ; the windows voice\n"
                    "[general]\nstep_sound = no\nlanguage = German\n"
                    "[game]\nfolder = \"D:\\Games\\Fallout 2\"\n")
        s = config.load(path)
        self.assertEqual(s.speech, "sapi")
        self.assertFalse(s.step_sound)
        self.assertEqual(s.language, "german")
        self.assertEqual(s.game_folder, "D:\\Games\\Fallout 2")

    def test_a_typo_is_the_default_and_is_reported(self):
        path = os.path.join(self.root, "access.ini")
        write(path, "[speech]\nbackend = nvdaa\n[general]\nhotkeys = maybe\n")
        problems = []
        s = config.load(path, problems)
        self.assertEqual((s.speech, s.hotkeys), ("auto", True))
        self.assertEqual(len(problems), 2)

    def test_a_broken_file_is_every_default(self):
        path = os.path.join(self.root, "access.ini")
        write(path, "no section header at all\n")
        problems = []
        self.assertEqual(config.load(path, problems), config.defaults())
        self.assertEqual(len(problems), 1)


class TestWhereThingsAre(_Dir):
    def test_installed_inside_the_game(self):
        game = os.path.join(self.root, "Fallout 2")
        for marker in paths.GAME_MARKERS:
            write(os.path.join(game, marker), "")
        exe = os.path.join(game, "Access Never Changes", "AccessNeverChanges.exe")
        with mock.patch.object(paths.sys, "frozen", True, create=True), \
                mock.patch.object(paths.sys, "executable", exe):
            self.assertEqual(paths.app_dir(), os.path.dirname(exe))
            self.assertEqual(paths.lang_dir(),
                             os.path.join(os.path.dirname(exe), "lang"))
            self.assertEqual(paths.game_dir(), game)
            self.assertTrue(config.defaults().exit_with_game)

    def test_the_setting_wins(self):
        game = os.path.join(self.root, "elsewhere")
        for marker in paths.GAME_MARKERS:
            write(os.path.join(game, marker), "")
        self.assertEqual(paths.game_dir(game), game)


class TestUninstall(_Dir):
    def setUp(self):
        super().setUp()
        self.game = self.root
        for marker in install.GAME_MARKERS:
            write(os.path.join(self.game, marker), "")
        self.ddraw = os.path.join(self.game, "ddraw.ini")
        write(self.ddraw, "[Debugging]\nDebugMode=0\n[Misc]\nMode=4\n"
                          "SpeedMulti=100\n")
        write(os.path.join(self.game, "f2_res.ini"), "[MAIN]\nWINDOWED=0\n")
        write(os.path.join(self.game, "fallout2.cfg"),
              "[debug]\nshow_script_messages=0\n")
        build = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "build")
        self.assertTrue(all(os.path.exists(os.path.join(build, n))
                            for n in install.SCRIPTS))
        with mock.patch("builtins.print"):
            install.install(self.game, check_only=False, replace_config=False)

    def test_install_then_uninstall_puts_the_settings_back(self):
        self.assertIn("Mode=5", read(self.ddraw))
        with mock.patch("builtins.print"):
            self.assertEqual(install.uninstall(self.game), 0)
        text = read(self.ddraw)
        self.assertIn("DebugMode=0", text)
        self.assertIn("Mode=4", text)
        self.assertFalse(os.path.exists(self.ddraw + install.BACKUP_SUFFIX))
        for name in install.SCRIPTS:
            self.assertFalse(os.path.exists(
                os.path.join(self.game, "data", "scripts", name)))

    def test_what_the_player_changed_since_is_kept(self):
        text = read(self.ddraw).replace("SpeedMulti=100", "SpeedMulti=250")
        write(self.ddraw, text)
        with mock.patch("builtins.print"):
            install.uninstall(self.game)
        self.assertIn("SpeedMulti=250", read(self.ddraw))

    def test_the_installer_subcommand(self):
        with mock.patch("builtins.print"), \
                mock.patch.object(f2access, "_Tee", lambda stream, path: stream), \
                mock.patch.object(f2access.sys, "stdout"), \
                mock.patch.object(f2access.sys, "stderr"):
            self.assertEqual(f2access.main(["uninstall", self.game]), 0)
        self.assertIn("DebugMode=0", read(self.ddraw))


class _App:
    def __init__(self):
        self.up = False

    def _connected(self):
        return self.up


class _Launched:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


class TestStoppingWithTheGame(unittest.TestCase):
    def setUp(self):
        self.now = [0.0]
        self.app, self.launched = _App(), _Launched()
        self.until = f2access.StopWhenGameCloses(
            self.app, self.launched, grace=90, clock=lambda: self.now[0])

    def test_waits_for_the_game_then_goes_with_it(self):
        self.assertFalse(self.until())
        self.app.up = True
        self.assertFalse(self.until())
        self.app.up = False
        self.assertTrue(self.until())

    def test_a_launcher_stub_exiting_is_not_the_game_closing(self):
        self.launched.code = 0
        self.now[0] = 30
        self.assertFalse(self.until())
        self.app.up = True
        self.assertFalse(self.until())

    def test_a_game_that_never_arrives_is_given_up_on(self):
        self.launched.code = 1
        self.now[0] = 91
        self.assertTrue(self.until())


if __name__ == "__main__":
    unittest.main()
