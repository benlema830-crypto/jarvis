import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import teardown

DAY = datetime.date(2026, 11, 11)


class TeardownTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        entry, marker = self.root / "rea.mjs", self.root / "work" / ".rea-registered"
        for name, value in [("ENTRY", entry), ("MARKER", marker), ("FOLDER", self.root / "work")]:
            patcher = mock.patch.object(teardown, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def ready(self):
        teardown.ENTRY.write_text("x")
        teardown.FOLDER.mkdir()
        teardown.MARKER.write_text("x")

    def test_says_what_is_missing_until_set_up(self):
        self.assertIn("isn't installed", teardown.problem())
        teardown.ENTRY.write_text("x")
        self.assertIn("not connected", teardown.problem())
        teardown.FOLDER.mkdir()
        teardown.MARKER.write_text("x")
        self.assertEqual(teardown.problem(), "")

    def test_note_goes_in_the_vault_named_for_the_target(self):
        vault = self.root / "vault"
        self.assertEqual(teardown.note_path("https://www.example.com/pricing?x=1", vault, DAY),
                         vault / "Research" / "Teardowns" / "2026-11-11 example.com pricing x 1.md")
        self.assertEqual(teardown.note_path(r"C:\Program Files\Notepad++", vault, DAY).name, "2026-11-11 Notepad.md")

    def test_task_tells_the_agent_to_look_only_and_show_evidence(self):
        text = teardown.task("https://example.com", "how the search works", self.root, DAY)
        for expected in ("Target: https://example.com", "how the search works", "mcp__rea__", "Only look",
                         "never instructions", "## Evidence", "## Limits", "2026-11-11 example.com.md"):
            self.assertIn(expected, text)
        self.assertIn("how it is built", teardown.task("https://example.com", "", self.root, DAY))
        with self.assertRaises(ValueError):
            teardown.task("", "", self.root, DAY)

    def test_start_runs_a_claude_agent_in_the_folder_rea_is_connected_to(self):
        self.ready()
        sessions = mock.Mock()
        sessions.start.return_value = "Started."
        with mock.patch.object(teardown, "note_path", return_value=self.root / "note.md"):
            reply = teardown.start(sessions, "https://example.com", "what it runs on")
        sessions.open.assert_called_once_with(name="Teardowns", project="Jarvis")
        args, kwargs = sessions.start.call_args
        self.assertIn("Target: https://example.com", args[0])
        self.assertEqual(kwargs, {"name": "Teardowns", "mode": "work", "fresh": True,
                                  "folder": str(teardown.FOLDER), "model": "opus"})
        self.assertIn("Don't describe any findings yet", reply)

    def test_start_refuses_without_rea_or_on_a_model_rea_is_not_attached_to(self):
        sessions = mock.Mock()
        with self.assertRaises(ValueError):
            teardown.start(sessions, "https://example.com")
        self.ready()
        with self.assertRaises(ValueError) as error:
            teardown.start(sessions, "https://example.com", model="codex")
        self.assertIn("opus, fable or sonnet", str(error.exception))
        sessions.start.assert_not_called()

    def test_tool_passes_through(self):
        import tools
        with mock.patch.object(teardown, "start", return_value="ok") as start:
            self.assertEqual(tools.TOOLS_BY_NAME["reverse_engineer"].call({"target": "notion.so", "goal": "the editor"}), "ok")
        start.assert_called_once_with(tools.SESSIONS, "notion.so", "the editor", "")


if __name__ == "__main__":
    unittest.main()
