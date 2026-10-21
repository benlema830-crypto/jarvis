"""Inert Stage 3 checks: every screen/window effect is mocked."""
import base64
import http.client
import io
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

from PIL import Image

import brain
import visual_modes as vm


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.capture = mock.Mock(return_value="mock-frame")
        self.observe = mock.Mock(return_value={"kind": "app", "process": "code.exe"})
        self.modes = vm.VisualModes(self.capture, self.observe, lambda: self.now)
        self.addCleanup(self.modes.stop)

    def start(self, mode="focus", minutes=1, target="Code.exe"):
        return self.modes.start(mode, minutes, target, threaded=False)

    def tick(self, process="code.exe", kind="app", seconds=5):
        self.now += seconds
        self.modes.heartbeat(self.modes.session)
        self.observe.return_value = {"kind": kind, "process": process}
        self.modes.step()

    def test_import_snapshot_and_idle_tick_observe_nothing(self):
        self.assertEqual(self.modes.snapshot()["state"], "off")
        self.modes.step()
        self.capture.assert_not_called()
        self.observe.assert_not_called()

    def test_watch_cadence_no_burst_and_no_focus_observation(self):
        self.start("watch")
        self.assertEqual(self.modes.snapshot()["state"], "starting")
        self.modes.step()
        self.assertEqual(self.modes.snapshot()["preview"], "mock-frame")
        for _ in range(20):
            self.modes.step()
        self.capture.assert_called_once()
        self.tick(seconds=4.9)
        self.capture.assert_called_once()
        self.tick(seconds=0.1)
        self.assertEqual(self.capture.call_count, 2)
        self.observe.assert_not_called()

    def test_focus_counts_only_evidenced_departure_episodes(self):
        self.start()
        self.tick("chrome.exe")
        self.tick("chrome.exe")
        self.assertEqual(self.modes.drifts, 0, "Cannot count before seeing target")
        self.tick()
        self.tick("chrome.exe")
        self.assertEqual(self.modes.drifts, 0)
        self.tick("chrome.exe")
        self.assertEqual(self.modes.drifts, 1)
        self.tick("explorer.exe")
        self.tick(kind="protected")
        self.tick("chrome.exe")
        self.assertEqual(self.modes.drifts, 1)
        self.tick()
        self.tick("chrome.exe")
        self.tick("chrome.exe")
        self.assertEqual(self.modes.drifts, 2)
        self.assertEqual(self.modes.evidence[-1]["process"], "chrome.exe")
        self.capture.assert_not_called()

    def test_unknown_and_protected_samples_break_evidence(self):
        self.start()
        self.tick()
        self.tick("chrome.exe")
        self.tick(kind="protected", process="private-work-title")
        self.assertEqual(self.modes.observation, "Work app hidden.")
        self.assertNotIn("private-work-title", json.dumps(self.modes.snapshot()))
        self.tick("chrome.exe")
        self.assertEqual(self.modes.drifts, 0)
        self.tick(kind="unknown")
        self.tick("chrome.exe")
        self.assertEqual(self.modes.drifts, 0)
        self.tick("chrome.exe")
        self.assertEqual(self.modes.drifts, 1)

    def test_browser_tabs_not_classified(self):
        self.start(target="CHROME.EXE")
        self.tick("chrome.exe")
        self.tick("chrome.exe")
        self.assertEqual(self.modes.drifts, 0)

    def test_deadline_and_lease_stop_without_further_capture(self):
        for duration, elapsed, reason in [(1, 60, "Duration"), (2, 15, "heartbeat")]:
            self.start("watch", duration)
            self.modes.step()
            calls = self.capture.call_count
            self.now += elapsed
            self.modes.step()
            self.assertEqual(self.modes.state, "off")
            self.assertIn(reason, self.modes.reason)
            self.assertIsNone(self.modes.preview)
            self.assertEqual(self.capture.call_count, calls)

    def test_expired_heartbeat_cannot_revive_session(self):
        self.start("watch")
        self.now += vm.LEASE
        self.modes.heartbeat(self.modes.session)
        self.assertEqual(self.modes.state, "off")
        self.modes.step()
        self.capture.assert_not_called()

    def test_focus_keeps_running_without_page_heartbeat(self):
        self.start(minutes=25)
        self.now += vm.LEASE * 4
        self.modes.step()
        self.assertEqual(self.modes.state, "running")
        self.now += 25 * 60
        self.modes.step()
        self.assertIn("Duration", self.modes.reason)

    def test_stop_clears_frame_and_requires_explicit_restart(self):
        self.start("watch")
        self.modes.step()
        old = self.modes.session
        self.modes.stop()
        self.modes.step()
        self.assertEqual(self.modes.state, "off")
        self.assertIsNone(self.modes.preview)
        self.capture.assert_called_once()
        with self.assertRaises(ValueError):
            self.modes.heartbeat(old)
        self.start("watch")
        with self.assertRaises(ValueError):
            self.modes.heartbeat(old)
        self.assertEqual(self.modes.samples, 0)

    def test_inflight_stop_discards_frame_and_blocks_restart_until_cleanup(self):
        entered, release = threading.Event(), threading.Event()
        def blocking_capture():
            entered.set()
            release.wait(2)
            return "late-frame"
        self.modes.capture = blocking_capture
        self.modes.start("watch", 1)
        self.assertTrue(entered.wait(1))
        try:
            self.assertEqual(self.modes.stop()["state"], "stopping")
            with self.assertRaises(ValueError):
                self.modes.start("focus", 1, "Code.exe")
        finally:
            release.set()
            self.modes.worker.join(2)
        self.assertFalse(self.modes.worker.is_alive())
        self.assertEqual(self.modes.state, "off")
        self.assertIsNone(self.modes.preview)
        self.assertEqual(self.modes.samples, 0)

    def test_slow_capture_expiring_midflight_discards_result(self):
        def slow():
            self.now += 16
            return "late"
        self.modes.capture = slow
        self.start("watch")
        self.modes.step()
        self.assertEqual(self.modes.state, "off")
        self.assertIsNone(self.modes.preview)

    def test_fixed_errors_do_not_leak_native_exception_details(self):
        for mode, effect in [("watch", self.capture), ("focus", self.observe)]:
            effect.side_effect = PermissionError("private title or device path")
            self.start(mode)
            self.modes.step()
            value = self.modes.snapshot()
            self.assertEqual(value["state"], "error")
            self.assertIn("Windows desktop access", value["error"])
            self.assertNotIn("private title", json.dumps(value))
            self.assertIsNone(value["preview"])

    def test_validation_and_overlapping_start(self):
        for mode, minutes, target in [("eyes", 1, ""), ("watch", 31, ""), ("focus", 121, "a.exe"),
                                      ("focus", 1, "https://tab"), ("watch", True, ""), ("watch", 1.5, "")]:
            with self.assertRaises(ValueError):
                self.start(mode, minutes, target)
        self.capture.assert_not_called()
        self.observe.assert_not_called()
        self.start()
        with self.assertRaises(ValueError):
            self.start("watch")
        for payload in [[], {"action": "unknown"}, {"action": "heartbeat", "session": "wrong"}]:
            with self.assertRaises(ValueError):
                self.modes.request(payload)

    def test_evidence_bounded_and_resets_between_sessions(self):
        self.start(minutes=120)
        for _ in range(30):
            self.tick()
            self.tick("chrome.exe")
            self.tick("chrome.exe")
        self.assertEqual(self.modes.drifts, 30)
        self.assertEqual(len(self.modes.evidence), 20)
        self.modes.stop()
        self.start()
        self.assertFalse(self.modes.evidence)
        self.assertEqual(self.modes.drifts, 0)


