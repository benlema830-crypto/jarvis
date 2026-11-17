"""Explanation cards over the screen (explain_cards.py) and the orb that follows the mouse (cursor_companion.py)."""
import queue
import unittest
from unittest import mock

import numpy as np

import cursor_companion as companion
import explain_cards as cards
import screen_pointer as pointer

WORK = (0, 0, 2560, 1392)              # one 1440p monitor's work area (taskbar at the bottom)
LEFT_WORK = (-2560, 0, 0, 1392)


def inside(box, area):
    return area[0] <= box[0] and area[1] <= box[1] and box[2] <= area[2] and box[3] <= area[3]


class CardContentTest(unittest.TestCase):
    def test_cards_are_tidied_trimmed_and_capped(self):
        title, tidy = cards.normalize([
            {"kind": "Diagram", "title": "x" * 90, "items": ["a", "b"]},
            {"type": "history", "items": ["2012 - Founded"] * 9},
            {"kind": "mystery", "items": "just one line"},
            {"kind": "note", "text": "A sentence."},
            {"kind": "facts", "items": ["fifth card is dropped"]},
        ], "  Title   with   spaces ")
        self.assertEqual(title, "Title with spaces")
        self.assertEqual([c["kind"] for c in tidy], ["flow", "timeline", "facts", "summary"])
        self.assertEqual(len(tidy[0]["title"]), 48)
        self.assertEqual(len(tidy[1]["items"]), cards.MAX_ITEMS)
        self.assertEqual(tidy[2]["items"], ["just one line"])
        self.assertEqual(tidy[3]["items"], ["A sentence."])

    def test_empty_cards_are_refused(self):
        for bad in ([], [{"kind": "facts", "items": []}], "text", [None]):
            with self.assertRaises(ValueError):
                cards.normalize(bad)

    def test_labels_split_off_dates_and_keys(self):
        self.assertEqual(cards.split_label("1998 - Founded in Menlo Park"), ("1998", "Founded in Menlo Park"))
        self.assertEqual(cards.split_label("Made by: PTC"), ("Made by", "PTC"))
        self.assertEqual(cards.split_label("No label here"), ("", "No label here"))
        self.assertEqual(cards.split_label("A very long opening phrase that is not a label: really")[0], "")

    def test_every_kind_renders_in_its_panel_and_scales_with_the_monitor(self):
        for kind in cards.KINDS:
            card = {"kind": kind, "title": "Title", "items": ["Label: a value that is long enough to wrap twice "
                                                              "across the card", "2019 - Second", "Third"]}
            image, margin = cards.render_card(card)
            self.assertEqual(image.width - 2 * margin, cards.CARD_WIDTH)
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 0)                       # see-through around the glow
            self.assertGreater(image.getpixel((margin + 30, margin + 30))[3], 200)  # the panel itself is solid
            big, big_margin = cards.render_card(card, 1.5)
            self.assertEqual(big.width - 2 * big_margin, round(cards.CARD_WIDTH * 1.5))
        header, _ = cards.render_header("What this page is about")
        self.assertGreater(header.height, 60)


class CardPlacementTest(unittest.TestCase):
    sizes = [(340, 90), (340, 200), (340, 230)]

    def boxes(self, spots, sizes=None):
        return [(x, y, x + w, y + h) for (x, y), (w, h) in zip(spots, sizes or self.sizes)]

    def test_cards_go_beside_the_region_on_the_right_when_there_is_room(self):
        spots = cards.place(self.sizes, WORK, (300, 150, 1700, 900))
        self.assertEqual(spots[0], (1714, 150))
        for box in self.boxes(spots):
            self.assertGreaterEqual(box[0], 1700)
            self.assertTrue(inside(box, WORK))

    def test_left_of_the_region_when_the_right_is_full(self):
        spots = cards.place(self.sizes, LEFT_WORK, (-1500, 200, -100, 1000))
        for box in self.boxes(spots):
            self.assertLessEqual(box[2], -1500)
            self.assertTrue(inside(box, LEFT_WORK))

    def test_over_the_regions_right_edge_when_it_fills_the_screen(self):
        spots = cards.place(self.sizes, WORK, (0, 0, 2560, 1392))
        for box in self.boxes(spots):
            self.assertTrue(inside(box, WORK))
            self.assertGreater(box[0], 2000)

    def test_a_tall_stack_becomes_two_columns_and_stays_on_screen(self):
        sizes = [(340, 500)] * 4
        spots = cards.place(sizes, WORK, (300, 1200, 900, 1380))
        self.assertEqual(len({x for x, _ in spots}), 2)
        for box in self.boxes(spots, sizes):
            self.assertTrue(inside(box, WORK))

    def test_no_region_means_down_the_right_side(self):
        spots = cards.place(self.sizes, WORK)
        self.assertGreater(spots[0][0], 2100)
        self.assertEqual(spots[1][1], spots[0][1] + 90 + cards.GAP)


