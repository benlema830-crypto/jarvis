"""Jarvis must not be able to spend API credits: no paid key is loaded, and stage records stay out of real data."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jarvis
import runtime_metrics


class NoPaidKeys(unittest.TestCase):
    def test_paid_keys_are_blank_after_jarvis_loads(self):
        for key in jarvis.PAID_KEYS:
            self.assertEqual(os.environ.get(key, ""), "", key)

    def test_all_three_paid_services_are_covered(self):
        self.assertEqual(set(jarvis.PAID_KEYS), {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"})

    def test_screen_agent_builds_no_client_at_start(self):
        import tools
        self.assertIsNone(tools.AGENT.client)


class StageLog(unittest.TestCase):
    def test_finished_turn_is_saved_with_its_tools(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runtime_metrics, "LOG", Path(folder) / "stages.jsonl"):
            runtime_metrics.begin_turn(source="keyboard")
            runtime_metrics.note_tool("home_control", True, 0.25)
            runtime_metrics.note_tool("run_command", False, 1.5)
            runtime_metrics.mark("first_text")
            runtime_metrics.mark("complete")
            runtime_metrics.mark("complete")  # a second mark must not write a second line
            lines = (Path(folder) / "stages.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        row = json.loads(lines[0])
        self.assertEqual(row["source"], "keyboard")
        self.assertIn("first_text", row["stages"])
        self.assertEqual([(t["name"], t["ok"], t["ms"]) for t in row["tools"]],
                         [("home_control", True, 250), ("run_command", False, 1500)])

    def test_test_runs_do_not_write_the_real_log(self):
        before = runtime_metrics.DEFAULT_LOG.stat().st_size if runtime_metrics.DEFAULT_LOG.exists() else None
        runtime_metrics.begin_turn(source="keyboard")
        runtime_metrics.mark("complete")
        after = runtime_metrics.DEFAULT_LOG.stat().st_size if runtime_metrics.DEFAULT_LOG.exists() else None
        self.assertEqual(before, after)

    def test_tool_outside_a_turn_is_ignored(self):
        with patch.object(runtime_metrics, "_turn", None):
            runtime_metrics.note_tool("home_status", True, 0.1)


if __name__ == "__main__":
    unittest.main()
