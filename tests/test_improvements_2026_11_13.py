"""Fixes that came out of reading three days of real conversations (2026-11-11 to 11-13)."""
import struct
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import context
import jarvis
import local_brain
import pc_lights
import suspend_watch
import tools
from voice import SentenceBuffer


class SentenceSplitTest(unittest.TestCase):
    def test_a_title_does_not_end_the_sentence(self):
        buf = SentenceBuffer()
        out = buf.feed("I'd like to introduce a few new acquaintances from Mr. Zubair Trabzada. Next one. ")
        self.assertEqual(out, ["I'd like to introduce a few new acquaintances from Mr. Zubair Trabzada.", "Next one."])

    def test_initials_stay_together_but_i_still_ends_a_sentence(self):
        buf = SentenceBuffer()
        self.assertEqual(buf.feed("J. R. R. Tolkien wrote it. "), ["J. R. R. Tolkien wrote it."])
        self.assertEqual(buf.feed("So do I. Shall we? "), ["So do I.", "Shall we?"])

    def test_a_line_break_releases_what_was_waiting(self):
        buf = SentenceBuffer()
        self.assertEqual(buf.feed("I'll put the PC to sleep."), [])
        self.assertEqual(buf.feed("\n"), ["I'll put the PC to sleep."])


def tool(name):
    return {"name": name, "description": name, "input_schema": {"type": "object", "properties": {}}}


class LocalBrainRoundsTest(unittest.TestCase):
    def test_words_either_side_of_a_tool_call_are_not_glued(self):
        rounds = iter([
            [{"message": {"content": "I'll put the PC to sleep.",
                          "tool_calls": [{"function": {"name": "sleep_computer", "arguments": {}}}]}}],
            [{"message": {"content": "There you go."}}, {"done": True}],
        ])
        heard = []
        with mock.patch.object(local_brain, "chat", side_effect=lambda payload, cancel: next(rounds)):
            answer = local_brain.Conversation().ask("m", "sys", [{"role": "user", "content": "sleep"}],
                                                    [tool("sleep_computer")], mock.Mock(return_value={"content": "ok"}),
                                                    heard.append, threading.Event())
        self.assertEqual(answer, "I'll put the PC to sleep.\nThere you go.")
        buf, said = SentenceBuffer(), []
        for piece in heard:
            said += buf.feed(piece)
        self.assertEqual(said + [buf.flush()], ["I'll put the PC to sleep.", "There you go."])


class SuspendWatchTest(unittest.TestCase):
    def setUp(self):
        self.saved = (list(suspend_watch._naps), suspend_watch._last_tick)
        suspend_watch._naps.clear()
        suspend_watch._last_tick = 0.0
        self.addCleanup(self.restore)

    def restore(self):
        suspend_watch._naps[:] = self.saved[0]
        suspend_watch._last_tick = self.saved[1]

    def test_a_long_gap_between_ticks_is_a_sleep(self):
        suspend_watch.note(1000, 1005)            # an ordinary tick
        self.assertEqual(suspend_watch.slept_since(0), 0)
        suspend_watch.note(1005, 1005 + 6 * 3600)  # the clock jumped six hours
        self.assertEqual(suspend_watch.slept_since(900), 6 * 3600)
        self.assertTrue(suspend_watch.stale(900))
        self.assertFalse(suspend_watch.stale(1005 + 6 * 3600 + 1))   # a turn begun after waking slept through nothing
        self.assertFalse(suspend_watch.stale(0))                    # no turn

    def test_a_short_nap_is_not_stale(self):
        suspend_watch.note(1000, 1000 + 120)
        self.assertEqual(suspend_watch.slept_since(900), 120)
        self.assertFalse(suspend_watch.stale(900))

    def test_the_first_seconds_after_waking_count_before_the_watcher_ticks(self):
        with mock.patch.object(suspend_watch.time, "time", return_value=50_000):
            suspend_watch._last_tick = 10_000
            self.assertTrue(suspend_watch.stale(9_990))     # began before the PC slept
            self.assertFalse(suspend_watch.stale(49_999))   # began after it woke

    def test_describe(self):
        self.assertEqual(suspend_watch.describe(20 * 60), "about 20 minutes")
        self.assertEqual(suspend_watch.describe(6 * 3600), "about 6 hours")


