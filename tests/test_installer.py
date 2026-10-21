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


class TestMashExe(_Dir):
    """The installer makes sfall's own hi-res change to fallout2.exe."""

    def setUp(self):
        super().setUp()
        self.exe = os.path.join(self.root, "fallout2.exe")
        self.hrp = bytes(range(256)) * 0x1000
        plain = bytearray(self.hrp)
        for offset, new in install.HRP_UNDO:
            plain[offset:offset + len(new)] = new
        self.plain = bytes(plain)
        self.hashes = mock.patch.multiple(
            install,
            HRP_EXE_SHA256=install.hashlib.sha256(self.hrp).hexdigest(),
            PLAIN_EXE_SHA256=install.hashlib.sha256(self.plain).hexdigest())
        self.hashes.start()
        self.quiet = mock.patch("builtins.print")
        self.quiet.start()

    def tearDown(self):
        self.quiet.stop()
        self.hashes.stop()
        super().tearDown()

    def exe_bytes(self):
        with open(self.exe, "rb") as fh:
            return fh.read()

    def write_exe(self, data):
        with open(self.exe, "wb") as fh:
            fh.write(data)

    def test_rpu_exe_is_switched_and_kept(self):
        self.write_exe(self.hrp)
        install.undo_mash_exe(self.root, check_only=False)
        self.assertEqual(self.exe_bytes(), self.plain)
        with open(self.exe + install.BACKUP_SUFFIX, "rb") as fh:
            self.assertEqual(fh.read(), self.hrp)

    def test_check_only_changes_nothing(self):
        self.write_exe(self.hrp)
        install.undo_mash_exe(self.root, check_only=True)
        self.assertEqual(self.exe_bytes(), self.hrp)

    def test_an_unknown_exe_is_left_alone(self):
        self.write_exe(b"something else")
        install.undo_mash_exe(self.root, check_only=False)
        self.assertEqual(self.exe_bytes(), b"something else")
        self.assertFalse(os.path.exists(self.exe + install.BACKUP_SUFFIX))

    def test_uninstall_puts_it_back(self):
        self.write_exe(self.hrp)
        install.undo_mash_exe(self.root, check_only=False)
        self.assertEqual(install.restore_mash_exe(self.root), 0)
        self.assertEqual(self.exe_bytes(), self.hrp)
        self.assertFalse(os.path.exists(self.exe + install.BACKUP_SUFFIX))

    def test_uninstall_leaves_an_exe_changed_since(self):
        self.write_exe(self.hrp)
        install.undo_mash_exe(self.root, check_only=False)
        self.write_exe(b"patched by something else")
        install.restore_mash_exe(self.root)
        self.assertEqual(self.exe_bytes(), b"patched by something else")


# sfall's own rename of RPU's exe, where a machine has one: the real bytes
# against the real hashes, which the fake exe above cannot check.
_RPU_EXE = r"C:\Program Files (x86)\Steam\steamapps\common\Fallout 2\fallout2HR.exe"


class TestRealMashExe(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(_RPU_EXE), "no RPU fallout2HR.exe here")
    def test_the_bytes_give_the_plain_game(self):
        with open(_RPU_EXE, "rb") as fh:
            data = bytearray(fh.read())
        if install.hashlib.sha256(data).hexdigest() != install.HRP_EXE_SHA256:
            self.skipTest("fallout2HR.exe here is not RPU's")
        for offset, new in install.HRP_UNDO:
            data[offset:offset + len(new)] = new
        self.assertEqual(install.hashlib.sha256(data).hexdigest(),
                         install.PLAIN_EXE_SHA256)


class TestHandOverOnRestart(unittest.TestCase):
    class _Waits:
        def wait(self):
            return 0

    def handed(self, hwnd):
        app, calls = mock.Mock(hwnd=hwnd), []
        with mock.patch("builtins.print"):
            f2access.hand_over_again_on_restart(
                self._Waits(), app, hand_over=lambda: calls.append(1)).join(2)
        return bool(calls)

    def test_a_game_gone_before_its_window_is_handed_over(self):
        self.assertTrue(self.handed(None))

    def test_a_game_that_was_played_and_closed_is_not(self):
        self.assertFalse(self.handed(1234))


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
        self.assertFalse(self.until())          # it may be restarting
        self.now[0] += 21
        self.assertTrue(self.until())

    def test_a_game_that_restarts_is_followed(self):
        """sfall restarts the game on a first launch; the mod must not leave."""
        self.app.up = True
        self.until()
        self.app.up = False
        self.now[0] += 5
        self.assertFalse(self.until())
        self.app.up = True
        self.assertFalse(self.until())
        self.app.up = False
        self.now[0] += 5
        self.assertFalse(self.until())

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
