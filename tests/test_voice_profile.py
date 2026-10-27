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


class VoiceStudioTest(unittest.TestCase):
    def test_render_decodes_pcm_and_sends_profile(self):
        import voicestudio_voice
        engine = voicestudio_voice.VoiceStudioEngine()
        reply = mock.Mock(ok=True, content=np.array([0, 16384, -32768], dtype="<i2").tobytes())
        with mock.patch.object(engine.session, "post", return_value=reply) as post:
            samples = engine.render("Good evening, sir.")
        self.assertEqual(post.call_args.kwargs["json"]["voice"], voicestudio_voice.DEFAULT_PROFILE)
        self.assertEqual(post.call_args.kwargs["json"]["response_format"], "pcm")
        np.testing.assert_allclose(samples, [0, 0.5, -1])

    def test_closed_app_falls_back_to_kokoro(self):
        import voicestudio_voice
        instance = voice.Voice.__new__(voice.Voice)
        instance.studio = mock.Mock()
        instance.studio.render.side_effect = voicestudio_voice.VoiceStudioError("VoiceStudio isn't running")
        instance._studio_failures = 0
        instance.local = instance.eleven = None
        instance.voice, instance.speed = "bm_george", 1.0
        instance.kokoro = mock.Mock()
        instance.kokoro.create.return_value = (np.ones(10), 24000)
        instance._reopen_studio = mock.Mock()
        with mock.patch.object(voice.hud, "emit"):
            pieces = list(instance._render("Hello."))
        self.assertEqual(len(pieces), 1)
        instance.kokoro.create.assert_called_once()
        self.assertEqual(instance.engine, "voicestudio")  # stays chosen; the next sentence retries it
        instance._reopen_studio.assert_called_once()  # reopened in the background

    def test_keep_alive_reopens_a_closed_voicestudio_once(self):
        instance = voice.Voice.__new__(voice.Voice)
        instance.studio = mock.Mock()
        instance.studio.running.return_value = False
        instance._studio_reopening, instance._studio_retry_at = False, 0.0
        instance._reopen_studio = mock.Mock()
        with mock.patch.object(voice.threading, "Thread") as thread:
            instance._check_studio()
            instance._check_studio()  # already reopening: no second launch
        thread.assert_called_once_with(target=instance._reopen_studio, daemon=True)
        self.assertTrue(instance._studio_reopening)
        instance._studio_reopening, instance.studio.running.return_value = False, True
        with mock.patch.object(voice.threading, "Thread") as thread:
            instance._check_studio()  # running fine: nothing to do
            instance.studio = None
            instance._check_studio()  # another voice chosen: leave VoiceStudio alone
        thread.assert_not_called()

    def test_launch_never_starts_a_second_copy(self):
        import voicestudio_voice
        engine = voicestudio_voice.VoiceStudioEngine()
        with mock.patch.object(engine, "running", return_value=False), \
                mock.patch.object(voicestudio_voice, "_app_processes", return_value={123}), \
                mock.patch.object(voicestudio_voice.subprocess, "Popen") as popen:
            self.assertFalse(engine.launch())
        popen.assert_not_called()

    def test_no_waiting_on_voicestudio_while_it_reopens(self):
        instance = voice.Voice.__new__(voice.Voice)
        instance.studio = mock.Mock()
        instance._studio_reopening = True
        instance.local = instance.eleven = None
        instance.voice, instance.speed = "bm_george", 1.0
        instance.kokoro = mock.Mock()
        instance.kokoro.create.return_value = (np.ones(10), 24000)
        self.assertEqual(len(list(instance._render("Hello."))), 1)
        instance.studio.render.assert_not_called()
        instance.studio = mock.Mock()  # once it's back, it's used again
        instance._studio_reopening = False
        instance.studio.render.return_value = np.ones(5, dtype=np.float32)
        instance._studio_failures = 0
        list(instance._render("Hello."))
        instance.studio.render.assert_called_once()

    def test_switching_between_voicestudio_and_kokoro(self):
        instance = voice.Voice.__new__(voice.Voice)
        instance.eleven = instance.local = instance.studio = None
        instance.speed = 1.0
        with mock.patch.object(voice.threading, "Thread"):
            self.assertEqual(instance.switch_engine("voicestudio"), "voicestudio")
        self.assertEqual(instance.switch_engine("kokoro"), "kokoro")
        self.assertIsNone(instance.studio)


class VoiceStudioProfilesTest(unittest.TestCase):
    PROFILES = [{"id": "9e78e6cd", "name": "J.A.R.V.I.S"}, {"id": "27c8e8a9", "name": "JARVIS 2.0"}]

    def test_every_saved_voice_is_a_choice_and_names_resolve_to_ids(self):
        import voicestudio_voice
        with mock.patch.object(voicestudio_voice, "profiles", return_value=self.PROFILES):
            choices, current = voice.voice_choices("voicestudio:J.A.R.V.I.S")
        ids = [c["id"] for c in choices]
        self.assertEqual(ids[:2], ["voicestudio:9e78e6cd", "voicestudio:27c8e8a9"])
        self.assertIn("kokoro", ids)
        self.assertEqual(current, "voicestudio:9e78e6cd")

    def test_profile_list_is_reused_briefly_unless_a_fresh_one_is_asked_for(self):
        import voicestudio_voice
        with mock.patch.object(voicestudio_voice, "_profiles_cache", (0.0, [])), \
                mock.patch.object(voicestudio_voice, "_fetch_profiles", return_value=self.PROFILES) as fetch:
            self.assertEqual(voicestudio_voice.profiles(), self.PROFILES)
            voicestudio_voice.profiles()[0]["name"] = "changed by a caller"
            self.assertEqual(voicestudio_voice.profiles(), self.PROFILES)
            self.assertEqual(fetch.call_count, 1)
            voicestudio_voice.profiles(max_age=0)
            self.assertEqual(fetch.call_count, 2)

    def test_closed_app_still_lists_the_current_voice(self):
        import voicestudio_voice
        with mock.patch.object(voicestudio_voice, "profiles", return_value=[]):
            choices, current = voice.voice_choices("voicestudio:27c8e8a9")
        self.assertEqual(choices[0]["id"], "voicestudio:27c8e8a9")
        self.assertEqual(current, "voicestudio:27c8e8a9")

    def test_switching_between_voicestudio_voices_keeps_the_engine(self):
        instance = voice.Voice.__new__(voice.Voice)
        instance.eleven = instance.local = instance.studio = None
        instance.speed = 1.0
        with mock.patch.object(voice.threading, "Thread"):
            instance.switch_engine("voicestudio:9e78e6cd")
            engine = instance.studio
            self.assertEqual(instance.switch_engine("voicestudio:27c8e8a9"), "voicestudio")
        self.assertIs(instance.studio, engine)  # no reload, the next sentence uses the new voice
        self.assertEqual(instance.choice, "voicestudio:27c8e8a9")
