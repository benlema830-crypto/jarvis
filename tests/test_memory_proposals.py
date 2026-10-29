import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import knowledge
import memory
import memory_proposals
import privacy


class MemoryProposalsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        (self.vault / "Journal").mkdir(parents=True)
        for module, field, value in [(knowledge, "VAULT", self.vault),
                                     (memory_proposals, "STORE", self.root / "proposals.json"),
                                     (privacy, "STORE", self.root / "privacy.json"),
                                     (memory, "PATH", str(self.root / "memory.json")),
                                     (memory, "RECENT_PATH", str(self.root / "recent.json"))]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.today = datetime.date(2026, 10, 28)

    def journal(self, day, body):
        (self.vault / "Journal" / f"{day}.md").write_text(f"# {day}\n\n## Summary\nA day.\n\n{body}", encoding="utf-8")

    def test_harvest_proposes_once_and_skips_known_facts_and_today(self):
        memory.remember("The owner's game project is Rocket Frontier.")
        self.journal("2026-10-26", "## Facts to remember\n- The owner's game project is Rocket Frontier.\n"
                                   "- The owner works nights on weekdays.\n\n## Decisions\n"
                                   "- Use Obsidian for notes because it is local; rejected: Notion.\n")
        self.journal("2026-10-27", "## Decisions and preferences\n- The owner wants humor at 100%.\n"
                                   "## Facts to remember\n- The owner works nights on weekdays.\n")
        self.journal("2026-10-28", "## Facts to remember\n- Today is not finished.\n")
        self.assertEqual(memory_proposals.harvest(self.today), 3)
        self.assertEqual(memory_proposals.harvest(self.today), 0)  # each day is read once
        kinds = [(i["kind"], i["text"]) for i in memory_proposals.pending()]
        self.assertIn(("decision", "Use Obsidian for notes because it is local; rejected: Notion."), kinds)
        self.assertIn(("fact", "The owner wants humor at 100%."), kinds)
        self.assertNotIn("Today is not finished.", str(kinds))
        self.assertEqual(len(memory.facts()), 1)  # nothing joins memory without approval
        self.assertIn("3 memory proposals", memory_proposals.count_line())

    def test_approving_saves_with_source_and_logs_decisions(self):
        self.journal("2026-10-26", "## Facts to remember\n- The owner works nights.\n- The owner has a dog.\n\n"
                                   "## Decisions\n- Ship the private test build first.\n")
        memory_proposals.harvest(self.today)
        listing = memory_proposals.listing()
        self.assertIn("1. [fact] The owner works nights.", listing)
        memory_proposals.decide("1 and 3", True)
        memory_proposals.decide("1", False)  # numbers follow the remaining list: the dog
        self.assertEqual(memory_proposals.pending(), [])
        self.assertEqual(memory.facts(), ["The owner works nights."])
        self.assertIn("Journal/2026-10-26", memory.recall("nights"))
        log = knowledge.read(memory_proposals.DECISION_LOG)["content"]
        self.assertIn("Ship the private test build first.", log)
        self.assertIn("Status: active", log)

    def test_reword_and_bad_selection(self):
        self.journal("2026-10-26", "## Facts to remember\n- The owner likes tea.\n- The owner likes jazz.\n")
        memory_proposals.harvest(self.today)
        with self.assertRaises(ValueError):
            memory_proposals.decide("9", True)
        with self.assertRaises(ValueError):
            memory_proposals.decide("all", True, reword="Both")
        memory_proposals.decide("1", True, reword="The owner likes green tea.")
        self.assertEqual(memory.facts(), ["The owner likes green tea."])


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
