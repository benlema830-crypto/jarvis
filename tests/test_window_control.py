import unittest
from unittest import mock
import win32con
import window_control as wc


class WindowControlTest(unittest.TestCase):
    monitors = [(1, {"Device": r"\\.\DISPLAY1", "Flags": 0, "Monitor": (-2560, 0, 0, 1440), "Work": (-2560, 0, 0, 1400)}),
                (2, {"Device": r"\\.\DISPLAY2", "Flags": 1, "Monitor": (0, 0, 2560, 1440), "Work": (0, 0, 2560, 1400)})]
    windows = [{"id": 10, "title": "Rocket Frontier - Roblox Studio", "process": "RobloxStudioBeta.exe"}]

    def test_second_means_nonprimary_not_display_number(self):
        self.assertEqual(wc.choose_monitor(self.monitors, "secondary")[0], 1)
        self.assertEqual(wc.choose_monitor(self.monitors, "second")[0], 1)
        self.assertEqual(wc.choose_monitor(self.monitors, "DISPLAY2")[0], 2)

    def test_negative_coordinates_and_work_area(self):
        self.assertEqual(wc.fit_rect((0, 0, 3000, 2000), (-2560, 0, 0, 1400)), (-2560, 0, 2560, 1400))

    def test_studio_matches_process_and_ambiguity_is_not_guessed(self):
        self.assertEqual(wc.choose_window(self.windows, "roblox studios", 99)["id"], 10)
        items = self.windows + [{"id": 11, "title": "Other - Roblox Studio", "process": "RobloxStudioBeta.exe"}]
        with self.assertRaisesRegex(ValueError, "Several"):
            wc.choose_window(items, "Roblox Studio", 99)
        self.assertEqual(wc.choose_window(items, "Roblox Studio", 11)["id"], 11)

    def run_move(self, monitor_results):
        with mock.patch.object(wc, "windows", return_value=self.windows), \
             mock.patch.object(wc, "monitors", return_value=self.monitors), \
             mock.patch.object(wc.win32gui, "GetForegroundWindow", return_value=99), \
             mock.patch.object(wc.win32gui, "IsWindow", return_value=True), \
             mock.patch.object(wc.worksafe, "is_blocked", return_value=False), \
             mock.patch.object(wc.win32gui, "GetWindowPlacement", return_value=(0, win32con.SW_SHOWMAXIMIZED, (), (), ())), \
             mock.patch.object(wc.win32gui, "GetWindowRect", return_value=(0, 0, 1000, 800)), \
             mock.patch.object(wc.win32gui, "ShowWindow") as show, \
             mock.patch.object(wc.win32gui, "SetWindowPos") as position, \
             mock.patch.object(wc.win32api, "MonitorFromWindow", side_effect=monitor_results), \
             mock.patch.object(wc.time, "sleep"):
            result = wc.move("Roblox Studio")
            return result, show, position

    def test_move_restores_then_remaximizes_and_verifies(self):
        result, show, position = self.run_move([2, 1])
        self.assertIn("moved", result)
        self.assertLess(position.call_args.args[2], 0)
        self.assertEqual(show.call_args_list, [mock.call(10, win32con.SW_RESTORE), mock.call(10, win32con.SW_MAXIMIZE)])

    def test_failed_move_never_reports_success(self):
        with self.assertRaisesRegex(RuntimeError, "did not move"):
            self.run_move([2] * 11)

    def test_missing_secondary_is_explicit(self):
        with self.assertRaises(ValueError):
            wc.choose_monitor(self.monitors[1:], "secondary")
