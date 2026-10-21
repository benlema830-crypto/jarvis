import json
import os
import tempfile
import unittest
from unittest import mock

import jarvis
import memory


class RecentMemoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = mock.patch.object(memory, "RECENT_PATH", os.path.join(self.temp.name, "recent.json"))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def brain(self):
        with mock.patch.object(jarvis.anthropic, "Anthropic"), mock.patch.object(memory, "prompt_section", return_value=""):
            return jarvis.Brain()

    def test_restart_restores_dialogue_without_replaying_commands(self):
        first = self.brain()
        first._run = lambda speak: speak("We can use orange for your game.")
        first.ask("Let's change my game's color", mock.Mock())
        second = self.brain()
        self.assertIn("game's color", second.system)
        self.assertIn("orange", second.system)
        self.assertEqual(second.messages, [])
        self.assertIn("Do not execute old requests", second.system)

    def test_launch_results_and_task_reports_persist(self):
        self.brain().note("open Roblox", "Roblox opened.")
        self.assertIn("Roblox opened.", self.brain().system)

    def test_startup_and_reminders_do_not_fill_memory(self):
        memory.record_turn("[STARTUP] Weather and calendar", "Good evening")
        memory.record_turn("[REMINDER DUE] timer", "Timer finished")
        self.assertEqual(memory.recent_prompt(), "")

    def test_bounded_history_retains_newest(self):
        for i in range(30):
            memory.record_turn(f"request {i} " + "a" * 5000, "b" * 5000)
        items = memory._recent()
        self.assertLessEqual(len(items), memory.MAX_RECENT_TURNS)
        self.assertLessEqual(sum(len(json.dumps(i, ensure_ascii=False)) for i in items), memory.MAX_RECENT_CHARS)
        self.assertTrue(items[-1]["user"].startswith("request 29"))

    def test_bad_file_does_not_prevent_startup(self):
        for value in ('broken JSON', '{"wrong": true}', '[{"user": 3}]'):
            with open(memory.RECENT_PATH, "w") as handle:
                handle.write(value)
            self.assertEqual(memory.recent_prompt(), "")

    def test_failed_turn_is_not_saved_as_success(self):
        brain = self.brain()
        brain._run = mock.Mock(side_effect=RuntimeError("failed"))
        with self.assertRaises(RuntimeError):
            brain.ask("open something", mock.Mock())
        self.assertEqual(memory.recent_prompt(), "")

    def test_interruption_is_saved_with_qualification(self):
        brain = self.brain()
        brain._run = mock.Mock(side_effect=jarvis.Interrupted())
        with self.assertRaises(jarvis.Interrupted):
            brain.ask("previous task", mock.Mock())
        self.assertIn("Interrupted", self.brain().system)

    def test_disk_failure_does_not_break_reply(self):
        brain = self.brain()
        brain._run = lambda speak: speak("Hello.")
        speak = mock.Mock()
        with mock.patch.object(memory, "record_turn", side_effect=OSError), mock.patch.object(jarvis.hud, "emit") as emit:
            brain.ask("hello", speak)
        speak.assert_called_once_with("Hello.")
        emit.assert_called_once()
