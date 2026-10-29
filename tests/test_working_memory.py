import datetime
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import knowledge
import memory
import memory_proposals
import privacy
import working_memory


class WorkingMemoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        (self.vault / "Journal").mkdir(parents=True)
        for module, field, value in [(knowledge, "VAULT", self.vault),
                                     (working_memory, "SESSIONS", self.root / "sessions.json"),
                                     (working_memory, "HANDOFFS", self.root / "handoffs"),
                                     (memory_proposals, "STORE", self.root / "proposals.json"),
                                     (privacy, "STORE", self.root / "privacy.json"),
                                     (memory, "PATH", str(self.root / "memory.json")),
                                     (memory, "RECENT_PATH", str(self.root / "recent.json"))]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.now = time.time()
        self.today = datetime.date.today()

    def sessions(self, **entries):
        (self.root / "sessions.json").write_text(json.dumps({"sessions": entries}), encoding="utf-8")

    def journal(self, days_back, threads=(), decisions=()):
        day = (self.today - datetime.timedelta(days=days_back)).isoformat()
        body = "# Day\n\n## Summary\nStuff.\n\n## Open threads\n" + "".join(f"- {t}\n" for t in threads)
        body += "\n## Decisions and preferences\n" + "".join(f"- {d}\n" for d in decisions)
        (self.vault / "Journal" / f"{day}.md").write_text(body, encoding="utf-8")

    def test_empty_records_give_empty_brief(self):
        self.assertEqual(working_memory.brief(), "")

    def test_brief_gathers_agents_tasks_journal_and_handoffs(self):
        self.sessions(
            a={"name": "Frontier", "project": "Rocket Frontier", "status": "running", "task": "Deploy the test build"},
            b={"name": "Builder", "project": "Jarvis", "status": "completed", "task": "Fix the TV default",
               "report": "Saved the [default](/C:/x.md). **All** tests passed.", "reported_at": self.now - 600},
            old={"name": "Old", "project": "Jarvis", "status": "completed", "task": "Ancient work",
                 "report": "done", "reported_at": self.now - 30 * 86400})
        (self.vault / "Tasks.md").write_text("- [ ] Call Spectrum\n- [x] Buy cables\n", encoding="utf-8")
        self.journal(0, threads=["Get an Ethernet quote"], decisions=["Willing to pay for better Wi-Fi"])
        self.journal(1, threads=["Get an Ethernet quote", "Test the clip farm"])
        folder = self.root / "handoffs" / "Jarvis"
        folder.mkdir(parents=True)
        (folder / "1.json").write_text(json.dumps({
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "claims": {"next_action": "Try the three Core models"}}), encoding="utf-8")

        brief = working_memory.brief()
        self.assertIn("Frontier (Rocket Frontier): running", brief)
        self.assertIn("Saved the default. All tests passed.", brief)  # links and markdown removed
        self.assertNotIn("Ancient work", brief)
        self.assertIn("Call Spectrum", brief)
        self.assertNotIn("Buy cables", brief)
        self.assertEqual(brief.count("Get an Ethernet quote"), 1)  # repeated threads appear once
        self.assertIn("Test the clip farm", brief)
        self.assertIn("not confirmed facts", brief)
        self.assertIn("Jarvis (today", brief)
        self.assertEqual(brief, working_memory.brief())  # stable between turns

    def test_project_brief_warns_about_live_agents_and_shares_results(self):
        with mock.patch.object(working_memory, "PROJECT_LOG", self.root / "log.jsonl"):
            self.assertEqual(working_memory.project_brief("Rocket Frontier", "Frontier"), "")
            self.sessions(
                me={"name": "Frontier", "project": "Rocket Frontier", "status": "running", "task": "My own task"},
                other={"name": "Frontier Claude", "project": "Rocket Frontier", "status": "running",
                       "task": "Rework the shop UI"},
                elsewhere={"name": "Builder", "project": "Jarvis", "status": "running", "task": "Jarvis work"})
            working_memory.record_result("Rocket Frontier", "Frontier Claude", "Fix saves", True, "Saves fixed.")
            working_memory.record_result("Jarvis", "Builder", "Jarvis thing", True, "Jarvis result.")
            self.journal(0, threads=["Verify Rocket Frontier's place IDs"], decisions=["Use Obsidian"])
            brief = working_memory.project_brief("Rocket Frontier", "Frontier")
        self.assertIn("Don't undo or overwrite", brief)
        self.assertIn("Rework the shop UI", brief)
        self.assertNotIn("My own task", brief)
        self.assertNotIn("Jarvis work", brief)
        self.assertIn("Saves fixed.", brief)
        self.assertNotIn("Jarvis result.", brief)
        self.assertIn("place IDs", brief)
        self.assertNotIn("Use Obsidian", brief)

    def test_brief_is_capped(self):
        self.journal(0, threads=["x" * 600] * 1 + [f"thread {i} " + "y" * 500 for i in range(8)])
        self.assertLessEqual(len(working_memory.brief()), working_memory.MAX_CHARS)

    def test_conversation_gets_brief_once_and_again_when_work_changes(self):
        import jarvis
        brain = jarvis.Brain()
        brain._run = lambda speak: speak("Okay")
        self.sessions(a={"name": "Frontier", "project": "Rocket Frontier", "status": "running", "task": "Deploy"})
        with mock.patch.object(jarvis.router, "choose", return_value=None):
            brain.ask("What's going on?", mock.Mock())
            brain.ask("And now?", mock.Mock())
            self.sessions(a={"name": "Frontier", "project": "Rocket Frontier", "status": "completed",
                             "task": "Deploy", "report": "Deployed.", "reported_at": time.time()})
            brain.ask("Anything new?", mock.Mock())
        users = [m["content"] for m in brain.messages if m["role"] == "user"]
        self.assertIn(jarvis.STATE_MARK, users[0])
        self.assertNotIn(jarvis.STATE_MARK, users[1])
        self.assertIn("Deployed.", users[2])
        brain.messages = []  # e.g. cleared after a privacy change: the brief comes back
        with mock.patch.object(jarvis.router, "choose", return_value=None):
            brain.ask("Hello", mock.Mock())
        self.assertIn(jarvis.STATE_MARK, brain.messages[0]["content"])

    def test_local_model_turn_skips_brief(self):
        import jarvis
        brain = jarvis.Brain()
        brain._run = lambda speak: speak("Okay")
        self.sessions(a={"name": "Frontier", "project": "Rocket Frontier", "status": "running", "task": "Deploy"})
        with mock.patch.object(jarvis.router, "choose", return_value={"provider": "ollama", "model": "m"}):
            brain.ask("Turn on the lights", mock.Mock())
        self.assertNotIn(jarvis.STATE_MARK, brain.messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
