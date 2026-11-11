"""Inert tests for tasks, documents, Telegram audio/routing, Eyes, HOLO, notifications and web sources."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import numpy as np

import codex_brain
import holo_bridge
import knowledge
import tasks
import telegram_bridge
import voice


class WebSourcesTest(unittest.TestCase):
    def test_only_http_links_deduplicated(self):
        item = {"type": "webSearch", "results": [
            {"url": "https://a.example/x", "title": "A"}, {"url": "https://a.example/x", "title": "dup"},
            {"url": "javascript:alert(1)", "title": "bad"}, {"url": "http://b.example", "domain": "b.example"}, "junk"],
            "action": {"type": "openPage", "url": "https://c.example"}}
        self.assertEqual(codex_brain.web_sources(item), [
            {"url": "https://a.example/x", "title": "A"}, {"url": "http://b.example", "title": "b.example"},
            {"url": "https://c.example", "title": ""}])


class SpeechTest(unittest.TestCase):
    def test_links_never_spoken(self):
        said = voice.clean_for_speech("It's **1.1.1** ([npm](https://www.npmjs.com/x)). See https://x.example/a?b=1 now.")
        self.assertNotIn("http", said)
        self.assertIn("npm", said)
        self.assertEqual(voice.clean_for_speech("[chuckle] Right then."), "[chuckle] Right then.")

    def test_paths_are_spoken_as_just_the_name(self):
        said = voice.clean_for_speech
        self.assertEqual(said(r"Saved C:\Users\Lemab\Documents\JARVIS Documents\budget-27e1190f4b.pptx for you."),
                         "Saved budget.pptx for you.")
        self.assertEqual(said("See [README](/C:/Users/Lemab/Jarvis/clip-farm/README.md) and /C:/Users/Lemab/Jarvis/clip-farm/clips/."),
                         "See README and clips.")
        self.assertEqual(said("Opened ~/projects/app/main.py."), "Opened main.py.")
        self.assertEqual(said("It's 72°F and/or 24/7, 3/4 done, at 60 km/h."),
                         "It's 72 degrees Fahrenheit and/or 24/7, 3/4 done, at 60 km/h.")

    def test_code_is_left_on_screen(self):
        report = ("Open PowerShell and run this:\n\n```powershell\ncd C:\\Users\\Lemab\\Jarvis\\clip-farm\n"
                  "& ..\\.venv\\Scripts\\python.exe clip_farm.py \"D:\\v.mp4\" --top 5\n```\n\nNothing was installed.")
        self.assertEqual(voice.clean_for_speech(report), "Open PowerShell and run this: It's on screen. Nothing was installed.")
        self.assertEqual(voice.clean_for_speech("Run `python clip_farm.py input.mp4 --model large --top 5` then `ls`."),
                         "Run the command on screen then ls.")

    def test_separate_codex_messages_are_not_glued_together(self):
        brain = codex_brain.CodexBrain.__new__(codex_brain.CodexBrain)
        brain.answer, brain.message_item, spoken = [], None, []
        brain.delta, brain.cancel = spoken.append, __import__("threading").Event()
        for item, text in (("m1", "I'll check"), ("m1", " the setup."), ("m2", "I'll let you know."), ("m3", " Done.")):
            brain._event({"method": "item/agentMessage/delta", "params": {"itemId": item, "delta": text}})
        self.assertEqual("".join(brain.answer), "I'll check the setup. I'll let you know. Done.")
        self.assertEqual("".join(spoken), "".join(brain.answer))

    def test_long_reports_are_shortened_for_speech(self):
        report = " ".join(f"Sentence number {i} explains one more detail of the finished work." for i in range(1, 9))
        spoken = voice.spoken_report(report)
        self.assertTrue(spoken.startswith("Sentence number 1 ") and spoken.endswith("The full report is on screen."))
        self.assertLessEqual(spoken.count("Sentence number"), 3)
        self.assertEqual(voice.spoken_report("Done. All tests passed."), "Done. All tests passed.")

    def test_long_text_is_queued_sentence_by_sentence(self):
        instance = voice.Voice.__new__(voice.Voice)
        instance._lock, instance._pending, instance._gen = __import__("threading").Lock(), 0, 0
        instance._idle, instance._text_q = __import__("threading").Event(), __import__("queue").Queue()
        text = " ".join(f"This is sentence {i} of a long spoken report." for i in range(12))
        with mock.patch.object(voice.hud, "emit"):
            instance.say(text, shown="full text")
        pieces = [instance._text_q.get_nowait()[1] for _ in range(instance._text_q.qsize())]
        self.assertEqual(len(pieces), 12)
        self.assertEqual(instance._pending, 12)


class VaultTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(knowledge, "VAULT", Path(self.folder.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.folder.cleanup()


class TasksTest(VaultTestCase):
    def test_add_list_complete_preserves_other_lines(self):
        path = Path(self.folder.name) / "Tasks.md"
        path.write_text("# Tasks\n\nMy own note line.\n- [x] Old thing\n", encoding="utf-8")
        tasks.add("Email Sam the invoice", due="Friday")
        tasks.add("Buy milk")
        self.assertEqual(tasks.describe(), "1. Email Sam the invoice (due Friday)\n2. Buy milk")
        self.assertEqual(tasks.complete("milk"), "Done: Buy milk")
        self.assertEqual(tasks.complete("1"), "Done: Email Sam the invoice (due Friday)")
        self.assertEqual(tasks.describe(), "No open tasks.")
        text = path.read_text(encoding="utf-8")
        self.assertIn("My own note line.", text)
        self.assertIn("- [x] Old thing", text)
        self.assertIn("no open task", tasks.complete("nothing like this").lower())

    def test_new_file_and_empty_task(self):
        self.assertEqual(tasks.add("   "), "Say what the task is.")
        tasks.add("First")
        self.assertTrue((Path(self.folder.name) / "Tasks.md").read_text(encoding="utf-8").startswith("# Tasks"))


class TelegramTest(unittest.TestCase):
    def test_voice_round_trip(self):
        t = np.linspace(0, 1, 24000, dtype=np.float32)
        ogg = telegram_bridge.encode_voice(0.3 * np.sin(2 * np.pi * 440 * t), 24000)
        self.assertTrue(ogg.startswith(b"OggS"))
        back = telegram_bridge.decode_voice(ogg)
        self.assertAlmostEqual(len(back) / 16000, 1.0, delta=0.05)

    def test_only_paired_chat_and_fresh_messages(self):
        bridge = telegram_bridge.Bridge()
        got, sent = [], []
        bridge.on_message = lambda chat, text, voice_: got.append((chat, text, voice_))
        bridge.send = lambda chat, text: sent.append(text)
        bridge.typing = lambda chat: None
        with mock.patch.object(telegram_bridge, "chat_id", return_value=42):
            bridge._handle({"chat": {"id": 7}, "date": time.time(), "text": "hi"})
            self.assertEqual((got, bridge.ignored), ([], 1))
            bridge._handle({"chat": {"id": 42}, "date": time.time() - 3600, "text": "old"})
            self.assertEqual(got, [])
            self.assertIn("offline", sent[-1])
            bridge._handle({"chat": {"id": 42}, "date": time.time(), "text": "What's on today?"})
            self.assertEqual(got, [(42, "What's on today?", False)])

    def test_send_requires_setup(self):
        with mock.patch.object(telegram_bridge, "chat_id", return_value=None):
            self.assertIn("isn't set up", telegram_bridge.send_to_owner("hi"))


class HoloTest(VaultTestCase):
    def test_configure_backup_and_card_mapping(self):
        (Path(self.folder.name) / "Projects").mkdir()
        (Path(self.folder.name) / "Projects" / "Alpha.md").write_text("# Alpha plan\nBody", encoding="utf-8")
        with tempfile.TemporaryDirectory() as install:
            folder = Path(install)
            (folder / "holo.json").write_text('{"folder": "sample-notes"}', encoding="utf-8")
            self.assertEqual(holo_bridge.configure(folder), "now reads your vault")
            self.assertEqual(json.loads((folder / "holo.json").read_text())["folder"], self.folder.name)
            self.assertIn("sample-notes", (folder / "holo.json.bak").read_text())
            self.assertEqual(holo_bridge.configure(folder), "already uses your vault")
        emitted, asked = [], []
        holo_bridge.handle({"event": "grab", "card": "Alpha plan"}, lambda kind, **d: emitted.append((kind, d)),
                           lambda label, prompt: asked.append(prompt))
        self.assertEqual(emitted[0][1]["sources"][0]["path"], "Projects/Alpha.md")
        holo_bridge.handle({"event": "sum", "card": "Alpha plan"}, lambda *a, **k: None, lambda label, prompt: asked.append(prompt))
        self.assertIn("Projects/Alpha.md", asked[0])
        holo_bridge.handle({"event": "fling", "card": "Unknown"}, lambda *a, **k: emitted.append(a), lambda *a: asked.append(a))
        self.assertEqual(len(emitted), 1)


class DictationTest(unittest.TestCase):
    def test_pastes_then_restores_clipboard_and_respects_work_apps(self):
        import dictation
        clipboard = ["previous"]
        with mock.patch.object(dictation.pyperclip, "paste", side_effect=lambda: clipboard[0]), \
             mock.patch.object(dictation.pyperclip, "copy", side_effect=lambda v: clipboard.__setitem__(0, v)) as copy, \
             mock.patch.object(dictation.win32api, "keybd_event") as keys, mock.patch.object(dictation.time, "sleep"), \
             mock.patch.object(dictation.worksafe, "foreground_blocked", return_value=False):
            self.assertEqual(dictation.type_into_focus("hello world"), "Typed.")
            self.assertEqual(copy.call_args_list[0].args[0], "hello world ")
            self.assertEqual(keys.call_count, 4)
            self.assertEqual(clipboard[0], "previous")
        with mock.patch.object(dictation.worksafe, "foreground_blocked", return_value=True), \
             mock.patch.object(dictation.win32api, "keybd_event") as keys:
            self.assertIn("work apps", dictation.type_into_focus("secret"))
            keys.assert_not_called()


class NudgesTest(unittest.TestCase):
    def test_each_event_announced_once_inside_lead_window(self):
        import datetime
        import nudges
        now = datetime.datetime(2026, 10, 21, 9, 0, tzinfo=datetime.timezone.utc)
        events = [(now + datetime.timedelta(minutes=8), "Standup"), (now + datetime.timedelta(minutes=40), "Lunch"),
                  (now + datetime.timedelta(seconds=30), "Call")]
        announced = set()
        said = [s for _, s in nudges.due(events, announced, now)]
        self.assertEqual(said, ["Heads up, sir: Standup starts in 8 minutes.", "Heads up, sir: Call starts now."])
        self.assertEqual(nudges.due(events, announced, now), [])


class BriefingWordsTest(unittest.TestCase):
    def test_matches_greetings_not_questions(self):
        import jarvis
        for said in ("good morning", "good morning, jarvis", "brief me", "what's my day look like"):
            self.assertTrue(jarvis.BRIEFING_WORDS.fullmatch(said), said)
        for said in ("good morning, can you open chrome", "what's the weather"):
            self.assertFalse(jarvis.BRIEFING_WORDS.fullmatch(said), said)


if __name__ == "__main__":
    unittest.main()
