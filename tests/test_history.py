"""Looking back: searching earlier conversations, the readable memory note, and the weekly check."""
import datetime
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import history
import knowledge
import memory
import privacy


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "transcripts").mkdir()
        (self.root / "vault").mkdir()
        for module, field, value in [(history, "TRANSCRIPTS", self.root / "transcripts"),
                                     (knowledge, "VAULT", self.root / "vault"),
                                     (privacy, "STORE", self.root / "privacy.json"),
                                     (memory, "PATH", str(self.root / "memory.json")),
                                     (memory, "RECENT_PATH", str(self.root / "recent.json"))]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def day(self, days_ago, *lines):
        date = datetime.date.today() - datetime.timedelta(days=days_ago)
        stamp = time.mktime(date.timetuple()) + 36000
        rows = [json.dumps({"type": kind, "t": stamp + n * 60, "text": text}) for n, (kind, text) in enumerate(lines)]
        (self.root / "transcripts" / f"{date.isoformat()}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
        return date.isoformat()


class SearchTest(Isolated):
    def test_finds_the_line_its_date_and_what_was_said_next(self):
        day = self.day(3, ("you", "What three wood should I buy for about 150 dollars?"),
                       ("jarvis", "A used TaylorMade would fit that budget."),
                       ("tool", "web_search"), ("you", "Turn off the fan."))
        found = history.search("three wood budget")
        self.assertIn(f"{day} 10:00 You: What three wood should I buy", found)
        self.assertIn("then Jarvis: A used TaylorMade", found)
        self.assertNotIn("Turn off the fan", found)
        self.assertIn("things may have changed since", found)

    def test_older_than_the_window_is_left_out(self):
        self.day(90, ("you", "Remember the paprika brand."))
        self.assertIn("No saved conversations in the last 60 days", history.search("paprika"))
        self.assertIn("paprika brand", history.search("paprika", days=120))

    def test_no_words_no_transcripts_and_bad_lines(self):
        self.assertIn("Give a few words", history.search("the of and"))
        self.assertIn("No saved conversations", history.search("fan"))
        (self.root / "transcripts" / f"{datetime.date.today().isoformat()}.jsonl").write_text(
            "not json\n" + json.dumps({"type": "you", "t": time.time(), "text": "open the garage"}) + "\n", encoding="utf-8")
        self.assertIn("open the garage", history.search("garage"))

    def test_private_phrases_are_filtered_from_results(self):
        self.day(1, ("you", "my password is hunter22 for the router"))
        privacy.configure(["hunter22"], False, False)
        self.assertNotIn("hunter22", history.search("router password"))

    def test_the_tool_is_registered_as_a_look_up(self):
        import tools
        import truth_guard
        self.assertIn("search_history", {t["name"] for t in tools.TOOL_DEFS})
        self.assertIsNone(truth_guard.classify("search_history", True, "x"))  # looking back proves nothing was done


class MirrorTest(Isolated):
    def test_note_lists_facts_newest_first_with_source_and_earlier_wording(self):
        items = [{"fact": "Ben lives in Minnesota.", "t": 1_790_000_000, "source": "Claude memory"},
                 {"fact": "The fan turns off after 15 minutes.", "t": 1_791_000_000, "updated": 1_792_000_000,
                  "history": [{"fact": "The fan turns off after 1 minute.", "until": 1_792_000_000}]}]
        text = history.mirror_text(items)
        self.assertLess(text.index("The fan turns off after 15 minutes."), text.index("Ben lives in Minnesota."))
        self.assertIn("from Claude memory", text)
        self.assertIn("earlier, until", text)
        self.assertIn("The fan turns off after 1 minute.", text)
        self.assertIn("edits made here are lost", text)
        self.assertIn("2 saved facts", text)

    def test_tests_never_write_the_vault_note(self):
        memory.remember("The owner likes tea.")
        self.assertFalse((self.root / "vault" / "Memory").exists())
        self.assertFalse(history.write_mirror([{"fact": "x", "t": 1}]))

    def test_outside_tests_the_note_is_written_and_replaced(self):
        with mock.patch("testing_guard.under_test", return_value=False):
            self.assertTrue(history.write_mirror([{"fact": "First fact.", "t": 1}]))
            self.assertTrue(history.write_mirror([{"fact": "Second fact.", "t": 2}]))
        text = (self.root / "vault" / "Memory" / "What Jarvis knows about you.md").read_text(encoding="utf-8")
        self.assertIn("Second fact.", text)
        self.assertNotIn("First fact.", text)

    def test_a_missing_vault_is_not_an_error(self):
        with mock.patch("testing_guard.under_test", return_value=False), \
                mock.patch.object(knowledge, "VAULT", self.root / "gone"):
            self.assertFalse(history.write_mirror([{"fact": "x", "t": 1}]))

    def test_only_the_real_memory_file_triggers_the_mirror(self):
        with mock.patch.object(history, "write_mirror") as write:
            memory.remember("Saved to a test store.")
        write.assert_not_called()


class WeeklyTest(Isolated):
    def test_counts_only_this_weeks_facts(self):
        memory.remember("An old fact.")
        items = memory._load()
        items[0]["t"] = time.time() - 30 * 86400
        memory._save(items)
        self.assertEqual(history.weekly_line(), "")
        memory.remember("Ben has a Mixamo account.")
        memory.remember("Ben's second outlet runs the air purifier.")
        line = history.weekly_line()
        self.assertIn("I saved 2 things about you", line)
        self.assertIn("Tell me if any of it is wrong", line)
        self.assertEqual(len(history.learned(7)), 2)


if __name__ == "__main__":
    unittest.main()
