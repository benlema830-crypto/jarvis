"""Phone bridge: loopback only, bearer token + Tailscale login required, replies come from the queue."""
import http.client
import json
import threading
from urllib.parse import unquote
import unittest
from unittest import mock

import phone_bridge


class PhoneBridgeTest(unittest.TestCase):
    def setUp(self):
        self.bridge = phone_bridge.Bridge()
        self.bridge.token = "secret-token"
        self.bridge.on_message = lambda text, reply, voice: reply(
            "echo: " + text, phone_bridge.to_wav(phone_bridge.np.zeros(240, "float32"), 24000) if voice else None)
        self.server = phone_bridge.ThreadingHTTPServer(("127.0.0.1", 0), phone_bridge.make_handler(self.bridge))
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        patcher = mock.patch.object(phone_bridge, "owner_login", return_value="")
        self.owner = patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def ask(self, text="hi", token="secret-token", **extra):
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}", **extra}
        status, body = self.request("POST", "/ask", json.dumps({"text": text}), headers)
        return status, json.loads(body)

    def test_reply_comes_back(self):
        self.assertEqual(self.ask("lights on"), (200, {"reply": "echo: lights on"}))

    def test_wrong_or_missing_token_refused(self):
        self.assertEqual(self.ask(token="nope")[0], 401)
        status, _ = self.request("POST", "/ask", json.dumps({"text": "hi"}), {"Content-Type": "application/json"})
        self.assertEqual(status, 401)

    def test_lockout_after_repeated_failures(self):
        for _ in range(phone_bridge.LOCKOUT_FAILS):
            self.ask(token="nope")
        self.assertEqual(self.ask()[0], 401)

    def test_tailscale_login_enforced_when_set(self):
        self.owner.return_value = "me@example.com"
        self.assertEqual(self.ask()[0], 401)
        self.assertEqual(self.ask(**{"Tailscale-User-Login": "someone@else.com"})[0], 401)
        self.assertEqual(self.ask(**{"Tailscale-User-Login": "Me@Example.com"})[0], 200)

    def test_bad_requests(self):
        auth = {"Authorization": "Bearer secret-token"}
        self.assertEqual(self.request("POST", "/ask", "text=hi", {**auth, "Content-Type": "text/plain"})[0], 400)
        self.assertEqual(self.ask("   ")[0], 400)
        status, body = self.request("POST", "/", "{}", auth)
        self.assertEqual(status, 404)
        self.assertIn("slash ask", json.loads(body)["reply"])  # a Shortcut speaks the fix

    def test_page_and_health_need_no_token(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"JARVIS", body)
        self.assertNotIn(b"secret-token", body)
        self.assertEqual(self.request("GET", "/health")[0], 200)

    def test_slow_turn_does_not_hang_the_phone(self):
        self.bridge.on_message = lambda text, reply, voice: None
        with mock.patch.object(phone_bridge, "REPLY_SECONDS", 0.2):
            self.assertIn("Still working", self.ask()[1]["reply"])

    def test_voice_reply_is_wav_with_text_header(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("POST", "/voice", json.dumps({"text": "time?"}),
                               {"Content-Type": "application/json", "Authorization": "Bearer secret-token"})
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(response.getheader("Content-Type"), "audio/wav")
            self.assertEqual(unquote(response.getheader("X-Jarvis-Reply")), "echo: time?")
            self.assertTrue(body.startswith(b"RIFF"))
        finally:
            connection.close()

    def test_voice_falls_back_to_text_without_audio(self):
        self.bridge.on_message = lambda text, reply, voice: reply("no audio")
        status, _ = self.request("POST", "/voice", json.dumps({"text": "hi"}),
                                 {"Content-Type": "application/json", "Authorization": "Bearer secret-token"})
        self.assertEqual(status, 200)

    def test_voice_route_speaks_problems_and_busy_answers(self):
        self.bridge.speak = lambda text: phone_bridge.to_wav(phone_bridge.np.zeros(24, "float32"), 24000)
        voice = {"Content-Type": "application/json", "Authorization": "Bearer secret-token"}
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("POST", "/voice", json.dumps({"text": " "}), voice)
            response = connection.getresponse()
            response.read()
            self.assertEqual((response.status, response.getheader("Content-Type")), (400, "audio/wav"))
            self.assertIn("empty message", unquote(response.getheader("X-Jarvis-Reply")))
        finally:
            connection.close()
        self.bridge.on_message = lambda text, reply, voice: reply("still here")  # no audio from the turn
        status, body = self.request("POST", "/voice", json.dumps({"text": "hi"}), voice)
        self.assertTrue(body.startswith(b"RIFF"))
        self.assertEqual(self.ask(token="nope")[0], 401)  # strangers get no audio
        status, body = self.request("POST", "/voice", "{}", {"Content-Type": "application/json"})
        self.assertFalse(body.startswith(b"RIFF"))

    def test_server_binds_loopback_only(self):
        with mock.patch.object(phone_bridge, "load_token", return_value="t"), \
                mock.patch.object(phone_bridge, "ThreadingHTTPServer") as server:
            bridge = phone_bridge.Bridge()
            self.assertTrue(bridge.start())
            self.assertEqual(server.call_args[0][0][0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
