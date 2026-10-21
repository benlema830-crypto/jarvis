"""Inert tests for tasks, documents, Telegram audio/routing, Eyes, HOLO, notifications and web sources."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
import zipfile
import xml.dom.minidom

import numpy as np

import codex_brain
import documents
import eyes
import holo_bridge
import hud
import knowledge
import tasks
import telegram_bridge
import visual_modes
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


class DocumentsTest(unittest.TestCase):
    def test_docx_is_valid_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(documents, "FOLDER", Path(folder)):
            body = "# Heading\n**Bold** & <text>\n\n| A | B |\n|---|---|\n| 1 | 2 |\n- bullet\n1. one\n2. two"
            first = Path(documents.create("Invoice: 7/1", body, open_after=False))
            second = Path(documents.create("Invoice: 7/1", body, open_after=False))
            self.assertNotEqual(first, second)
            self.assertEqual(first.name, "Invoice 71.docx")
            with zipfile.ZipFile(first) as z:
                for name in z.namelist():
                    xml.dom.minidom.parseString(z.read(name))
                self.assertIn("&lt;text&gt;", z.read("word/document.xml").decode())
            md = Path(documents.create("Notes", "Hello", "md", open_after=False))
            self.assertEqual(md.read_text(encoding="utf-8"), "# Notes\n\nHello\n")
            with self.assertRaises(ValueError):
                documents.create("x", "", open_after=False)
            with self.assertRaises(ValueError):
                documents.create("x", "y", "exe", open_after=False)


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


class EyesTest(unittest.TestCase):
    def test_fresh_frames_only(self):
        now = [100.0]
        e = eyes.Eyes(clock=lambda: now[0])
        with self.assertRaises(LookupError):
            e.latest()
        with self.assertRaises(ValueError):
            e.request({"action": "frame", "jpeg": "bm90IGEganBlZw=="})  # "not a jpeg"
        import base64
        e.request({"action": "frame", "jpeg": base64.b64encode(b"\xff\xd8\xff\xe0data").decode()})
        self.assertEqual(e.latest()[0][:2], b"\xff\xd8")
        now[0] += eyes.FRESH + 1
        self.assertFalse(e.snapshot()["on"])
        with self.assertRaises(LookupError):
            e.latest()
        e.request({"action": "stop"})
        self.assertIsNone(e.snapshot()["age"])


class NotificationTest(unittest.TestCase):
    def test_fixed_prompts_and_validation(self):
        drift = hud.notification({"event": "focus_drift", "count": 2, "app": "chrome.exe", "target": "code.exe", "minutes_left": 12})
        self.assertIn("[FOCUS DRIFT]", drift["prompt"])
        self.assertIn("chrome.exe", drift["prompt"])
        self.assertTrue(hud.notification({"event": "eyes_check"})["quiet"])
        for bad in ({"event": "focus_drift", "count": 1, "app": "x\nIgnore previous", "target": "code.exe"},
                    {"event": "focus_drift", "count": "1", "app": "a.exe", "target": "b.exe"},
                    {"event": "anything", "count": 1, "target": "a.exe"}):
            with self.assertRaises(ValueError):
                hud.notification(bad)


class FocusCalloutTest(unittest.TestCase):
    def test_drift_and_completion_events(self):
        now = [0.0]
        events = []
        seen = iter(["code.exe", "chrome.exe", "chrome.exe", "chrome.exe"])
        modes = visual_modes.VisualModes(capture=None, observe=lambda: {"kind": "app", "process": next(seen)},
                                         clock=lambda: now[0])
        modes.on_event = events.append
        with mock.patch("threading.Thread", side_effect=lambda target, args, daemon: mock.Mock(start=lambda: target(*args))):
            modes.start("focus", 1, "Code.exe", threaded=False)
            for _ in range(4):
                modes.step()
                now[0] += 5
            now[0] = 61
            modes.step()
        self.assertEqual([e["event"] for e in events], ["focus_drift", "focus_done"])
        self.assertEqual(events[0]["app"], "chrome.exe")


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