class CompanionPlacementTest(unittest.TestCase):
    def test_the_orb_sits_just_below_right_of_the_pointer(self):
        orb, bubble, _ = companion.place((1000, 500), WORK, 76)
        self.assertEqual(orb, (1000 + companion.OFFSET[0], 500 + companion.OFFSET[1]))
        self.assertIsNone(bubble)

    def test_it_flips_at_the_right_and_bottom_edges_and_never_leaves_the_screen(self):
        orb, _, _ = companion.place((2550, 1385), WORK, 76)
        self.assertLess(orb[0] + 76, 2550)
        self.assertLess(orb[1] + 76, 1385)
        for point in ((0, 0), (2559, 0), (0, 1391), (-2560, 700)):
            work = LEFT_WORK if point[0] < 0 else WORK
            orb, bubble, _ = companion.place(point, work, 76, (360, 140, 20))
            self.assertTrue(inside((*orb, orb[0] + 76, orb[1] + 76), work))
            panel = (bubble[0] + 20, bubble[1] + 20, bubble[0] + 340, bubble[1] + 120)
            self.assertTrue(inside(panel, work), (point, panel))

    def test_the_bubble_opens_away_from_the_pointer(self):
        _, bubble, tail = companion.place((1000, 500), WORK, 76, (360, 140, 20))
        self.assertGreater(bubble[0] + 20, 1000)
        self.assertEqual(tail, "left")
        _, bubble, tail = companion.place((2540, 500), WORK, 76, (360, 140, 20))
        self.assertLess(bubble[0] + 340, 2540)
        self.assertEqual(tail, "right")


