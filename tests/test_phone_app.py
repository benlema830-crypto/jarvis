"""The phone app: installable files, late answers kept for the app, alert sign-up, and who gets a question."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("JARVIS_UNDER_TEST", "1")
import jarvis  # noqa: E402
import phone_bridge  # noqa: E402
import phone_push  # noqa: E402
import whereabouts  # noqa: E402
from tests import test_phone_bridge as bridge_tests  # noqa: E402 - a module, so its tests are not collected here

AUTH = {"Authorization": "Bearer secret-token"}
SUB = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": "BPk", "auth": "xyz"}}


class PhoneAppTest(unittest.TestCase):
    """Runs on the same throwaway bridge as the phone bridge tests, without running those tests again."""
    request, ask = bridge_tests.PhoneBridgeTest.request, bridge_tests.PhoneBridgeTest.ask

    def setUp(self):
        bridge_tests.PhoneBridgeTest.setUp(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(phone_push, "SUBSCRIPTIONS", Path(folder.name) / "push.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_app_files_need_no_key_and_hold_no_secrets(self):
        for path in phone_bridge.APP_FILES:
            status, body = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertNotIn(b"secret-token", body)
        manifest = json.loads(self.request("GET", "/manifest.webmanifest")[1])
        self.assertEqual(manifest["display"], "standalone")

    def test_inbox_and_alert_key_need_the_key(self):
        self.assertEqual(self.request("GET", "/inbox")[0], 401)
        self.assertEqual(self.request("GET", "/push/key")[0], 401)
        self.assertEqual(self.request("POST", "/push/subscribe", json.dumps({"subscription": SUB}),
                                      {"Content-Type": "application/json"})[0], 401)

    def test_an_answer_after_the_phone_stopped_waiting_reaches_the_app(self):
        replies = []
        self.bridge.on_message = lambda text, reply, voice: replies.append(reply)
        with mock.patch.object(phone_bridge, "REPLY_SECONDS", 0.2), mock.patch.object(phone_push, "send") as send:
            self.assertIn("send the answer to your phone", self.ask()[1]["reply"])
            phone_push.subscribe(SUB)
            replies[0]("The render finished: 42 frames.")
            for _ in range(100):
                if send.called:
                    break
                time.sleep(0.01)
        status, body = self.request("GET", "/inbox?after=0", headers=AUTH)
        items = json.loads(body)["items"]
        # asked without the app's header, like a Siri Shortcut: the question shows in the app too
        self.assertEqual([(item["who"], item["text"]) for item in items],
                         [("you", "hi"), ("jarvis", "The render finished: 42 frames.")])
        self.assertEqual(json.loads(self.request("GET", f"/inbox?after={items[-1]['id']}", headers=AUTH)[1])["items"], [])
        send.assert_called_once()

    def test_subscribe_checks_the_subscription(self):
        headers = {**AUTH, "Content-Type": "application/json"}
        bad = {"endpoint": "http://insecure.example", "keys": {"p256dh": "a", "auth": "b"}}
        self.assertEqual(self.request("POST", "/push/subscribe", json.dumps({"subscription": bad}), headers)[0], 400)
        self.assertEqual(self.request("POST", "/push/subscribe", json.dumps({"subscription": SUB}), headers)[0], 200)
        self.assertTrue(phone_push.ready())
        self.request("POST", "/push/subscribe", json.dumps({"subscription": SUB}), headers)
        self.assertEqual(len(phone_push._load()), 1)  # the same phone twice is one entry
        self.request("POST", "/push/unsubscribe", json.dumps({"subscription": SUB}), headers)
        self.assertFalse(phone_push.ready())


class QuestionAlertTest(unittest.TestCase):
    def deliver(self, *, alerts_on, delivered=1, free_text=False):
        texts, pushes, done = [], [], threading.Event()

        def push(*args, **kwargs):
            pushes.append(args)
            done.set()
            return delivered
        with mock.patch("telegram_bridge.send_to_owner", side_effect=lambda text: (texts.append(text), done.set())), \
                mock.patch("privacy.redact", lambda text: text), \
                mock.patch.object(whereabouts, "out_of_room", return_value=True), \
                mock.patch.object(phone_push, "ready", return_value=alerts_on), \
                mock.patch.object(phone_push, "send", side_effect=push):
            jarvis.text_question("May I email Sam?", "Send this email?", free_text)
            done.wait(2)
            time.sleep(0.05)
        return texts, pushes

    def test_a_yes_no_goes_to_the_app_instead_of_telegram(self):
        texts, pushes = self.deliver(alerts_on=True)
        self.assertEqual((len(texts), len(pushes)), (0, 1))

    def test_telegram_when_the_alert_did_not_get_through(self):
        texts, pushes = self.deliver(alerts_on=True, delivered=0)
        self.assertEqual((len(texts), len(pushes)), (1, 1))

    def test_telegram_without_alerts_or_for_a_free_text_question(self):
        self.assertEqual([len(x) for x in self.deliver(alerts_on=False)], [1, 0])
        self.assertEqual([len(x) for x in self.deliver(alerts_on=True, free_text=True)], [1, 0])


class HandsFreeAndFeedTest(unittest.TestCase):
    setUp, request, ask = PhoneAppTest.setUp, PhoneAppTest.request, PhoneAppTest.ask  # not its tests

    def wav(self):
        return phone_bridge.to_wav(phone_bridge.np.zeros(1600, "float32"), 16000)

    def listen(self, heard, followup=False):
        self.bridge.transcribe = lambda audio: heard
        status, body = self.request("POST", "/listen" + ("?followup=1" if followup else ""), self.wav(),
                                    {**AUTH, "Content-Type": "audio/wav"})
        return status, body

    def test_the_name_is_needed_at_the_start(self):
        wake = phone_bridge.wake_command
        self.assertEqual(wake("Friday, turn off the lights.", "FRIDAY"), "turn off the lights.")
        self.assertEqual(wake("Hey, Friday what time is it", "FRIDAY"), "what time is it")
        self.assertEqual(wake("Hey Friday.", "FRIDAY"), "")
        self.assertIsNone(wake("I said Friday was fun", "FRIDAY"))
        self.assertIsNone(wake("Fridays are great", "FRIDAY"))

    def test_only_a_named_request_is_answered(self):
        self.assertEqual(json.loads(self.listen("Pass the salt please")[1]), {"ignored": True})
        self.assertEqual(json.loads(self.listen("Hey Friday.")[1]), {"awake": True})
        status, body = self.listen("Friday, lights on")
        self.assertEqual((status, body[:4]), (200, b"RIFF"))

    def test_a_follow_up_needs_no_name_but_noise_is_dropped(self):
        self.assertEqual(self.listen("and the kitchen too", followup=True)[1][:4], b"RIFF")
        self.assertEqual(json.loads(self.listen("Thank you.", followup=True)[1]), {"ignored": True})

    def test_listen_needs_the_key(self):
        self.assertEqual(self.request("POST", "/listen", self.wav(), {"Content-Type": "audio/wav"})[0], 401)

    def test_shortcut_conversations_reach_the_app_but_the_apps_own_do_not_repeat(self):
        self.ask("lights on")  # a Siri Shortcut: no app header
        self.ask("what time is it", **{"X-Jarvis-Client": "app"})
        items = json.loads(self.request("GET", "/inbox?after=0", headers=AUTH)[1])["items"]
        self.assertEqual([(i["who"], i["text"]) for i in items], [("you", "lights on"), ("jarvis", "echo: lights on")])

    def test_the_feed_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "feed.json"
            self.bridge.load_feed(path)
            self.ask("lights on")
            again = phone_bridge.Bridge()
            again.load_feed(path)
            self.assertEqual(again.inbox_after(0)["last"], 2)
            self.assertEqual(again.to_feed("jarvis", "next"), 3)


class AgentBoardTest(unittest.TestCase):
    """The laptop's agent board inside the phone app: a public page, data only with the key, read-only."""
    setUp, request = PhoneAppTest.setUp, PhoneAppTest.request

    def page_server(self):
        """A stand-in for Jarvis's own page server (hud.py); it records what reached it."""
        seen = []

        class Page(phone_bridge.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen.append((self.path, self.headers.get("Host"), self.headers.get("Authorization")))
                stream = self.path == "/events"
                body = b'data: {"type": "hello"}\n\n' if stream else json.dumps({"counts": {"working": 2}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
                self.end_headers()
                self.wfile.write(body)
        server = phone_bridge.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        patcher = mock.patch.object(phone_bridge, "HUD_PORT", server.server_port)
        patcher.start()
        self.addCleanup(patcher.stop)
        return seen

    def test_the_board_page_is_marked_for_the_phone_and_is_the_laptops_page(self):
        status, page = self.request("GET", "/board")
        self.assertEqual(status, 200)
        self.assertIn(b"data-phone", page)  # board.js sends the phone key only when it sees this
        self.assertNotIn(b"data-phone", (phone_bridge.PAGE.parent / "board.html").read_bytes())
        self.assertIn(b"'jarvis-key'", self.request("GET", "/board.js")[1])  # the key the chat page saved
        self.assertEqual(self.request("GET", "/board.css")[0], 200)

    def test_board_data_needs_the_key(self):
        seen = self.page_server()
        for path in phone_bridge.BOARD_DATA:
            self.assertEqual(self.request("GET", path)[0], 401, path)
            self.assertEqual(self.request("GET", path, headers={"Authorization": "Bearer nope"})[0], 401, path)
        self.assertEqual(seen, [])

    def test_board_data_comes_from_jarvis_and_the_key_stays_here(self):
        seen = self.page_server()
        status, body = self.request("GET", "/agents?x=1", headers=AUTH)
        self.assertEqual((status, json.loads(body)), (200, {"counts": {"working": 2}}))
        self.assertEqual(self.request("GET", "/events", headers=AUTH), (200, b'data: {"type": "hello"}\n\n'))
        self.assertEqual(self.request("GET", "/jobs", headers=AUTH)[0], 200)
        port = phone_bridge.HUD_PORT
        self.assertEqual(seen, [(path, f"127.0.0.1:{port}", None) for path in ("/agents", "/events", "/jobs")])

    def test_the_board_can_only_read(self):
        self.page_server()
        for path in ("/agents", "/board", "/session-control", "/command"):
            self.assertEqual(self.request("POST", path, "{}", {**AUTH, "Content-Type": "application/json"})[0], 404, path)

    def test_a_page_server_that_is_down_says_so(self):
        with mock.patch.object(phone_bridge, "HUD_PORT", 1):
            status, body = self.request("GET", "/agents", headers=AUTH)
        self.assertEqual(status, 503)
        self.assertIn("page server", json.loads(body)["error"])

    def test_the_chat_page_links_to_the_board_and_the_cache_keeps_only_the_chat_page(self):
        self.assertIn(b'href="/board"', self.request("GET", "/")[1])
        self.assertIn(b"response.ok && home", self.request("GET", "/sw.js")[1])


class RealListTest(unittest.TestCase):
    def test_a_test_run_never_reads_the_real_alert_list(self):
        self.assertEqual(phone_push.SUBSCRIPTIONS, phone_push.DEFAULT_SUBSCRIPTIONS)
        self.assertFalse(phone_push.ready())
        self.assertEqual(phone_push.send("x", "y"), 0)


if __name__ == "__main__":
    unittest.main()
