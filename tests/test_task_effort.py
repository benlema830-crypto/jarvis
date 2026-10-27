import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_sessions
import task_effort


class AdaptiveEffortTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(task_effort, "PATH", Path(self.folder.name) / "task_effort.jsonl")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)

    def choose(self, task="make a Spotify playlist called Focus"):
        return task_effort.choose("screen", task, "low", "medium")[0]

    def test_new_task_uses_normal_effort(self):
        self.assertEqual(self.choose(), "low")

    def test_similar_hard_task_starts_higher(self):
        task_effort.record("screen", "make a Spotify playlist called Gym", "low", False, 90, "Couldn't find it")
        self.assertEqual(self.choose(), "medium")

    def test_unrelated_hard_task_does_not_change_effort(self):
        task_effort.record("screen", "change the desktop wallpaper", "low", False, 90)
        self.assertEqual(self.choose(), "low")

    def test_other_agent_kind_is_ignored(self):
        task_effort.record("terminal", "make a Spotify playlist called Gym", "", False, 90)
        self.assertEqual(self.choose(), "low")

    def test_user_stop_is_not_a_failure(self):
        task_effort.record("screen", "make a Spotify playlist called Gym", "low", False, 5, stopped_by_user=True)
        self.assertEqual(self.choose(), "low")

    def test_mid_task_escalation_counts_as_hard(self):
        task_effort.record("screen", "make a Spotify playlist called Gym", "medium", True, 50, "Done.", escalated=True)
        self.assertEqual(self.choose(), "medium")

    def test_drops_back_after_two_quick_runs_at_higher_effort(self):
        task_effort.record("screen", "make a Spotify playlist called Gym", "low", False, 200)
        task_effort.record("screen", "make a Spotify playlist called Run", "medium", True, 20, "Playlist made.")
        self.assertEqual(self.choose(), "medium")  # one quick run isn't enough evidence
        task_effort.record("screen", "make a Spotify playlist called Chill", "medium", True, 25, "Playlist made.")
        self.assertEqual(self.choose(), "low")

    def test_history_is_capped(self):
        with mock.patch.object(task_effort, "KEEP", 3):
            for n in range(5):
                task_effort.record("screen", f"task {n}", "low", True, 1)
        self.assertEqual(len(task_effort._read()), 3)


class ReadOnlyCommandTest(unittest.TestCase):
    def test_plain_inspection_is_read_only(self):
        for command in [
            '"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -Command "Get-Content a.txt -TotalCount 48; rg -n \'x|y\' src"',
            'git status --short',
            'powershell -Command "Get-ChildItem src | Select-Object -First 5"',
        ]:
            self.assertTrue(agent_sessions.plain_read_command(command), command)

    def test_anything_that_could_change_or_run_things_is_not(self):
        for command in [
            'powershell -Command "Remove-Item x"', 'powershell -Command "Get-Content a > b"',
            'powershell -Command "rg --pre evil x"', 'powershell -Command "Get-Content $(whoami)"',
            'powershell -Command "git -c core.pager=calc log"', 'powershell -Command "Get-Content a | Out-File b"',
            'powershell -Command "[IO.File]::WriteAllText(1,2)"', 'python -c "print(1)"', '',
        ]:
            self.assertFalse(agent_sessions.plain_read_command(command), command)


if __name__ == "__main__":
    unittest.main()
