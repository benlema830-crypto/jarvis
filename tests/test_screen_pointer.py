import time
import unittest
from unittest import mock

import screen_pointer as pointer

DESKTOP = (-2560, 0, 2560, 1440)   # two monitors side by side, the left one at negative x


class ScreenPointerTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(pointer, "_look", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_point_in_the_screenshot_maps_onto_the_real_desktop(self):
        pointer.remember_look((1600, 450), DESKTOP)
        self.assertEqual(pointer.to_native(0, 0), (-2560, 0))
        self.assertEqual(pointer.to_native(800, 225), (0, 720))
        self.assertEqual(pointer.to_native(1600, 450), (2560, 1440))

    def test_a_window_screenshot_maps_into_that_window(self):
        pointer.remember_look((800, 600), (100, 200, 900, 800))
        self.assertEqual(pointer.to_native(400, 300), (500, 500))

    def test_pointing_needs_a_recent_look_and_a_point_inside_it(self):
        with self.assertRaises(ValueError):
            pointer.to_native(10, 10)
        pointer.remember_look((1600, 450), DESKTOP)
        with self.assertRaises(ValueError):
            pointer.to_native(1700, 10)
        with self.assertRaises(ValueError):
            pointer.to_native(10, 10, now=time.time() + pointer.LOOK_FRESH_SECONDS + 5)

    def test_the_label_goes_under_the_ring_or_above_it_near_the_bottom(self):
        left, top, ring, plate = pointer.layout(0, 700, "Click here", DESKTOP)
        self.assertEqual((left + ring[0], top + ring[1]), (0, 700))        # the ring is exactly on the point
        self.assertGreater(plate[1], ring[1])                              # label below
        left, top, ring, plate = pointer.layout(0, 1430, "Click here", DESKTOP)
        self.assertEqual((left + ring[0], top + ring[1]), (0, 1430))
        self.assertLess(plate[3], ring[1])                                 # label above, still on screen
        self.assertLessEqual(top + pointer.HEIGHT, 1440)

    def test_the_window_stays_on_the_desktop_at_the_edges(self):
        for x, y in ((-2560, 0), (2559, 1439), (-2560, 1439), (2559, 0)):
            left, top, ring, _ = pointer.layout(x, y, "", DESKTOP)
            self.assertGreaterEqual(left, DESKTOP[0])
            self.assertLessEqual(left + pointer.WIDTH, DESKTOP[2])
            self.assertGreaterEqual(top, DESKTOP[1])
            self.assertLessEqual(top + pointer.HEIGHT, DESKTOP[3])
            self.assertEqual((left + ring[0], top + ring[1]), (x, y))

    def test_a_point_off_every_screen_is_refused(self):
        with self.assertRaises(ValueError):
            pointer.show(9000, 100, bounds=DESKTOP)

    def test_tool_points_without_clicking_and_respects_off_limits_apps(self):
        import tools
        run = tools.TOOLS_BY_NAME["point_at_screen"]
        pointer.remember_look((1600, 450), DESKTOP)
        with mock.patch.object(pointer, "show", return_value=True) as show, \
                mock.patch.object(tools.worksafe, "point_blocked", return_value=False):
            reply = run.call({"x": 800, "y": 225, "label": "Click Display"})
        show.assert_called_once_with(0, 720, "Click Display", 8)
        self.assertIn("nothing was clicked", reply)
        with mock.patch.object(pointer, "show") as show, mock.patch.object(tools.worksafe, "point_blocked", return_value=True), \
                mock.patch.object(tools.worksafe, "blocked_apps", return_value="Teams"):
            with self.assertRaises(ValueError):
                run.call({"x": 800, "y": 225})
        show.assert_not_called()


if __name__ == "__main__":
    unittest.main()
