"""The desktop app's Mute: hud.update_settings({"mic_muted": ...}) reaches the ears, and the ears hear only silence."""
import os
import unittest
from unittest import mock

import numpy as np

os.environ.setdefault("JARVIS_UNDER_TEST", "1")
import hud  # noqa: E402


class MicMuteTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, hud, "on_mic", hud.on_mic)
        self.addCleanup(setattr, hud, "mic_muted", hud.mic_muted)

    def test_mute_and_unmute_reach_the_ears(self):
        calls = []
        hud.on_mic = calls.append
        with mock.patch.object(hud, "emit"), mock.patch.object(hud, "voice_settings", return_value={}):
            self.assertTrue(hud.update_settings({"mic_muted": True})["mic_muted"])
            self.assertFalse(hud.update_settings({"mic_muted": False})["mic_muted"])
        self.assertEqual(calls, [True, False])

    def test_rejects_a_non_boolean_or_a_missing_microphone(self):
        hud.on_mic = None
        with self.assertRaises(ValueError):
            hud.update_settings({"mic_muted": True})
        hud.on_mic = lambda muted: None
        with self.assertRaises(ValueError):
            hud.update_settings({"mic_muted": "yes"})
        self.assertFalse(hud.mic_muted)

    def test_muted_ears_pass_on_only_silence(self):
        import queue
        from ears import Ears
        ears = Ears.__new__(Ears)  # no microphone or models: only the audio callback is exercised
        ears._blocks, ears.muted = queue.Queue(), False
        sound = np.full((4, 1), 1200, dtype=np.int16)
        ears._receive(sound)
        ears.muted = True
        ears._receive(sound)
        self.assertTrue(ears._blocks.get_nowait().any())
        self.assertFalse(ears._blocks.get_nowait().any())


if __name__ == "__main__":
    unittest.main()