class StaleRequestTest(unittest.TestCase):
    def test_an_action_is_refused_after_the_pc_slept_but_a_lookup_is_not(self):
        with mock.patch.object(suspend_watch, "stale", return_value=True), \
                mock.patch.object(suspend_watch, "slept_since", return_value=6 * 3600):
            self.assertIn("NOT DONE", tools.stale_request("sleep_computer"))
            self.assertIn("about 6 hours", tools.stale_request("home_control"))
            for name in ("get_weather", "home_status", "self_check", "list_tasks", "terminal_status", "read_file"):
                self.assertIsNone(tools.stale_request(name), name)

    def test_nothing_is_refused_while_awake(self):
        with mock.patch.object(suspend_watch, "stale", return_value=False):
            self.assertIsNone(tools.stale_request("sleep_computer"))

    def test_run_tool_does_not_run_a_stale_action(self):
        block = SimpleNamespace(name="sleep_computer", id="1", input={})
        with mock.patch.object(tools, "stale_request", return_value="NOT DONE. Old request."), \
                mock.patch.object(tools, "_suspend") as suspend, mock.patch.object(tools.threading, "Timer") as timer:
            result = tools.run_tool(block)
        self.assertTrue(result.get("is_error"))
        self.assertIn("NOT DONE", result["content"])
        timer.assert_not_called()
        suspend.assert_not_called()


class SleepHonestyTest(unittest.TestCase):
    def test_sleep_says_what_it_pauses(self):
        with mock.patch.object(tools.threading, "Timer") as timer, \
                mock.patch.object(tools, "running_work", return_value=["the Giant Builder agent"]):
            reply = tools.sleep_computer.call({"delay_seconds": 5})
        timer.assert_called_once()
        self.assertIn("PAUSES", reply)
        self.assertIn("Giant Builder", reply)

    def test_sleep_with_nothing_running_is_plain(self):
        with mock.patch.object(tools.threading, "Timer"), mock.patch.object(tools, "running_work", return_value=[]):
            self.assertEqual(tools.sleep_computer.call({}), "The computer will go to sleep in 10 seconds.")

    def test_running_work_survives_a_source_that_fails(self):
        sessions = {"sessions": [{"name": "Frontier", "status": "running"}, {"name": "Old", "status": "done"}]}
        with mock.patch.object(tools.TERMINAL.__class__, "running", new_callable=mock.PropertyMock, side_effect=OSError), \
                mock.patch.object(tools.SESSIONS, "snapshot", return_value=sessions):
            found = tools.running_work()
        self.assertIn("the Frontier agent", found)
        self.assertNotIn("the Old agent", found)


def controller(colours):
    """A minimal OpenRGB protocol-0 controller description holding these LED colours."""
    def text(value):
        raw = value.encode() + b"\x00"
        return struct.pack("<H", len(raw)) + raw
    body = struct.pack("<i", 0) + b"".join(text(t) for t in ("name", "desc", "ver", "serial", "loc"))
    body += struct.pack("<H", 1) + struct.pack("<i", 0)                      # one mode, active mode
    body += text("Direct") + b"\x00" * 36 + struct.pack("<H", 1) + b"\x00" * 4  # the mode, with one mode colour
    body += struct.pack("<H", 1) + text("zone") + b"\x00" * 16 + struct.pack("<H", 0)   # one zone, no matrix
    body += struct.pack("<H", len(colours)) + b"".join(text(f"led{i}") + b"\x00" * 4 for i in range(len(colours)))
    body += struct.pack("<H", len(colours)) + b"".join(bytes((r, g, b, 0)) for r, g, b in colours)
    return struct.pack("<I", len(body) + 4) + body


