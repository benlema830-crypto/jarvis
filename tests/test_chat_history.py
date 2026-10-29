import datetime
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import chat_history
import knowledge
import memory
import memory_proposals
import privacy

NOW = time.time()
DAY = 86400


def chatgpt(title, t, turns):
    mapping, parent = {"root": {"message": None, "parent": None}}, "root"
    for i, (role, text) in enumerate(turns):
        mapping[f"n{i}"] = {"parent": parent, "message": {"author": {"role": role}, "create_time": t,
                                                          "content": {"content_type": "text", "parts": [text]}}}
        parent = f"n{i}"
    mapping["side"] = {"parent": "root", "message": {"author": {"role": "user"},  # an abandoned branch
                                                     "content": {"content_type": "text", "parts": ["DISCARDED"]}}}
    return {"title": title, "create_time": t, "update_time": t, "mapping": mapping, "current_node": parent}


def claude(name, t, turns):
    stamp = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
    return {"uuid": name, "name": name, "created_at": stamp, "updated_at": stamp,
            "chat_messages": [{"sender": s, "text": text, "created_at": stamp} for s, text in turns]}


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        for module, field, value in [(knowledge, "VAULT", self.vault),
                                     (memory_proposals, "STORE", self.root / "proposals.json"),
                                     (privacy, "STORE", self.root / "privacy.json"),
                                     (memory, "PATH", str(self.root / "memory.json")),
                                     (memory, "RECENT_PATH", str(self.root / "recent.json"))]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)


class ChatHistoryTest(Isolated):
    def test_imports_both_exports_by_week_within_the_window(self):
        gpt = [chatgpt("Clip farm plan", NOW - 10 * DAY, [("user", "Plan the clip farm"), ("assistant", "Start with VODs.")]),
               chatgpt("Ancient chat", NOW - 900 * DAY, [("user", "old"), ("assistant", "old")])]
        cla = [claude("Roblox saves", NOW - 3 * DAY, [("human", "Fix saves"), ("assistant", "Use DataStore.")])]
        with zipfile.ZipFile(self.root / "gpt.zip", "w") as z:
            z.writestr("conversations.json", json.dumps(gpt))
        (self.root / "claude").mkdir()
        (self.root / "claude" / "conversations.json").write_text(json.dumps(cla), encoding="utf-8")
        convs = chat_history.load(self.root / "gpt.zip") + chat_history.load(self.root / "claude")
        self.assertEqual(len(convs), 3)
        result = chat_history.write_archive(convs, days=730, now=NOW)
        self.assertEqual((result["conversations"], result["skipped_older"], result["written"]), (2, 1, 2))
        notes = sorted(p.relative_to(self.vault).as_posix() for p in self.vault.rglob("*.md"))
        self.assertTrue(notes[0].startswith("Archive/ChatGPT/") and notes[1].startswith("Archive/Claude/"))
        text = (self.vault / notes[0]).read_text(encoding="utf-8")
        self.assertIn("## Clip farm plan", text)
        self.assertIn("**You:** Plan the clip farm", text)
        self.assertIn("**ChatGPT:** Start with VODs.", text)
        self.assertNotIn("DISCARDED", text)  # only the conversation's final branch
        self.assertIn("**Claude:** Use DataStore.", (self.vault / notes[1]).read_text(encoding="utf-8"))
        self.assertIn("Clip farm", str(knowledge.search("clip farm VODs")))
        # Re-running changes nothing and never overwrites.
        self.assertEqual(chat_history.write_archive(convs, days=730, now=NOW)["existing"], 2)

    def test_busy_week_splits_under_the_size_limit_and_redacts(self):
        long = "x" * 2900
        convs = [chatgpt(f"Chat {i}", NOW - DAY, [("user", long), ("assistant", long + " sk-proj-" + "a" * 30)])
                 for i in range(60)]
        result = chat_history.write_archive(chat_history.conversations(convs), now=NOW)
        self.assertGreater(result["written"], 1)
        for note in self.vault.rglob("*.md"):
            self.assertLess(note.stat().st_size, knowledge.MAX_BYTES)
            self.assertNotIn("sk-proj-aaaa", note.read_text(encoding="utf-8"))

    def test_unknown_or_broken_data_is_ignored(self):
        self.assertEqual(chat_history.conversations({"not": "a list"}), [])
        self.assertEqual(chat_history.conversations([{"title": "x"}, "junk", {"mapping": {}, "current_node": None}]), [])


class ImportLinesTest(Isolated):
    def test_memory_list_becomes_proposals_once(self):
        memory.remember("The owner prefers short answers.")
        text = ("1. The owner prefers short answers.\n- Works on a Roblox game called Rocket Frontier\n\n"
                "• Lives in Minnesota\nok\n")
        self.assertEqual(memory_proposals.import_lines(text, "ChatGPT memory"), 2)
        self.assertEqual(memory_proposals.import_lines(text, "ChatGPT memory"), 0)
        items = memory_proposals.pending()
        self.assertEqual([i["text"] for i in items], ["Works on a Roblox game called Rocket Frontier", "Lives in Minnesota"])
        memory_proposals.decide("1", True)
        self.assertIn("ChatGPT memory (imported, approved by the owner)", memory.recall("Roblox"))


if __name__ == "__main__":
    unittest.main()
