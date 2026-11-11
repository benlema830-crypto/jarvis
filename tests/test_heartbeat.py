"""Heartbeat: plain checks reported once, the owner's checklist asked quietly, nothing invented."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import heartbeat
import jarvis
import knowledge


class BeatTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.problem = {"home": ""}
        self.beat = heartbeat.Beat({"home": lambda: self.problem["home"]}, clock=lambda: self.now)

    def tick(self, minutes=30):
        self.now += minutes * 60
        return self.beat.run()

    def test_a_blip_is_not_reported(self):
        self.problem["home"] = "I can't reach Home Assistant."
        self.assertEqual(self.tick(), [])       # first sighting: wait for a second beat
        self.problem["home"] = ""
        self.assertEqual(self.tick(), [])       # gone again, and nothing was said, so no "it's back" either

    def test_a_standing_problem_is_said_once_then_again_after_six_hours(self):
        self.problem["home"] = "I can't reach Home Assistant."
        said = [self.tick() for _ in range(14)]  # seven hours of half-hour beats
        told = [n for n, out in enumerate(said) if out]
        self.assertEqual(told, [1, 13])
        self.assertEqual(said[1], ["I can't reach Home Assistant."])

    def test_recovery_is_announced_once(self):
        self.problem["home"] = "I can't reach Home Assistant."
        self.tick(); self.tick()
        self.problem["home"] = ""
        self.assertEqual(self.tick(), ["Home Assistant is reachable again."])
        self.assertEqual(self.tick(), [])

    def test_a_check_that_crashes_reports_nothing(self):
        beat = heartbeat.Beat({"home": mock.Mock(side_effect=RuntimeError("boom"))}, clock=lambda: self.now)
        self.assertEqual([beat.run(), beat.run(), beat.run()], [[], [], []])


class ChecklistTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / "vault"
        self.vault.mkdir()
        patcher = mock.patch.object(knowledge, "VAULT", self.vault)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_unticked_top_level_lines_count(self):
        (self.vault / heartbeat.NOTE).write_text(
            "# Jarvis heartbeat\n\n    - [ ] an indented example\n\n## Keep an eye on\n\n"
            "- [ ] Tell me if the build branch has new commits.\n- [x] Done already.\n* [ ] Check the fan at ten.\n- plain line\n",
            encoding="utf-8")
        self.assertEqual(heartbeat.checklist(), ["Tell me if the build branch has new commits.", "Check the fan at ten."])

    def test_the_template_has_no_active_lines_so_it_costs_nothing(self):
        (self.vault / heartbeat.NOTE).write_text(heartbeat.TEMPLATE, encoding="utf-8")
        self.assertEqual(heartbeat.checklist(), [])

    def test_missing_note_or_vault_is_quietly_empty_and_tests_create_nothing(self):
        self.assertEqual(heartbeat.checklist(), [])
        self.assertFalse((self.vault / heartbeat.NOTE).exists())
        with mock.patch.object(knowledge, "VAULT", self.vault / "gone"):
            self.assertEqual(heartbeat.checklist(), [])

    def test_prompt_asks_for_quiet_and_no_changes(self):
        text = heartbeat.prompt(["Check the fan at ten."])
        self.assertTrue(text.startswith("[HEARTBEAT]"))
        self.assertIn("- Check the fan at ten.", text)
        self.assertIn("(quiet)", text)
        self.assertIn("change nothing", text)
        self.assertTrue(jarvis.truth_guard.system_turn(text))

    def test_settings_defaults_and_off_switch(self):
        with mock.patch.object(heartbeat.preferences, "read", return_value={}):
            self.assertEqual(heartbeat.settings(), {"enabled": True, "minutes": 30, "checklist_minutes": 60})
        with mock.patch.object(heartbeat.preferences, "read", return_value={"heartbeat": {"enabled": False, "minutes": 1}}):
            self.assertEqual(heartbeat.settings(), {"enabled": False, "minutes": 30, "checklist_minutes": 60})


class TurnTest(unittest.TestCase):
    def run_turn(self, reply):
        queued = []
        with mock.patch.object(jarvis, "respond", lambda brain, voice, prompt, speak: [speak(s) for s in reply]), \
                mock.patch.object(jarvis.hud.commands, "put", queued.append):
            voice = mock.Mock()
            jarvis.heartbeat_turn(mock.Mock(), voice, {"prompt": "[HEARTBEAT] ..."})
        voice.say.assert_not_called()  # the check itself is never spoken
        return queued

    def test_quiet_means_nothing_is_queued(self):
        self.assertEqual(self.run_turn(["(quiet)"]), [])
        self.assertEqual(self.run_turn(["(Quiet)."]), [])
        self.assertEqual(self.run_turn([]), [])

    def test_a_finding_becomes_an_ordinary_update(self):
        queued = self.run_turn(["The build branch has two new commits."])
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["say"], "The build branch has two new commits.")
        self.assertTrue(queued[0]["update"])   # so attention.py decides: say it, or hold it


if __name__ == "__main__":
    unittest.main()