class PcLightsTest(unittest.TestCase):
    def test_colours_are_read_from_a_controller_description(self):
        self.assertEqual(pc_lights.parse_colours(controller([(197, 0, 255), (0, 0, 0)])), [(197, 0, 255), (0, 0, 0)])

    def test_all_off_switches_every_part_and_says_work_carries_on(self):
        with mock.patch.object(pc_lights, "_backlights", return_value="B") as back, \
                mock.patch.object(pc_lights, "_rgb_off", return_value="R") as rgb, \
                mock.patch.object(pc_lights, "_screens", return_value="S") as screens:
            reply = pc_lights.control("off", "all", ["the Teardowns agent"])
        back.assert_called_once_with(False)
        rgb.assert_called_once_with()
        screens.assert_called_once_with(False)
        self.assertEqual(reply.splitlines()[:3], ["B", "R", "S"])
        self.assertIn("the Teardowns agent keeps running", reply)

    def test_one_part_only(self):
        with mock.patch.object(pc_lights, "_backlights") as back, mock.patch.object(pc_lights, "_rgb_on", return_value="R"), \
                mock.patch.object(pc_lights, "_screens") as screens:
            self.assertEqual(pc_lights.control("turn_on", "computer lights"), "R")
        back.assert_not_called()
        screens.assert_not_called()

    def test_unknown_words_are_refused(self):
        with self.assertRaises(ValueError):
            pc_lights.control("dim")
        with self.assertRaises(ValueError):
            pc_lights.control("off", "ceiling")

    def test_screens_go_dark_after_a_pause_and_wake_at_once(self):
        with mock.patch.object(threading, "Timer") as timer, mock.patch.object(pc_lights, "_screens_power") as power:
            self.assertIn("sent", pc_lights._screens(False))
            power.assert_not_called()
            self.assertEqual(timer.call_args.kwargs["args"], (2,))
        with mock.patch.object(pc_lights, "_screens_power") as power, mock.patch.object(pc_lights.ctypes, "windll"):
            pc_lights._screens(True)
            power.assert_called_once_with(-1)

    def test_receipts_follow_what_each_part_reported(self):
        import truth_guard
        self.assertIsNone(truth_guard.classify("pc_lights", True, "Status:\nKeyboard and PC lights: on"))
        self.assertEqual(truth_guard.classify("pc_lights", True, "Monitor backlights: Confirmed: Desk lights is off."),
                         truth_guard.CONFIRMED)
        self.assertEqual(truth_guard.classify("pc_lights", True, "Screens: both go dark in 4 seconds (sent)."),
                         truth_guard.SENT)
        for bad in ("Keyboard and PC lights: NOT DONE, the OpenRGB service isn't answering.",
                    "Monitor backlights: Confirmed.\nKeyboard and PC lights: NOT CONFIRMED, 1 of 3 still lit."):
            self.assertEqual(truth_guard.classify("pc_lights", True, bad), truth_guard.UNKNOWN)

    def test_the_tool_is_offered_to_every_brain(self):
        self.assertIn("pc_lights", tools.TOOLS_BY_NAME)
        self.assertIn("pc_lights", local_brain.TOOLS)


class OverheardTest(unittest.TestCase):
    def test_only_nameless_continuous_speech_is_marked(self):
        heard = jarvis.heard_as("they get like flirty", "Yeah, they get like flirty", False, "continuous")
        self.assertIsInstance(heard, jarvis.Overheard)
        self.assertEqual(heard, "they get like flirty")
        for text, woke, mode in (("Jarvis, what time is it", False, "continuous"),
                                 ("what time is it, Jarvis?", False, "continuous"),
                                 ("what time is it", True, "continuous"),
                                 ("what time is it", False, "wake")):
            self.assertNotIsInstance(jarvis.heard_as("what time is it", text, woke, mode), jarvis.Overheard, text)

    def test_the_prompt_explains_the_note(self):
        self.assertIn(jarvis.NO_NAME, jarvis.SYSTEM_PROMPT)
        self.assertIn("(quiet)", jarvis.SYSTEM_PROMPT)

    def test_the_note_is_not_kept_in_the_saved_conversation(self):
        brain = jarvis.Brain.__new__(jarvis.Brain)
        with mock.patch.object(jarvis.memory, "record_turn") as record:
            brain._save_turn(f"That is wild. {jarvis.NO_NAME}", "(quiet)")
        self.assertEqual(record.call_args.args[0], "That is wild.")


