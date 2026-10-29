import datetime
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import daily_review
import knowledge
import memory
import memory_proposals
import performance
import privacy
import task_effort
import working_memory

REVIEW = """## Spoken summary
Rocket Frontier's deployment is still blocked on Studio. Connecting it is the one thing that matters today.
## Priorities today
- Connect Studio (agent session record).
## Stalled or at risk
- Deployment blocked since Sunday.
## Ideas and opportunities
- Idea: sell clips.
## Research worth starting
- Find streamer clipping prices.
## Jarvis improvements
- Fewer approval prompts."""


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        for module, field, value in [(knowledge, "VAULT", self.vault),
                                     (working_memory, "SESSIONS", self.root / "sessions.json"),
                                     (working_memory, "HANDOFFS", self.root / "handoffs"),
                                     (working_memory, "PROJECT_LOG", self.root / "log.jsonl"),
                                     (memory_proposals, "STORE", self.root / "proposals.json"),
                                     (performance, "TURNS", self.root / "turns.jsonl"),
                                     (task_effort, "PATH", self.root / "effort.jsonl"),
                                     (privacy, "STORE", self.root / "privacy.json"),
                                     (memory, "PATH", str(self.root / "memory.json")),
                                     (memory, "RECENT_PATH", str(self.root / "recent.json"))]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)


class PerformanceTest(Isolated):
    def test_scorecard_compares_models_and_tasks(self):
        for first in (1.0, 2.0, 3.0):
            performance.record_turn("codex", "terra", False, first, first + 1, "ok")
        performance.record_turn("ollama", "qwen3:4b", True, 0.5, 0.8, "ok")
        performance.record_turn("codex", "terra", False, None, 30, "failed")
        rows = [{"t": time.time(), "kind": "codex", "ok": True, "seconds": 120, "report": "Done and tested."},
                {"t": time.time(), "kind": "codex", "ok": True, "seconds": 600, "report": "Deployment is blocked."},
                {"t": time.time(), "kind": "screen", "ok": False, "seconds": 30, "report": "x", "stopped_by_user": True}]
        (self.root / "effort.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        card = performance.scorecard()
        self.assertIn("codex/terra: 4 turns, median 2.0s", card)
        self.assertIn("1 failed", card)
        self.assertIn("ollama/qwen3:4b (local router): 1 turns", card)
        self.assertIn("codex: 2 tasks, 2 finished, 1 struggled", card)
        self.assertIn("Deployment is blocked.", card)
        self.assertIn("1 stopped by the user", card)

    def test_turns_are_timed_with_the_answering_model(self):
        import jarvis
        brain = jarvis.Brain()
        brain._run = lambda speak: speak("Okay")
        brain.selection.active = {"provider": "codex", "model": "terra"}
        brain.config = dict(brain.selection.active)
        with mock.patch.object(jarvis.router, "choose", return_value=None):
            brain.ask("Hello", mock.Mock())
        row = json.loads((self.root / "turns.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((row["provider"], row["model"], row["outcome"]), ("codex", "terra", "ok"))
        self.assertIsNotNone(row["first"])
        self.assertNotIn("Hello", json.dumps(row))  # no words are kept


class DailyReviewTest(Isolated):
    def test_writes_once_with_records_and_surfaces_in_working_memory(self):
        today = datetime.date.today()
        memory.remember("The owner's goal is to run an AI-assisted game studio.")
        seen = {}

        def fake_codex(system, text, label):
            seen["text"] = text
            return REVIEW
        with mock.patch("vault_log.codex_once", fake_codex):
            path = daily_review.write(today)
            self.assertIsNone(daily_review.write(today))  # once a day
        self.assertEqual(path, f"Briefs/{today.isoformat()} Daily review.md")
        self.assertIn("AI-assisted game studio", seen["text"])
        self.assertIn("Performance scorecard", seen["text"])
        content = knowledge.read(path)["content"]
        self.assertIn("proposals, not decisions", content)
        self.assertTrue(daily_review.spoken(content).startswith("Rocket Frontier's deployment"))
        self.assertIn("Connecting it is the one thing", working_memory.brief())

    def test_no_note_without_a_usable_answer(self):
        with mock.patch("vault_log.codex_once", return_value=None):
            self.assertIsNone(daily_review.write())
        with mock.patch("vault_log.codex_once", return_value="Just some text without sections."):
            self.assertIsNone(daily_review.write())
        self.assertFalse((self.vault / "Briefs").exists())

    def test_settings_can_turn_it_off(self):
        with mock.patch("preferences.read", return_value={"daily_review": {"enabled": False, "hour": "9"}}):
            self.assertEqual(daily_review._settings(), {"enabled": False, "hour": 9, "speak": True})


if __name__ == "__main__":
    unittest.main()