class CompanionLookTest(unittest.TestCase):
    def test_the_orb_is_a_hollow_glowing_shell_and_see_through_at_the_corners(self):
        frame = companion.render_orb("speaking", 3)
        self.assertEqual(frame.size, (companion.ORB, companion.ORB))
        self.assertEqual(frame.getpixel((0, 0))[3], 0)
        pixels = np.asarray(frame)
        lit = (pixels[..., 3] > 200) & (pixels[..., :3].max(axis=2) > 180)
        self.assertGreater(int(lit.sum()), 60)                # block outlines in his colour
        middle = [frame.getpixel((companion.ORB // 2 + dx, companion.ORB // 2 + dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
        self.assertLess(sum(max(p[:3]) for p in middle) / 9, 235)   # no white-hot core: nothing sits in the middle

    def test_the_orb_stays_put_and_its_loop_repeats(self):
        for state in ("standby", "listening", "thinking", "speaking"):
            first = np.asarray(companion.render_orb(state, 0), dtype=np.int16)
            again = np.asarray(companion.render_orb(state, companion.FRAMES), dtype=np.int16)
            self.assertEqual(int(np.abs(first - again).max()), 0, state)     # the last frame runs into the first
            for i in range(0, companion.FRAMES, 6):                          # he never bounces: his weight stays on the centre
                alpha = np.asarray(companion.render_orb(state, i), dtype=np.float32)[..., 3]
                rows, columns = np.mgrid[0:alpha.shape[0], 0:alpha.shape[1]]
                middle = (companion.ORB - 1) / 2
                self.assertLess(abs(float((rows * alpha).sum() / alpha.sum()) - middle), 2, (state, i))
                self.assertLess(abs(float((columns * alpha).sum() / alpha.sum()) - middle), 2, (state, i))

    def test_a_long_reply_shows_its_latest_lines_in_a_bounded_bubble(self):
        short, _ = companion.render_bubble("Hello.")
        long, margin = companion.render_bubble("word " * 400)
        self.assertLessEqual(long.width - 2 * margin, companion.BUBBLE_WIDTH + 2)
        self.assertLess(long.height, 220)
        self.assertGreater(long.height, short.height)
        thinking, _ = companion.render_bubble("", "thinking")
        self.assertEqual(thinking.mode, "RGBA")

    def bare(self):
        c = companion.Companion.__new__(companion.Companion)
        c.events, c.state = queue.Queue(), "standby"
        c.reply, c.reply_at, c.reply_done = "", 0.0, True
        return c

    def test_the_bubble_follows_the_conversation(self):
        c = self.bare()
        for event in ({"type": "you", "text": "hi"}, {"type": "state", "state": "thinking"},
                      {"type": "jarvis", "text": "Hello there."}, {"type": "jarvis", "text": "(to phone) not here"},
                      {"type": "state", "state": "speaking"}, {"type": "jarvis", "text": "Second line."}):
            c.events.put(event)
        c._drain(10.0)
        self.assertEqual(c.reply, "Hello there. Second line.")
        self.assertFalse(c.reply_done)
        c.events.put({"type": "state", "state": "standby"})
        c._drain(12.0)
        self.assertTrue(c.reply_done)
        self.assertEqual(c.reply_at, 12.0)
        c.events.put({"type": "you", "text": "next"})
        c._drain(13.0)
        self.assertEqual(c.reply, "")


class OverlayToolsTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(pointer, "_look", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_tools_are_offered_to_the_voice_model(self):
        import tools
        names = {t["name"] for t in tools.TOOL_DEFS}
        self.assertLessEqual({"explain_on_screen", "clear_on_screen", "cursor_companion"}, names)
        self.assertIn("visually explain", tools.TOOLS_BY_NAME["explain_on_screen"].to_dict()["description"])

    def test_explain_without_cards_takes_the_screenshot_first(self):
        import tools
        shot = [{"type": "image", "source": {}}, {"type": "text", "text": "All monitors captured."}]
        with mock.patch.object(tools.look_at_screen, "call", return_value=shot) as look, \
                mock.patch.object(cards, "show") as show:
            result = tools.TOOLS_BY_NAME["explain_on_screen"].call({})
        look.assert_called_once()
        show.assert_not_called()
        self.assertIn("call explain_on_screen again", result[-1]["text"])

    def test_explain_maps_the_region_onto_the_desktop_and_shows_the_cards(self):
        import tools
        pointer.remember_look((1600, 450), (-2560, 0, 2560, 1440))
        shown = {"cards": 1, "titles": ["Key facts"], "seconds": 60, "where": "beside the area it explains"}
        card = [{"kind": "facts", "items": ["One"]}]
        with mock.patch.object(cards, "show", return_value=shown) as show, \
                mock.patch.object(tools.worksafe, "point_blocked", return_value=False):
            reply = tools.TOOLS_BY_NAME["explain_on_screen"].call(
                {"cards": card, "title": "T", "region": [800, 0, 1600, 450]})
        show.assert_called_once_with("T", card, (0, 0, 2560, 1440), 60)
        self.assertIn("nothing was clicked", reply)

    def test_explain_with_cards_needs_a_recent_look(self):
        import tools
        with mock.patch.object(cards, "show") as show:
            with self.assertRaises(ValueError):
                tools.TOOLS_BY_NAME["explain_on_screen"].call({"cards": [{"kind": "facts", "items": ["x"]}]})
        show.assert_not_called()

    def test_regions_are_trimmed_to_the_screenshot(self):
        pointer.remember_look((1600, 450), (-2560, 0, 2560, 1440))
        self.assertEqual(pointer.rect_to_native(1700, 500, -10, -10), (-2560, 0, 2560, 1440))

    def test_clear_takes_down_cards_and_pointer(self):
        import tools
        with mock.patch.object(cards, "hide", return_value=True), mock.patch.object(pointer, "hide"):
            self.assertEqual(tools.TOOLS_BY_NAME["clear_on_screen"].call({}), "Cleared the cards.")
        with mock.patch.object(cards, "hide", return_value=False), mock.patch.object(pointer, "hide"):
            self.assertIn("Nothing", tools.TOOLS_BY_NAME["clear_on_screen"].call({}))

    def test_companion_tool_turns_it_on_and_off(self):
        import tools
        with mock.patch.object(companion, "enable", return_value=True) as enable:
            self.assertIn("Following", tools.TOOLS_BY_NAME["cursor_companion"].call({"on": True}))
        enable.assert_called_once_with(True)
        with mock.patch.object(companion, "enable", return_value=False):
            self.assertIn("Back to normal", tools.TOOLS_BY_NAME["cursor_companion"].call({"on": False}))

    def test_the_choice_is_saved_and_reported_in_settings(self):
        import hud
        import preferences
        with mock.patch.object(preferences, "read", return_value={"cursor_companion": True}), \
                mock.patch.object(hud, "voice_settings", return_value={}):
            self.assertTrue(hud.settings()["cursor_companion"])
            self.assertTrue(companion.wanted())
        with mock.patch.object(companion.ui.HOST, "call") as call, \
                mock.patch.object(preferences, "update") as update, mock.patch.object(hud, "emit"), \
                mock.patch.object(hud, "settings", return_value={}):
            companion.enable(False)
        call.assert_called_once()
        update.assert_called_once_with(cursor_companion=False)

    def test_restore_never_draws_on_screen_under_test(self):
        with mock.patch.object(companion, "enable") as enable:
            self.assertFalse(companion.restore())
        enable.assert_not_called()


class AppCornerOrbTest(unittest.TestCase):
    def test_the_corner_orb_steps_aside_for_the_companion_and_comes_back(self):
        import jarvis_app
        app = jarvis_app.App(mock.Mock())
        app.orb = mock.Mock()
        app.orb.native.Handle.ToInt32.return_value = 42
        with mock.patch("win32gui.IsWindowVisible", return_value=True), \
                mock.patch.object(app, "main_visible", return_value=False):
            app.follow_companion(True)
            app.orb.hide.assert_called_once()
            app.follow_companion(True)                        # no change: nothing happens again
            app.orb.hide.assert_called_once()
            app.follow_companion(False)
        app.orb.show.assert_called_once()

    def test_an_orb_the_user_had_hidden_stays_hidden(self):
        import jarvis_app
        app = jarvis_app.App(mock.Mock())
        app.orb = mock.Mock()
        app.orb.native.Handle.ToInt32.return_value = 42
        with mock.patch("win32gui.IsWindowVisible", return_value=False), \
                mock.patch.object(app, "main_visible", return_value=False):
            app.follow_companion(True)
            app.follow_companion(False)
        app.orb.hide.assert_not_called()
        app.orb.show.assert_not_called()


if __name__ == "__main__":
    unittest.main()
