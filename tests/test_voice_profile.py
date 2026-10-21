import os
import tempfile
import unittest
from unittest import mock

import numpy as np
import voice


class CustomVoiceTest(unittest.TestCase):
    def test_archive_is_snapshot_and_can_be_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "voice.bin")
            with open(path, "wb") as handle:
                np.savez(handle, assistant_custom=np.ones((510, 1, 256)))
            with mock.patch.object(voice, "VOICE_PROFILE", {"voice_file": path}):
                result = voice.custom_voice_style()
            os.remove(path)
            self.assertEqual(result.shape, (510, 1, 256))
            self.assertEqual(result.dtype, np.float32)
            self.assertEqual(float(result.mean()), 1)

    def test_local_copy_refuses_elevenlabs_even_with_key(self):
        instance = voice.Voice.__new__(voice.Voice)
        instance.eleven = None
        with mock.patch.object(voice, "KOKORO_ONLY", True), \
             mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test"}), \
             mock.patch.object(voice, "ElevenLabsEngine") as engine:
            self.assertEqual(instance.switch_engine("elevenlabs"), "kokoro")
            engine.assert_not_called()

    def test_original_still_allows_elevenlabs(self):
        instance = voice.Voice.__new__(voice.Voice)
        instance.eleven = None
        instance.speed = 1.0
        with mock.patch.object(voice, "KOKORO_ONLY", False), \
             mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test"}), \
             mock.patch.object(voice, "ElevenLabsEngine") as engine:
            self.assertEqual(instance.switch_engine("elevenlabs"), "elevenlabs")
            engine.assert_called_once()
