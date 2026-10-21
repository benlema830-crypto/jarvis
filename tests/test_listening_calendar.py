import datetime
import http.client
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

import context
import ears
import hud
import preferences


def feed():
    tomorrow = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    start = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Jarvis Test//EN\r\n"
            "BEGIN:VEVENT\r\nUID:jarvis-test\r\n"
            f"DTSTART:{start:%Y%m%dT%H%M%SZ}\r\n"
            f"DTEND:{start + datetime.timedelta(hours=1):%Y%m%dT%H%M%SZ}\r\n"
            "SUMMARY:Calendar connection test\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").encode()


def response(content):
    result = mock.MagicMock()
    result.__enter__.return_value = result
    result.iter_content.return_value = [content]
    return result


class PreferencesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patch = mock.patch.object(preferences, "PATH", Path(self.temp.name) / "preferences.json")
        patch.start()
        self.addCleanup(patch.stop)
        env = mock.patch.dict(os.environ, {"JARVIS_LISTENING_MODE": "wake",
                                          "CALENDAR_ICS_URLS": "", "GOOGLE_CALENDAR_ICS_URL": ""})
        env.start()
        self.addCleanup(env.stop)

    def test_ui_toggle_persists_without_overwriting_calendar(self):
        preferences.update(calendar_urls=["https://example.com/private.ics"])
        hud.update_settings({"listening_mode": "continuous"})
        self.assertEqual(preferences.listening_mode(), "continuous")
        self.assertEqual(context.calendar_urls(), ["https://example.com/private.ics"])
        self.assertNotIn("private.ics", json.dumps(hud.settings()))
        hud.update_settings({"listening_mode": "wake"})
        self.assertEqual(preferences.listening_mode(), "wake")
        with self.assertRaises(ValueError):
            hud.update_settings({"listening_mode": "invalid"})
        self.assertEqual(preferences.listening_mode(), "wake")

    def test_calendar_connect_reads_feed_with_outlook_closed(self):
        outlook = mock.Mock()
        outlook.upcoming.side_effect = AssertionError("Should not automate Outlook")
        with mock.patch.object(context.requests, "get", return_value=response(feed())), \
             mock.patch.dict("sys.modules", {"outlook_calendar": outlook}):
            hud.update_calendar({"action": "connect", "url": "webcal://example.com/private.ics"})
            self.assertIn("Calendar connection test", context.upcoming_events(2))
        self.assertEqual(context.calendar_urls(), ["https://example.com/private.ics"])

    def test_bad_feed_does_not_replace_connection(self):
        preferences.update(calendar_urls=["https://example.com/existing.ics"])
        with mock.patch.object(context.requests, "get", return_value=response(b"<html>Sign in</html>")):
            with self.assertRaises(ValueError):
                context.connect_calendar("https://example.com/wrong-link")
        self.assertEqual(context.calendar_urls(), ["https://example.com/existing.ics"])

    def test_no_link_never_launches_outlook_in_background(self):
        with mock.patch.dict(os.environ, {"JARVIS_ALLOW_OUTLOOK": "1"}), \
             mock.patch.dict("sys.modules", {"outlook_calendar": mock.Mock()}):
            self.assertIn("Calendar not connected", context.upcoming_events())

    def test_disconnect_overrides_old_environment_link(self):
        with mock.patch.dict(os.environ, {"CALENDAR_ICS_URLS": "https://example.com/old.ics"}):
            self.assertTrue(context.calendar_urls())
            result = hud.update_calendar({"action": "disconnect"})
            self.assertFalse(result["calendar_connected"])
            self.assertEqual(context.calendar_urls(), [])

    def test_error_does_not_expose_private_url(self):
        with mock.patch.object(context.requests, "get", side_effect=context.requests.ConnectionError("SECRET")):
            with self.assertRaises(ValueError) as caught:
                context.fetch_calendar("https://example.com/SECRET")
        self.assertNotIn("SECRET", str(caught.exception))

    def test_http_controls_and_calendar_refresh(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), hud._Handler)
        server.daemon_threads = True
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(method, path, payload=None, content_type="application/json"):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                body = json.dumps(payload) if payload is not None else None
                connection.request(method, path, body, {"Content-Type": content_type})
                result = connection.getresponse()
                return result.status, result.read().decode()
            finally:
                connection.close()

        try:
            with mock.patch.object(hud, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"}), \
                 mock.patch.object(context, "fetch_calendar", return_value=context.icalendar.Calendar()), \
                 mock.patch.object(hud, "intel", return_value={"weather": "test", "schedule": "Nothing scheduled."}) as intel:
                status, body = request("POST", "/settings", {"listening_mode": "continuous"})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["listening_mode"], "continuous")
                status, body = request("POST", "/calendar", {"action": "connect", "url": "https://example.com/PRIVATE.ics"})
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["calendar_connected"])
                self.assertNotIn("PRIVATE", body)
                status, body = request("GET", "/settings")
                self.assertEqual(status, 200)
                self.assertNotIn("PRIVATE", body)
                self.assertEqual(request("GET", "/intel?refresh=1")[0], 200)
                intel.assert_called_once_with(refresh=True)
                # Exercise consecutive rejections: unread bodies used to cause
                # intermittent Windows socket resets instead of HTTP 400.
                for _ in range(5):
                    self.assertEqual(request("POST", "/settings", {"listening_mode": "wake"}, "text/plain")[0], 400)
                self.assertEqual(preferences.listening_mode(), "continuous")
                self.assertEqual(request("POST", "/calendar", {"action": "disconnect"})[0], 200)
                self.assertFalse(context.calendar_urls())
        finally:
            server.shutdown()
            server.server_close()


