"""Laptop bridge: key + Tailscale login, the dashboard passed through to a (fake) Brain server, one-time pairing
codes, the room microphone's name check, and the PC answering what both microphones heard."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("JARVIS_UNDER_TEST", "1")
import desk_bridge  # noqa: E402
import phone_bridge  # noqa: E402

HOST = "draco420.tailf4c37e.ts.net:8443"
OWNER = {"Tailscale-User-Login": "me@example.com", "Host": HOST}


class FakeBrain(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        FakeBrain.seen.append((self.command, self.path, self.headers.get("Host"), self.headers.get("Origin")))
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for n in range(3):
                self.wfile.write(f"data: {n}\n\n".encode())
                self.wfile.flush()
            return
        body = b"<html>brain page</html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        FakeBrain.seen.append((self.command, self.path, self.headers.get("Host"), self.headers.get("Origin"),
                               self.rfile.read(size)))
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DeskBridgeTest(unittest.TestCase):
    def setUp(self):
        FakeBrain.seen = []
        self.brain = ThreadingHTTPServer(("127.0.0.1", 0), FakeBrain)
        threading.Thread(target=self.brain.serve_forever, daemon=True).start()
        self.addCleanup(self.brain.server_close)
        self.addCleanup(self.brain.shutdown)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for name, value in (("BRAIN_PORT", self.brain.server_port), ("PAIR", Path(folder.name) / "pair.json")):
            patcher = mock.patch.object(desk_bridge, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(phone_bridge, "owner_login", return_value="me@example.com")
        patcher.start()
        self.addCleanup(patcher.stop)
        desk_bridge._heard_at_pc.clear()
        self.bridge = desk_bridge.Bridge()
        self.bridge.token = "laptop-key"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), desk_bridge.make_handler(self.bridge))
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            connection.request(method, path, body, {**OWNER, **(headers or {})})
            response = connection.getresponse()
            return response.status, response.read(), response
        finally:
            connection.close()

    def key(self, key="laptop-key"):
        return {"Authorization": "Bearer " + key}

    # ---------- the gate ----------
    def test_the_page_needs_the_key_and_the_owners_login(self):
        status, _, response = self.request("GET", "/")
        self.assertEqual((status, response.headers["Location"]), (303, "/login"))
        self.assertEqual(self.request("GET", "/brain-data", headers=self.key("wrong"))[0], 401)
        self.assertEqual(self.request("GET", "/brain-data", headers={**self.key(), "Tailscale-User-Login": "x@y.z"})[0], 401)
        self.assertEqual(self.request("GET", "/", headers=self.key())[1], b"<html>brain page</html>")

    def test_login_sets_a_strict_cookie_that_opens_the_page(self):
        status, _, response = self.request("POST", "/login", json.dumps({"key": "laptop-key"}), {"Content-Type": "application/json"})
        cookie = response.headers["Set-Cookie"]
        self.assertEqual(status, 200)
        for part in ("Secure", "HttpOnly", "SameSite=Strict"):
            self.assertIn(part, cookie)
        self.assertEqual(self.request("GET", "/", headers={"Cookie": cookie.split(";")[0]})[0], 200)
        self.assertEqual(self.request("POST", "/login", json.dumps({"key": "nope"}), {"Content-Type": "application/json"})[0], 401)

    def test_lockout_after_repeated_wrong_keys(self):
        for _ in range(desk_bridge.LOCKOUT_FAILS):
            self.request("GET", "/x", headers=self.key("wrong"))
        self.assertEqual(self.request("GET", "/x", headers=self.key())[0], 401)

    # ---------- the dashboard ----------
    def test_requests_reach_brain_as_if_from_the_pc(self):
        origin = f"https://{HOST}"
        status, body, _ = self.request("POST", "/command", '{"text": "hi"}',
                                       {**self.key(), "Content-Type": "application/json", "Origin": origin})
        self.assertEqual((status, json.loads(body)), (200, {"ok": True}))
        method, path, host, sent_origin, sent = FakeBrain.seen[-1]
        self.assertEqual((path, host, sent_origin, sent), ("/command", f"127.0.0.1:{self.brain.server_port}",
                                                          f"http://127.0.0.1:{self.brain.server_port}", b'{"text": "hi"}'))

    def test_other_websites_are_refused(self):
        status, _, _ = self.request("POST", "/command", '{"text": "hi"}',
                                    {**self.key(), "Content-Type": "application/json", "Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(FakeBrain.seen, [])

    def test_the_live_event_stream_passes_through(self):
        status, body, _ = self.request("GET", "/events", headers=self.key())
        self.assertEqual((status, body), (200, b"data: 0\n\ndata: 1\n\ndata: 2\n\n"))

    # ---------- pairing ----------
    def test_a_code_works_once(self):
        code = desk_bridge.new_pair_code()
        pair = lambda c: self.request("POST", "/laptop/pair", json.dumps({"code": c}), {"Content-Type": "application/json"})
        self.assertEqual(pair("000000" if code != "000000" else "111111")[0], 403)
        status, body, _ = pair(code)
        self.assertEqual((status, json.loads(body)), (200, {"key": "laptop-key"}))
        self.assertEqual(pair(code)[0], 403)

    def test_an_old_code_or_another_login_fails(self):
        code = desk_bridge.new_pair_code()
        data = json.loads(desk_bridge.PAIR.read_text())
        self.assertNotIn(code, json.dumps(data))  # only its hash is kept
        status, _, _ = self.request("POST", "/laptop/pair", json.dumps({"code": code}),
                                    {"Content-Type": "application/json", "Tailscale-User-Login": "x@y.z"})
        self.assertEqual(status, 403)
        data["until"] = time.time() - 1
        desk_bridge.PAIR.write_text(json.dumps(data))
        self.assertEqual(self.request("POST", "/laptop/pair", json.dumps({"code": code}), {"Content-Type": "application/json"})[0], 403)

    def test_setup_files_are_public_linux_files_with_this_pcs_address(self):
        status, body, _ = self.request("GET", "/laptop")
        self.assertEqual(status, 200)
        self.assertIn(f'URL="https://{HOST}"'.encode(), body)
        self.assertNotIn(b"\r\n", body)
        self.assertNotIn(b"laptop-key", body)
        status, body, _ = self.request("GET", "/laptop/satellite.py")
        self.assertEqual(status, 200)
        self.assertNotIn(b"\r\n", body)

    # ---------- the room microphone ----------
    def listen(self, heard, followup=False):
        self.bridge.transcribe = lambda audio: heard
        self.bridge.speak = lambda text: phone_bridge.to_wav(phone_bridge.np.zeros(160, "float32"), 16000)
        self.bridge.on_message = lambda text, reply: reply("Done: " + text, None)
        wav = phone_bridge.to_wav(phone_bridge.np.zeros(1600, "float32"), 16000)
        with mock.patch.object(desk_bridge.time, "sleep"):
            return self.request("POST", "/room/listen" + ("?followup=1" if followup else ""), wav,
                                {**self.key(), "Content-Type": "audio/wav"})

    def test_only_his_name_wakes_the_room_mic(self):
        self.assertEqual(json.loads(self.listen("Friday, lights off")[1]), {"ignored": True})
        self.assertEqual(json.loads(self.listen("Hey Jarvis.")[1]), {"awake": True})
        status, body, response = self.listen("Jarvis, lights off")
        self.assertEqual((status, body[:4], response.headers["X-Jarvis-Reply"]), (200, b"RIFF", "Done%3A%20lights%20off"))
        self.assertEqual(self.listen("and the fan", followup=True)[0], 200)

    def test_what_the_pc_already_heard_is_answered_once(self):
        desk_bridge.pc_heard("Jarvis, turn the lights off")
        self.assertEqual(json.loads(self.listen("Jarvis, turn the lights off.")[1]),
                         {"ignored": True, "why": "heard at the PC"})
        self.assertEqual(self.listen("Jarvis, what's the weather")[0], 200)


if __name__ == "__main__":
    unittest.main()
