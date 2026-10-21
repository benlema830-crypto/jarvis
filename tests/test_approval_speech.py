import unittest
from unittest import mock

import approvals
import agent_sessions
from jarvis import interruption_command


class ApprovalSpeechTest(unittest.TestCase):
    def test_early_yes_in_wake_mode_reaches_pending_approval(self):
        def speaking(question):
            command = interruption_command("yes", True, "wake", approval_pending=True)
            self.assertEqual(command, "yes")
            self.assertTrue(approvals.answer(command))
        with mock.patch.object(approvals, "on_question", speaking), mock.patch.object(approvals.hud, "emit"):
            self.assertEqual(approvals.ask("May I proceed?"), (True, "yes"))

    def test_unclear_reply_and_question_echo_do_not_decline_or_approve(self):
        def speaking(question):
            for text in ("what's the weather", "May I proceed?", "Can you explain that?", ""):
                self.assertIsNone(approvals.answer(text))
                self.assertIsNotNone(approvals.waiting())
                self.assertFalse(approvals._pending["event"].is_set())
            approvals.answer("yes, go ahead")
        with mock.patch.object(approvals, "on_question", speaking), mock.patch.object(approvals.hud, "emit"):
            self.assertEqual(approvals.ask("May I proceed?"), (True, "yes, go ahead"))

    def test_pending_approval_does_not_remove_owner_check(self):
        self.assertIsNone(interruption_command("yes", False, "wake", approval_pending=True))
        self.assertIsNone(interruption_command("yes", True, "wake", approval_pending=False))
        self.assertEqual(interruption_command("Jarvis, yes", True, "wake", approval_pending=True), "yes")

    def test_short_plain_question_is_preserved(self):
        self.assertEqual(approvals.spoken_question("May I delete the old backup?"), "May I delete the old backup?")

    def test_command_is_never_spoken(self):
        text = "Permission needed to build the project. Command: powershell.exe -Command " + "x" * 2000
        speech = approvals.spoken_question(text)
        self.assertEqual(speech, "Permission needed to build the project.")

    def test_embedded_commands_paths_json_and_long_reasons_fall_back(self):
        for text in ("May I run `python fix.py`?", r"Can I change C:\Users\User\project\file.txt?",
                     'Allow {"filesystem": "all"}?', "May I run powershell -File fix.ps1?", "Words " * 80):
            speech = approvals.spoken_question(text)
            self.assertIn("details on screen", speech)
            self.assertLess(len(speech), 150)

    def test_full_details_are_displayed_but_callback_and_waiting_are_short(self):
        command = "powershell.exe -Command " + "x" * 1000
        heard = []
        def callback(question):
            heard.append(question)
            self.assertEqual(approvals.waiting(), question)
            approvals.answer("yes")
        with mock.patch.object(approvals, "on_question", callback), mock.patch.object(approvals.hud, "emit") as emit:
            result = approvals.ask(command, spoken="The agent wants to install software. May I proceed?")
        self.assertEqual(result, (True, "yes"))
        self.assertEqual(heard, ["The agent wants to install software. May I proceed?"])
        self.assertIn(command, emit.call_args.kwargs["text"])
        self.assertIsNone(approvals.waiting())

    def test_codex_approval_keeps_command_out_of_voice_and_preserves_all_details(self):
        manager = agent_sessions.SessionManager()
        manager.active = "test"
        manager.entries = {"test": {"name": "Test", "mode": "work"}}
        command = "Remove-Item " + "x" * 800
        event = {"method": "item/commandExecution/requestApproval", "params": {"command": command}}
        with mock.patch.object(manager, "publish"), mock.patch.object(approvals, "ask", return_value=(False, "no")) as ask:
            self.assertEqual(manager._approval(event), {"decision": "decline"})
        self.assertIn(command, ask.call_args.args[0])
        self.assertNotIn("Remove-Item", ask.call_args.kwargs["spoken"])
        self.assertIn("delete data", ask.call_args.kwargs["spoken"])