class WeatherWordsTest(unittest.TestCase):
    def test_cold_is_named(self):
        self.assertEqual(context._feel(21, True), "below freezing")
        self.assertEqual(context._feel(9, True), "bitterly cold, well below freezing")
        self.assertEqual(context._feel(60, True), "")
        self.assertEqual(context._feel(-10, False), "bitterly cold, well below freezing")

    def test_the_report_carries_the_word_and_snow(self):
        answer = {"current": {"temperature_2m": 21.2, "apparent_temperature": 9.0, "weather_code": 0, "wind_speed_10m": 18},
                  "daily": {"temperature_2m_max": [30, 28], "temperature_2m_min": [12, 10],
                            "precipitation_probability_max": [10, 70], "weather_code": [3, 73]}}
        with mock.patch.object(context, "_location", return_value={"loc": "44.7,-93.1", "country": "US", "city": "Rosemount"}), \
                mock.patch.object(context.requests, "get", return_value=mock.Mock(json=mock.Mock(return_value=answer))):
            said = context.weather()
        self.assertIn("now 21°F (below freezing), feels like 9°F", said)
        self.assertIn("wind 18 mph", said)
        self.assertIn("70% chance of snow", said)
        self.assertIn("10% chance of rain", said)


class FillerTest(unittest.TestCase):
    def test_the_start_of_a_thought_is_not_a_request(self):
        for said in ("Um...", "uh", "Hmm.", "Wait.", "hold on", "So, um...", "Actually...", "wait wait wait", ""):
            self.assertTrue(jarvis.is_filler(said), said)

    def test_answers_and_requests_are_not_fillers(self):
        for said in ("Yes.", "No", "Okay", "Yeah", "Wait, what did you say?", "So what's next", "Southwick",
                     "hold on to that file", "pull it apart", "actually do the other one"):
            self.assertFalse(jarvis.is_filler(said), said)


class NearVoiceMatchTest(unittest.TestCase):
    def listener(self, score, heard, woke=False):
        import queue

        import numpy as np

        import ears
        source = ears.Ears.__new__(ears.Ears)
        source._phrases = queue.Queue()
        source._phrases.put((np.zeros(16000, dtype=np.int16), woke, 0.0))
        source.voiceprint = np.ones(2)
        source.threshold = 0.62
        source._owner_check = mock.Mock(return_value=score)
        source.pool = mock.Mock()
        source.pool.submit.return_value.result.return_value = heard
        source.transcribe = mock.Mock()
        source.logged = []
        source._log = source.logged.append
        return source

    def test_a_near_match_that_says_his_name_is_heard(self):
        source = self.listener(0.55, "Jarvis, I'm just gonna restart you.")
        self.assertEqual(source.listen(timeout=0), ("Jarvis, I'm just gonna restart you.", False))
        self.assertTrue(any("near match" in line for line in source.logged))

    def test_a_near_match_without_his_name_is_ignored_and_its_words_logged(self):
        source = self.listener(0.55, "Pull it apart.")
        self.assertIsNone(source.listen(timeout=0))
        self.assertTrue(any("ignored a voice" in line and "Pull it apart" in line for line in source.logged))

    def test_a_poor_match_is_ignored_even_with_his_name(self):
        source = self.listener(0.40, "Jarvis, open the door.")
        self.assertIsNone(source.listen(timeout=0))
        source.pool.submit.return_value.result.assert_not_called()   # its words are not even read
        self.assertFalse(any("Jarvis" in line for line in source.logged))

    def test_the_wake_word_counts_as_his_name(self):
        source = self.listener(0.58, "Hey Travis, what time is it", woke=True)
        self.assertEqual(source.listen(timeout=0), ("Hey Travis, what time is it", True))


