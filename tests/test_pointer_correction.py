"""Aiming at a panel: correct the quick reader, don't throw it away.

Moving a stack onto a barter table took nine seconds. The quick reader drifts
low on the screen, the game disagreed with it, and the whole aim was handed to
the slow servo at a second a step. Its drift is close to a fixed offset near
the target, so one correction lands it.
"""

import unittest

from fallout2_access.game import pointer


class TestCorrection(unittest.TestCase):

    def _run(self, drift):
        aimed = []
        truth_readers = []

        def fake_aim_to(proc, hwnd, x, y, tolerance=2, log_path=None, reader=None):
            aimed.append((x, y, type(reader).__name__))
            return True, (x, y), ""

        class FakeTruth:
            def __init__(self, hwnd, log_path):
                truth_readers.append(self)

            def read(self, timeout=0.6):
                x, y, _ = aimed[-1]
                return x + drift[0], y + drift[1]

        saved = (pointer.aim_to, pointer.ScriptMouse, pointer.MenuMouse)
        try:
            pointer.aim_to = fake_aim_to
            pointer.ScriptMouse = FakeTruth
            pointer.MenuMouse = lambda proc: object()
            result = pointer.aim_ui(None, 1, 200, 400, log_path="x.log")
        finally:
            pointer.aim_to, pointer.ScriptMouse, pointer.MenuMouse = saved
        return result, aimed

    def test_a_steady_drift_is_corrected_in_one_go(self):
        (ok, where, _), aimed = self._run((0, 12))
        self.assertTrue(ok)
        self.assertEqual(where, (200, 400))
        self.assertEqual([a[:2] for a in aimed], [(200, 400), (200, 388)])
        self.assertNotIn("FakeTruth", [a[2] for a in aimed])

    def test_no_drift_needs_no_correction(self):
        (ok, _where, _), aimed = self._run((0, 0))
        self.assertTrue(ok)
        self.assertEqual(len(aimed), 1)


if __name__ == "__main__":
    unittest.main()
