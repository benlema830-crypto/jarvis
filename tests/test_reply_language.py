import unittest
from unittest import mock

import reply_language as languages
import voice
import voicestudio_voice


class ReplyLanguageTest(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        for name, fake in [("read", lambda: dict(self.saved)), ("update", lambda **changes: self.saved.update(changes))]:
            patcher = mock.patch.object(languages.preferences, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_english_is_the_default_and_adds_nothing(self):
        self.assertEqual(languages.code(), "")
        self.assertEqual(languages.prompt(), "")
        self.assertIsNone(languages.voice_code())

    def test_choosing_a_language_by_any_of_its_names(self):
        self.assertEqual(languages.choose("Spanish"), "es")
        self.assertEqual(self.saved["reply_language"], {"code": "es", "name": "Spanish"})
        self.assertEqual(languages.code(), "es")
        self.assertIn("answer in Spanish", languages.prompt())
        self.assertEqual(languages.voice_code(), "es")
        self.assertEqual(languages.choose("  deutsch "), "de")
        self.assertEqual(languages.choose("English"), "")
        self.assertEqual(languages.code(), "")

    def test_only_checked_languages_send_a_code_to_the_voice(self):
        languages.choose("japanese")
        self.assertEqual(languages.code(), "ja")
        self.assertIsNone(languages.voice_code())   # right only when the engine detects it itself

    def test_an_unknown_language_is_refused_with_the_list(self):
        with self.assertRaises(ValueError) as error:
            languages.choose("Klingon")
        self.assertIn("Spanish", str(error.exception))
        self.assertEqual(self.saved, {})

    def test_a_bad_saved_value_means_english(self):
        self.saved["reply_language"] = {"code": "xx"}
        self.assertEqual(languages.code(), "")
        self.saved["reply_language"] = "es"
        self.assertEqual(languages.code(), "")

    def test_tool_sets_the_voice_and_says_what_was_checked(self):
        import tools
        fake = mock.Mock(engine="voicestudio", language="")
        with mock.patch.object(tools, "VOICE", fake):
            run = tools.TOOLS_BY_NAME["reply_language"]
            self.assertIn("was checked", run.call({"language": "German"}))
            self.assertEqual(fake.language, "de")
            self.assertIn("hasn't been checked", run.call({"language": "Italian"}))
            fake.engine = "qwen"
            self.assertIn("Qwen voice can't speak it", run.call({"language": "Hindi"}))
            self.assertEqual(run.call({"language": "english"}), "Back to English from now on.")
            self.assertEqual(fake.language, "")


class SpeechInAnotherLanguageTest(unittest.TestCase):
    def test_voicestudio_gets_the_language_only_when_given(self):
        studio = voicestudio_voice.VoiceStudioEngine.__new__(voicestudio_voice.VoiceStudioEngine)
        studio.profile, studio.speed, studio.seed, studio.url = "p", 1.0, None, "http://x"
        studio.session = mock.Mock()
        studio.session.post.return_value = mock.Mock(ok=True, content=b"\x00\x00")
        studio.render("Hola.", "es")
        self.assertEqual(studio.session.post.call_args.kwargs["json"]["language"], "es")
        studio.render("Hello.")
        self.assertNotIn("language", studio.session.post.call_args.kwargs["json"])

    def test_signs_are_left_for_the_voice_when_not_english(self):
        self.assertEqual(voice.clean_for_speech("It's 20% and 5°C."), "It's 20 percent and 5 degrees Celsius.")
        self.assertEqual(voice.clean_for_speech("Es 20% y 5°C.", english=False), "Es 20% y 5°C.")
        self.assertEqual(voice.clean_for_speech("Mira **esto** en https://example.com ahora.", english=False), "Mira esto en ahora.")

    def test_sentences_end_on_hindi_and_cjk_full_stops(self):
        self.assertEqual(len(voice.sentences("शुभ संध्या, सर। कल आपकी दो बैठकें हैं।")), 2)
        self.assertEqual(len(voice.sentences("こんばんは。明日は会議が二つあります。")), 2)
        self.assertEqual(voice.sentences("Done, sir. Anything else?"), ["Done, sir.", "Anything else?"])


if __name__ == "__main__":
    unittest.main()
