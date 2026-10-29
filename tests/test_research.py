import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import knowledge
import memory
import privacy
import research
import working_memory

REPORT = """## Spoken summary
Used launch monitors under a thousand dollars are good enough for gapping. The Garmin R10 is the best value.
## Key findings
- The R10 costs about $600 (https://example.com/r10).
## What this means for the owner
Recommendation: buy the R10 for range sessions.
## Open questions
None.
## Sources
https://example.com/r10"""


class ResearchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "vault").mkdir()
        for module, field, value in [(knowledge, "VAULT", self.root / "vault"),
                                     (research, "STORE", self.root / "research.json"),
                                     (working_memory, "PROJECT_LOG", self.root / "log.jsonl"),
                                     (privacy, "STORE", self.root / "privacy.json"),
                                     (memory, "PATH", str(self.root / "memory.json")),
                                     (memory, "RECENT_PATH", str(self.root / "recent.json"))]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_research(self, result=None, error=None, topic="Best launch monitor under $1000"):
        seen, done = {}, []

        def fake(instructions, request, searches, seconds, cancel=None):
            seen.update(instructions=instructions, request=request)
            if error:
                raise error
            return result, [{"title": "R10 review", "url": "https://example.com/r10"},
                            {"title": "Unrelated", "url": "https://example.com/other"}], 3
        with mock.patch.object(research, "codex_research", fake):
            research.start(topic, "practice for scratch golf", on_done=done.append, background=False)
        return seen, done

    def test_finished_research_is_a_vault_note_announced_and_recorded(self):
        memory.remember("Ben is working toward scratch golf.")
        seen, done = self.run_research(REPORT)
        self.assertIn("scratch golf", seen["instructions"])  # owner context goes to the researcher
        self.assertIn("Why the owner wants it: practice for scratch golf", seen["request"])
        record = done[0]
        self.assertTrue(record["ok"])
        self.assertTrue(record["summary"].startswith("Used launch monitors"))
        content = knowledge.read(record["note"])["content"]
        self.assertTrue(record["note"].startswith("Research/") and record["note"].endswith("under 1000.md"))
        self.assertIn("type: research", content)
        self.assertIn("[R10 review](https://example.com/r10)", content)
        self.assertNotIn("example.com/other", content)  # only links the report actually cites
        log = [json.loads(line) for line in (self.root / "log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual((log[0]["project"], log[0]["ok"]), ("Research", True))
        self.assertIn("Done: Best launch monitor", research.recent_lines()[0])
        self.assertIn("Done", research.describe())

    def test_same_topic_twice_never_overwrites(self):
        _, first = self.run_research(REPORT)
        _, second = self.run_research(REPORT)
        self.assertNotEqual(first[0]["note"], second[0]["note"])
        self.assertTrue(second[0]["note"].endswith("(2).md"))

    def test_failures_are_reported_and_nothing_is_saved(self):
        _, done = self.run_research(error=ValueError("Research ran out of time or searches before finishing."))
        self.assertFalse(done[0]["ok"])
        self.assertIn("ran out of time", done[0]["summary"])
        self.assertFalse((self.root / "vault" / "Research").exists())
        _, done = self.run_research("No sections at all.")
        self.assertFalse(done[0]["ok"])
        self.assertEqual(research._load()["runs"][-1]["status"], "failed")

    def test_limits_concurrent_runs_and_marks_interrupted(self):
        with mock.patch.object(research, "_work"):
            research.start("Topic one here")
            with self.assertRaises(ValueError):
                research.start("topic ONE here")  # already running
            research.start("Topic two here")
            with self.assertRaises(ValueError):
                research.start("Topic three here")  # two at a time
        with self.assertRaises(ValueError):
            research.start("hi")
        research.interrupted()
        self.assertEqual({r["status"] for r in research._load()["runs"]}, {"failed"})
        self.assertIn("Jarvis restarted", research.describe())

    def test_codex_research_stops_at_the_search_budget(self):
        class FakeBrain:
            def __init__(self):
                self.sources = []

            def ask(self, model, system, messages, definitions, run_tool, delta, cancel):
                self.cancel = cancel
                for _ in range(3):
                    self._web_search("item/started", {})
                    if cancel.is_set():
                        raise InterruptedError()
                return "never"

            def close(self):
                pass
        with mock.patch("codex_brain.CodexBrain", FakeBrain), \
                mock.patch("preferences.read", return_value={"conversation_model": {"provider": "codex", "model": "m"}}):
            with self.assertRaises(ValueError):
                research.codex_research("system", "request", searches=2, seconds=30)

    def test_note_names_are_safe(self):
        self.assertEqual(research.note_name("What's <best>/fastest: GPU?", "2026-10-28"),
                         "Research/2026-10-28 What's best fastest GPU.md")


if __name__ == "__main__":
    unittest.main()
