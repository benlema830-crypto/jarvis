import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import knowledge
import memory
import decision_log
import privacy


class DecisionLogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        (self.vault / "Journal").mkdir(parents=True)
        for module, field, value in [(knowledge, "VAULT", self.vault),
                                     (decision_log, "STORE", self.root / "decisions.json"),
                                     (decision_log, "OLD_STORE", self.root / "no-old-queue.json"),
                                     (privacy, "STORE", self.root / "privacy.json"),
                                     (memory, "PATH", str(self.root / "memory.json")),
                                     (memory, "RECENT_PATH", str(self.root / "recent.json"))]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.today = datetime.date(2026, 10, 28)

    def journal(self, day, body):
        (self.vault / "Journal" / f"{day}.md").write_text(f"# {day}\n\n## Summary\nA day.\n\n{body}", encoding="utf-8")

    def test_decisions_are_logged_once_and_facts_are_not_harvested(self):
        self.journal("2026-10-26", "## Facts to remember\n- The owner works nights on weekdays.\n\n## Decisions\n"
                                   "- Use Obsidian for notes because it is local; rejected: Notion.\n"
                                   "- Ship the private test build first.\n")
        self.journal("2026-10-27", "## Decisions\n- Ship the private test build first.\n- Keep the fan on overnight.\n")
        self.journal("2026-10-28", "## Decisions\n- Today is not finished.\n")
        self.assertEqual(decision_log.harvest(self.today), 3)  # the repeated decision is logged once
        self.assertEqual(decision_log.harvest(self.today), 0)  # each day is read once
        log = knowledge.read(decision_log.DECISION_LOG)["content"]
        self.assertIn("## 2026-10-26: Use Obsidian for notes because it is local; rejected: Notion.", log)
        self.assertIn("## 2026-10-27: Keep the fan on overnight.", log)
        self.assertEqual(log.count("Ship the private test build first."), 1)
        self.assertNotIn("Today is not finished.", log)
        self.assertIn("the journal's summary", log)   # it never claims the owner approved each line
        self.assertNotIn("approved by the owner", log)
        self.assertEqual(memory.facts(), [])           # the journal's "facts" don't reach memory by themselves

    def test_today_is_read_on_a_later_day(self):
        self.journal("2026-10-28", "## Decisions\n- Use five keys.\n")
        self.assertEqual(decision_log.harvest(self.today), 0)
        self.assertEqual(decision_log.harvest(datetime.date(2026, 10, 29)), 1)

    def test_days_the_old_queue_already_read_are_not_read_again(self):
        self.journal("2026-10-26", "## Decisions\n- An old decision.\n")
        old = self.root / "old-queue.json"
        old.write_text('{"harvested": ["2026-10-26"], "items": []}', encoding="utf-8")
        with mock.patch.object(decision_log, "OLD_STORE", old):
            self.assertEqual(decision_log.harvest(self.today), 0)
        self.assertIn("2026-10-26", (self.root / "decisions.json").read_text(encoding="utf-8"))

    def test_no_journal_folder_is_fine(self):
        with mock.patch.object(knowledge, "VAULT", self.root / "nowhere"):
            self.assertEqual(decision_log.harvest(self.today), 0)

    def test_the_approval_queue_is_gone(self):
        import tools
        names = {t["name"] for t in tools.TOOL_DEFS}
        self.assertFalse(names & {"review_memory_proposals", "decide_memory_proposals"})
        self.assertIn("remember", names)


class MemoryHistoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module, field, value in [(privacy, "STORE", self.root / "privacy.json"),
                                     (memory, "PATH", str(self.root / "memory.json")),
                                     (memory, "RECENT_PATH", str(self.root / "recent.json"))]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_update_keeps_history_but_correct_and_forget_erase(self):
        memory.remember("The owner's top priority is Rocket Frontier.")
        self.assertIn("kept as history", memory.update("top priority", "The owner's top priority is Jarvis."))
        self.assertEqual(memory.facts(), ["The owner's top priority is Jarvis."])
        self.assertNotIn("Rocket Frontier", memory.prompt_section())  # only the current version is in the prompt
        self.assertIn("Earlier versions", memory.recall("priority"))
        self.assertIn("Rocket Frontier", memory.recall("priority"))
        memory.correct("top priority", "The owner's top priority is the smart home.")
        self.assertNotIn("is Jarvis.", memory.recall("priority").split("Earlier versions")[0])
        memory.forget("top priority")
        self.assertNotIn("Rocket Frontier", Path(memory.PATH).read_text(encoding="utf-8"))

    def test_limit_still_refuses_instead_of_evicting(self):
        with mock.patch.object(memory, "MAX_FACTS", 2):
            memory.remember("Fact one.")
            memory.remember("Fact two.")
            self.assertIn("nothing was removed", memory.remember("Fact three."))
        self.assertEqual(memory.facts(), ["Fact one.", "Fact two."])


if __name__ == "__main__":
    unittest.main()
