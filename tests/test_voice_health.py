"""Inert voice lifecycle regressions: no devices, models, network or desktop tools."""
import queue
import http.client
import json
from http.server import ThreadingHTTPServer
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

import ears
import jarvis
import hud
import voice
import voice_health as health


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.multiple(health, _voice=None, _ears=None, _listener=None,
                                        _phase="starting", _api="not_checked", _text_mode=False,
                                        _output_error=False, _recognition={"reason": "none", "at": None})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_browser_connection_does_not_establish_voice_readiness(self):
        result = health.snapshot("standby", "wake")
        self.assertEqual(result["startup"], "starting")
        for field in ("microphone_active", "microphone_receiving", "listener_alive", "output_active"):
            self.assertFalse(result[field])
        self.assertIsNone(result["voice_lock"])
        self.assertEqual(result["ai_service"], "not_checked")

    def test_health_uses_actual_devices_and_live_pipeline_without_transcript(self):
        source = SimpleNamespace(stream=SimpleNamespace(active=True), mic="Actual mic" * 40,
                                 last_input=time.monotonic(), last_processed=time.monotonic(),
                                 level=0.23, voiceprint=np.ones(2), transcript="PRIVATE")
        speaker = SimpleNamespace(_player=SimpleNamespace(device_name="Actual speaker", _stream=SimpleNamespace(active=True)),
                                  _idle=threading.Event())
        health.bind(voice=speaker, ears=source, listener=SimpleNamespace(is_alive=lambda: True))
        health.phase("ready")
        health.recognition("voice_not_matched")
        result = health.snapshot("standby", "continuous")
        self.assertTrue(result["microphone_receiving"])
        self.assertTrue(result["voice_lock"])
        self.assertEqual(result["input_level"], 0.23)
        self.assertEqual(result["output"], "Actual speaker")
        self.assertEqual(len(result["microphone"]), 160)
        self.assertNotIn("PRIVATE", str(result))
        with self.assertRaises(ValueError):
            health.recognition("PRIVATE arbitrary exception")
        source.last_input = source.last_processed = time.monotonic() - 5
        source.level = float("nan")
        result = health.snapshot("standby", "wake")
        self.assertFalse(result["microphone_receiving"])
        self.assertFalse(result["processing"])
        self.assertEqual(result["input_level"], 0)

    def test_voice_rejection_reports_reason_without_changing_threshold(self):
        source = ears.Ears.__new__(ears.Ears)
        source._phrases = queue.Queue()
        source._phrases.put((np.zeros(16000, dtype=np.int16), True, 0.9))
        source.voiceprint = np.ones(2)
        source.threshold = 0.8
        source._owner_check = mock.Mock(return_value=0.4)
        source.pool = mock.Mock()
        source.transcribe = mock.Mock()
        source._log = mock.Mock()
        self.assertIsNone(source.listen(timeout=0))
        self.assertEqual(source.threshold, 0.8)
        self.assertEqual(health.snapshot("standby", "wake")["recognition"]["reason"], "voice_not_matched")
        source.pool.submit.return_value.result.assert_not_called()

    def test_health_http_endpoint_is_bounded_and_host_guarded(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), hud._Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(hud, "ALLOWED_HOSTS", {f"127.0.0.1:{server.server_port}"}), \
                 mock.patch.object(hud.preferences, "listening_mode", return_value="wake"), \
                 mock.patch.object(hud, "status", side_effect=AssertionError("No system probes")):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                connection.request("GET", "/voice-health")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                body = response.read()
                self.assertLess(len(body), 2000)
                self.assertEqual(json.loads(body)["startup"], "starting")
                connection.close()
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                connection.request("GET", "/voice-health", headers={"Host": "untrusted.example"})
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                connection.close()
        finally:
            server.shutdown()
            server.server_close()


class LifecycleTest(unittest.TestCase):
    def speaker(self, active):
        speaker = voice.Voice.__new__(voice.Voice)
        speaker._idle = threading.Event()
        speaker._lock = threading.Lock()
        speaker._player_lock = threading.Lock()
        speaker._player = mock.Mock()
        speaker._player._stream.active = active
        speaker._gen = 1
        speaker._pending = 1
        speaker._text_q = queue.Queue()
        return speaker

    def test_stopped_output_releases_wait_and_invalidates_queued_generation(self):
        speaker = self.speaker(False)
        # Real wait on a daemon thread makes the pre-fix infinite wait a bounded
        # test failure; the cleanup releases it even on that failure.
        worker = threading.Thread(target=speaker.wait, daemon=True)
        with mock.patch.object(health, "output_failed") as failure:
            worker.start()
            worker.join(1)
            try:
                self.assertFalse(worker.is_alive(), "wait hung after the output stream stopped")
                self.assertEqual(speaker._pending, 0)
                self.assertEqual(speaker._gen, 2)
                failure.assert_called_once()
            finally:
                speaker._idle.set()
                worker.join(1)

    def test_healthy_playback_has_no_duration_cutoff(self):
        speaker = self.speaker(True)
        speaker._idle = mock.Mock()
        speaker._idle.wait.side_effect = [False] * 100 + [True]
        with mock.patch.object(speaker, "stop") as stop:
            speaker.wait()
        stop.assert_not_called()
        self.assertEqual(speaker._pending, 1)

    def test_normal_completion_and_old_callback_after_stop(self):
        speaker = self.speaker(True)
        speaker._done(1, 1)
        self.assertTrue(speaker._idle.is_set())
        speaker.stop()
        speaker._pending = 1
        speaker._idle.clear()
        speaker._done(1, 1)
        self.assertFalse(speaker._idle.is_set())
        self.assertEqual(speaker._pending, 1)

    def test_transcription_failure_does_not_kill_normal_listener(self):
        source = mock.Mock()
        source.listen.side_effect = [RuntimeError("private failure"), ("Jarvis hello", True)]
        turns = jarvis.Turns()
        turns.idle = mock.Mock()
        turns.idle.wait.side_effect = [True, True, StopIteration()]
        with mock.patch.object(jarvis.preferences, "listening_mode", return_value="wake"), \
             mock.patch.object(jarvis.approvals, "waiting", return_value=None), \
             mock.patch.object(jarvis.hud, "emit"), \
             mock.patch.object(jarvis.hud, "commands") as commands, \
             mock.patch.object(health, "recognition") as recognition:
            with self.assertRaises(StopIteration):
                jarvis.listen_loop(source, mock.Mock(), turns)
        self.assertEqual(source.listen.call_count, 2)
        commands.put.assert_called_once_with("hello")
        recognition.assert_any_call("recognition_error")
        recognition.assert_any_call("accepted")


if __name__ == "__main__":
    unittest.main()