class ListeningTest(unittest.TestCase):
    def test_mode_filter_and_followups(self):
        self.assertIsNone(ears.command_for_mode("What's on my calendar?"))
        self.assertEqual(ears.command_for_mode("What's on my calendar?", mode="continuous"),
                         "What's on my calendar?")
        self.assertEqual(ears.command_for_mode("Jarvis, check my calendar", mode="continuous"), "check my calendar")
        self.assertEqual(ears.command_for_mode("Hey Jarvis", mode="wake"), "")
        self.assertEqual(ears.command_for_mode("And tomorrow?", in_followup=True), "And tomorrow?")
        self.assertEqual(ears.command_for_mode("Tell me about Jarvis", mode="continuous"), "Tell me about Jarvis")

    def test_live_toggle_is_used_after_waiting_for_speech(self):
        import jarvis
        turns = SimpleNamespace(idle=mock.Mock(), count=0, followup_until=0)
        source = mock.Mock()
        source.listen.side_effect = [("Check my calendar", False), StopIteration()]
        with mock.patch.object(preferences, "listening_mode", side_effect=["wake", "continuous", "continuous"]), \
             mock.patch.object(hud, "commands") as commands, mock.patch.object(hud, "emit"):
            with self.assertRaises(StopIteration):
                jarvis.listen_loop(source, mock.Mock(), turns)
            commands.put.assert_called_once_with("Check my calendar")

    def test_reply_tail_cannot_become_a_continuous_command(self):
        source = ears.Ears.__new__(ears.Ears)
        source.accepting = threading.Event()  # Jarvis is speaking.
        source.on_wake = None
        source.wake = mock.Mock()
        source.wake.predict.return_value = {ears.WAKE_MODEL: 0.0}
        source._phrases = queue.Queue()
        source._busy_phrases = queue.Queue()
        source._is_speech = mock.Mock(side_effect=[True] * 4 + [False] * 9)
        n = 0

        def get_block():
            nonlocal n
            n += 1
            if n == 6:
                source.accepting.set()  # Playback ends while the phrase is trailing off.
            if n > 13:
                raise StopIteration
            return np.zeros(ears.BLOCK, dtype=np.int16)

        source._blocks = mock.Mock()
        source._blocks.get.side_effect = get_block
        with self.assertRaises(StopIteration):
            source._process()
        self.assertTrue(source._phrases.empty())
        self.assertEqual(source._busy_phrases.qsize(), 1)