class AdapterTests(unittest.TestCase):
    def test_preview_uses_existing_mask_and_closes_frame(self):
        image = Image.new("RGB", (1920, 1080), "black")
        with mock.patch("worksafe.grab", return_value=image) as grab, mock.patch.object(image, "close", wraps=image.close) as close:
            frame = vm.screen_preview()
            grab.assert_called_once_with()
            close.assert_called_once()
        decoded = Image.open(io.BytesIO(base64.b64decode(frame)))
        self.assertEqual(decoded.size, (960, 540))
        self.assertEqual(decoded.getpixel((200, 200)), (0, 0, 0))
        decoded.close()

    def test_protected_foreground_never_returns_process_or_title(self):
        with mock.patch("worksafe.win32gui.GetForegroundWindow", return_value=123), \
             mock.patch("worksafe.is_blocked", return_value=True), \
             mock.patch("worksafe._process_name") as process:
            self.assertEqual(vm.foreground_app(), {"kind": "protected"})
            process.assert_not_called()


class HttpTests(unittest.TestCase):
    def test_real_companion_routes_without_running_supervisor_or_capture(self):
        # Extract the actual nested Handler using an inert server constructor.
        holder = {}
        def construct(address, handler):
            holder["handler"] = handler
            return mock.Mock()
        fake = vm.VisualModes(capture=mock.Mock(side_effect=AssertionError("No capture")),
                              observe=mock.Mock(side_effect=AssertionError("No observation")))
        with mock.patch("http.server.ThreadingHTTPServer", side_effect=construct), mock.patch.object(vm, "controller", fake):
            brain.serve()
        server = ThreadingHTTPServer(("127.0.0.1", 0), holder["handler"])
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        def call(method, path="/visual-modes", payload=None, headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            fields = {"Host": "127.0.0.1:7781", "Content-Type": "application/json"}
            fields.update(headers or {})
            connection.request(method, path, body=json.dumps(payload) if payload is not None else None, headers=fields)
            response = connection.getresponse()
            result = response.status, response.getheader("Cache-Control"), response.read()
            connection.close()
            return result
        try:
            code, cache, body = call("GET")
            self.assertEqual((code, cache), (200, "no-store"))
            self.assertEqual(json.loads(body)["state"], "off")
            self.assertEqual(call("POST", payload={"action": "stop"})[0], 200)
            self.assertEqual(call("POST", payload={"action": "start", "mode": "eyes", "minutes": 1})[0], 400)
            self.assertEqual(call("POST", payload=[])[0], 400)
            self.assertEqual(call("POST", payload={"action": "start"}, headers={"Origin": "https://other.example"})[0], 403)
            self.assertEqual(call("GET", headers={"Host": "other.example"})[0], 403)
            self.assertEqual(call("POST", payload={}, headers={"Content-Type": "text/plain"})[0], 400)
            self.assertEqual(call("GET", "/modes.js")[0], 200)
            # Valid starts reach only a mock controller; no native effects.
            with mock.patch.object(fake, "start", return_value={"state": "starting"}) as start:
                self.assertEqual(call("POST", payload={"action": "start", "mode": "focus", "minutes": 25, "target": "Code.exe"})[0], 200)
                start.assert_called_once_with("focus", 25, "Code.exe", callouts=True)
            fake.start("focus", 1, "Code.exe", threaded=False)
            self.assertEqual(call("POST", payload={"action": "heartbeat", "session": fake.session})[0], 200)
            # Brain's existing Stop also stops visual modes even if Blue is offline.
            with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
                self.assertEqual(call("POST", "/stop", {})[0], 503)
            self.assertEqual(fake.state, "off")
            fake.capture.assert_not_called()
            fake.observe.assert_not_called()
        finally:
            fake.stop()
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
