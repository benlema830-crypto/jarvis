import base64
import io
import unittest
from unittest import mock

from PIL import Image

import agent
import desktop
import worksafe


LEFT_AND_PRIMARY = desktop.Layout((
    desktop.Monitor("DISPLAY1", (-2560, 0, 0, 1440)),
    desktop.Monitor("DISPLAY2", (0, 0, 2560, 1440), True),
))


def computer():
    result = agent.Agent.__new__(agent.Agent)
    result.layout = LEFT_AND_PRIMARY
    result.shot_size = LEFT_AND_PRIMARY.shot_size(agent.SHOT_LONG_EDGE)
    result.log = []
    return result


class GeometryTest(unittest.TestCase):
    def test_left_monitor_coordinates_and_round_trip(self):
        layout = LEFT_AND_PRIMARY
        shot = layout.shot_size(1456)
        self.assertEqual(layout.size, (5120, 1440))
        self.assertEqual(shot, (1456, 410))
        self.assertEqual(layout.to_native((364, 205), shot), (-1280, 720))
        self.assertEqual(layout.to_native((1092, 205), shot), (1280, 720))
        self.assertEqual(layout.to_shot((-1280, 720), shot), (364, 205))

    def test_monitor_above_primary_with_different_resolution(self):
        layout = desktop.Layout((desktop.Monitor("upper", (0, -1080, 1920, 0)),
                                 desktop.Monitor("primary", (0, 0, 2560, 1440), True)))
        shot = layout.shot_size(2560)
        self.assertEqual(layout.to_native((960, 540), shot), (960, -540))
        self.assertEqual(layout.to_shot((1280, 720), shot), (1280, 1800))
        self.assertFalse(layout.contains(2200, -500))

    def test_invalid_coordinates_and_zoom_edges(self):
        layout = LEFT_AND_PRIMARY
        shot = layout.shot_size(1456)
        for coord in ((-1, 0), (1456, 5), (float("nan"), 1)):
            with self.assertRaises(ValueError):
                layout.to_native(coord, shot)
        self.assertEqual(layout.to_native(shot, shot, edge=True), (2560, 1440))


class CaptureTest(unittest.TestCase):
    def test_full_desktop_masks_protected_windows_on_both_monitors(self):
        rects = [(-2300, 100, -2000, 400), (200, 100, 500, 400)]
        with mock.patch.object(desktop, "current_layout", return_value=LEFT_AND_PRIMARY), \
             mock.patch("PIL.ImageGrab.grab", return_value=Image.new("RGB", (5120, 1440), "white")) as grab, \
             mock.patch.object(worksafe, "blocked_rects", return_value=rects):
            image = worksafe.grab()
        grab.assert_called_once_with(bbox=(-2560, 0, 2560, 1440), all_screens=True)
        self.assertEqual(image.getpixel((400, 250)), (0, 0, 0))
        self.assertEqual(image.getpixel((2900, 250)), (0, 0, 0))
        self.assertEqual(image.getpixel((2000, 700)), (255, 255, 255))

    def test_negative_origin_crop_masks_correctly_and_ignores_offscreen_windows(self):
        with mock.patch("PIL.ImageGrab.grab", return_value=Image.new("RGB", (500, 400), "white")) as grab, \
             mock.patch.object(worksafe, "blocked_rects", return_value=[(-2300, 100, -2000, 400), (100, 0, 600, 600)]):
            image = worksafe.grab((-2400, 50, -1900, 450))
        grab.assert_called_once_with(bbox=(-2400, 50, -1900, 450), all_screens=True)
        self.assertEqual(image.getpixel((200, 200)), (0, 0, 0))
        self.assertEqual(image.getpixel((10, 10)), (255, 255, 255))

    def test_agent_screenshot_has_full_desktop_aspect_ratio(self):
        instance = computer()
        with mock.patch.object(desktop, "current_layout", return_value=LEFT_AND_PRIMARY), \
             mock.patch.object(worksafe, "grab", return_value=Image.new("RGB", (5120, 1440))) as grab:
            result = instance._screenshot()
        grab.assert_called_once_with(LEFT_AND_PRIMARY.bounds)
        image = Image.open(io.BytesIO(base64.b64decode(result[0]["source"]["data"])))
        self.assertEqual(image.size, (1456, 410))


class MouseTest(unittest.TestCase):
    def setUp(self):
        self.computer = computer()
        patch = mock.patch.object(desktop, "current_layout", return_value=LEFT_AND_PRIMARY)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(agent.hud, "emit")
        patch.start()
        self.addCleanup(patch.stop)

    def test_click_goes_to_negative_windows_coordinate(self):
        with mock.patch.object(worksafe, "point_blocked", return_value=False), \
             mock.patch.object(agent.pyautogui, "click") as click:
            self.computer._computer("left_click", {"coordinate": [364, 205]})
        click.assert_called_once_with(-1280, 720, button="left")

    def test_protected_app_on_left_monitor_is_not_clicked(self):
        with mock.patch.object(worksafe, "point_blocked", return_value=True) as blocked, \
             mock.patch.object(agent.pyautogui, "click") as click:
            with self.assertRaises(agent.Blocked):
                self.computer._computer("left_click", {"coordinate": [364, 205]})
        blocked.assert_called_once_with(-1280, 720)
        click.assert_not_called()

    def test_layout_change_prevents_click(self):
        new_layout = desktop.Layout((desktop.Monitor("primary", (0, 0, 2560, 1440), True),))
        with mock.patch.object(desktop, "current_layout", return_value=new_layout), \
             mock.patch.object(agent.pyautogui, "click") as click:
            with self.assertRaisesRegex(RuntimeError, "Monitor layout changed"):
                self.computer._computer("left_click", {"coordinate": [364, 205]})
        click.assert_not_called()

    def test_zoom_and_cursor_share_full_desktop_coordinates(self):
        with mock.patch.object(self.computer, "_screenshot", return_value=[]) as screenshot:
            self.computer._computer("zoom", {"region": [0, 0, 728, 410]})
        screenshot.assert_called_once_with(bbox=(-2560, 0, 0, 1440))
        with mock.patch.object(agent.pyautogui, "position", return_value=(-1280, 720)):
            self.assertEqual(self.computer._computer("cursor_position", {})[0]["text"], "(364, 205)")

    def test_monitor_gap_is_not_clickable(self):
        layout = desktop.Layout((desktop.Monitor("left", (-2560, -1440, 0, 0)),
                                 desktop.Monitor("primary", (0, 0, 2560, 1440), True)))
        self.computer.layout = layout
        with mock.patch.object(desktop, "current_layout", return_value=layout):
            with self.assertRaisesRegex(ValueError, "gap"):
                self.computer._check_point(-500, 500)

    def test_emergency_stop_corners_cover_both_monitors(self):
        with mock.patch.object(agent.pyautogui, "FAILSAFE_POINTS", []):
            self.computer._configure_screen()
            self.assertIn((-2560, 0), agent.pyautogui.FAILSAFE_POINTS)
            self.assertIn((2559, 1439), agent.pyautogui.FAILSAFE_POINTS)