class RestartKeepsTheLightsTest(unittest.TestCase):
    def test_the_colour_flow_is_not_one_of_jarvis_own_workers(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import restart_jarvis

        def process(*cmdline):
            return mock.Mock(name=mock.Mock(return_value="pythonw.exe"), cmdline=mock.Mock(return_value=list(cmdline)))
        flow, worker = process("pythonw.exe", "C:/Users/x/Jarvis/scripts/rgb_flow.py"), process("pythonw.exe", "-c", "work")
        flow.name.return_value = worker.name.return_value = "pythonw.exe"
        self.assertFalse(restart_jarvis._is_worker(flow))
        self.assertTrue(restart_jarvis._is_worker(worker))


class GoodNightTest(unittest.TestCase):
    def test_good_night_no_longer_ends_the_program(self):
        self.assertNotIn("good night", jarvis.EXIT_PHRASES)
        self.assertNotIn("go to sleep", jarvis.EXIT_PHRASES)
        self.assertIn("shut down", jarvis.EXIT_PHRASES)
        self.assertIn("Good night", jarvis.SYSTEM_PROMPT)


class TextReplyTest(unittest.TestCase):
    def test_an_echoed_marker_is_dropped(self):
        self.assertEqual(jarvis.without_marker("[Via Telegram] Jarvis is here, sir."), "Jarvis is here, sir.")
        self.assertEqual(jarvis.without_marker(" [Via Phone as FRIDAY] [Via Phone] On it."), "On it.")
        self.assertEqual(jarvis.without_marker("The file [Via x] stays."), "The file [Via x] stays.")
        self.assertEqual(jarvis.without_marker("  "), "")


class QuietLogsTest(unittest.TestCase):
    def test_the_uploads_playlist_is_used_when_the_channel_feed_is_missing(self):
        import creator_watch
        feed = (b'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
                b'<entry><yt:videoId>abc</yt:videoId><title>New</title><published>2026-11-11T00:00:00</published>'
                b'</entry></feed>')
        asked = []

        def get(url, **_):
            asked.append(url)
            if "channel_id=" in url:
                return mock.Mock(status_code=404)
            return mock.Mock(status_code=200, content=feed, raise_for_status=lambda: None)
        with mock.patch.object(creator_watch.requests, "get", side_effect=get):
            found = creator_watch.videos("UC123")
        self.assertEqual([v["id"] for v in found], ["abc"])
        self.assertIn("playlist_id=UU123", asked[1])


class HomeTilesTest(unittest.TestCase):
    def test_a_group_shows_once_and_option_switches_are_left_out(self):
        import home_assistant

        def device(domain, name, **attributes):
            return {"id": f"{domain}.{name.lower().replace(' ', '_')}", "domain": domain, "name": name,
                    "state": "on", "attributes": attributes}
        everything = [device("light", "Monitor 2"), device("switch", "Monitor 2 Sync send"),
                      device("switch", "Monitor 2 Nightlight"), device("light", "Monitor 1"),
                      device("light", "Desk lights", entity_id=["light.monitor_2", "light.monitor_1"]),
                      device("fan", "Bedroom Fan"), device("switch", "Bedroom Fan"), device("switch", "Air purifier")]
        self.assertEqual([d["name"] for d in home_assistant.tiles(everything)],
                         ["Desk lights", "Bedroom Fan", "Air purifier"])
        self.assertEqual([d["domain"] for d in home_assistant.tiles(everything)], ["light", "fan", "switch"])

    def test_numbered_bulbs_of_an_unreachable_group_show_once(self):
        import home_assistant

        def light(name, state):
            return {"id": "light." + name.lower().replace(" ", "_"), "domain": "light", "name": name, "state": state,
                    "attributes": {}}
        everything = [light("Ceiling Light", "unavailable"), light("Ceiling Light 1", "unavailable"),
                      light("Ceiling Light 2", "unavailable"), light("Lamp 2", "on")]
        self.assertEqual([d["name"] for d in home_assistant.tiles(everything)], ["Ceiling Light", "Lamp 2"])
        everything[1]["state"] = "on"   # a bulb that differs from the group is worth its own tile
        self.assertIn("Ceiling Light 1", [d["name"] for d in home_assistant.tiles(everything)])


if __name__ == "__main__":
    unittest.main()
