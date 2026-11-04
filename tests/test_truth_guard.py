"""Jarvis must not say he did something when nothing backs it, and agent outcomes must be reported as they were."""
import unittest
from unittest import mock

import truth_guard as tg


class ClaimDetectionTest(unittest.TestCase):
    def test_real_false_claims_from_the_transcripts_are_caught(self):
        for sentence in ("My voice is now set to play through your Bose speaker, and I've set it as default.",
                         "I've opened Outlook for you, sir.",
                         "It's 22:58, sir. I just checked the system clock.",
                         "I've turned the fan off.",
                         "I've just checked, and it's fine.",
                         "I verified the links.",
                         "Done, sir."):
            self.assertTrue(tg.claims_action(sentence), sentence)

    def test_ordinary_speech_is_left_alone(self):
        for sentence in ("No harm done, sir.",
                         "The builder fixed the chair.",
                         "I've got your message, sir.",
                         "I've no tool for that.",
                         "I haven't checked that.",
                         "Shall I check?",
                         "Have I turned it off?",
                         "If I've turned it off, the light will show.",
                         "I'll turn it off once I've checked.",
                         "Distinguish \"I've started\" from \"it's finished\".",
                         "It should work.",
                         "I set the bar low.".replace("set", "keep")):
            self.assertFalse(tg.claims_action(sentence), sentence)

    def test_system_messages_are_not_the_owner(self):
        self.assertTrue(tg.system_turn("[PRESENCE GREETING] Greet them."))
        self.assertTrue(tg.system_turn("[REMINDER DUE] Tell them."))
        self.assertFalse(tg.system_turn("[Via Phone] did it work?"))
        self.assertFalse(tg.system_turn("[Via Telegram voice note] hello"))
        self.assertFalse(tg.system_turn("turn off the fan"))


class ClaimGateTest(unittest.TestCase):
    def setUp(self):
        tg.begin_turn()
        patcher = mock.patch.object(tg, "LOG", mock.MagicMock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unbacked_claim_and_everything_after_it_are_held(self):
        gate = tg.ClaimGate()
        self.assertTrue(gate.admit("Right then."))
        self.assertFalse(gate.admit("I've turned the fan off."))
        self.assertFalse(gate.admit("Anything else is held too."))
        correction = gate.correction()
        self.assertIn("I've turned the fan off. Anything else is held too.", correction)
        self.assertIn("not spoken", correction)
        self.assertTrue(gate.admit("I've turned the fan off."))  # one correction, then the gate is open

    def test_a_successful_tool_backs_the_claim(self):
        gate = tg.ClaimGate()
        tg.note_tool("home_control", ok=True)
        self.assertTrue(gate.admit("I've turned the fan off."))
        self.assertEqual(gate.held, [])

    def test_a_failed_tool_backs_nothing(self):
        gate = tg.ClaimGate()
        tg.note_tool("home_control", ok=False)
        self.assertFalse(gate.admit("I've turned the fan off."))

    def test_each_turn_starts_clean(self):
        tg.note_tool("web_search")
        self.assertTrue(tg.tainted())
        tg.begin_turn()
        self.assertFalse(tg.tainted())
        self.assertEqual(tg.tools_succeeded(), 0)

    def test_disabled_gate_for_system_turns(self):
        gate = tg.ClaimGate(enabled=False)
        self.assertTrue(gate.admit("I've turned the fan off."))


class OutcomeTest(unittest.TestCase):
    def test_outcome_line_is_read_and_removed(self):
        for word in tg.OUTCOMES:
            outcome, text = tg.parse_outcome(f"Here's the report.\n\nOUTCOME: {word}")
            self.assertEqual((outcome, text), (word, "Here's the report."))

    def test_outcome_line_tolerates_formatting(self):
        self.assertEqual(tg.parse_outcome("Report.\n**OUTCOME: partial**")[0], "partial")
        self.assertEqual(tg.parse_outcome("Report.\n`OUTCOME: BLOCKED`")[0], "blocked")
        self.assertEqual(tg.parse_outcome("OUTCOME: failed")[0], "failed")

    def test_the_word_in_a_sentence_is_not_the_outcome_line(self):
        self.assertEqual(tg.parse_outcome("The expected OUTCOME: done was never reached.\nMore text follows here.")[0], "done")

    def test_real_unfinished_reports_without_a_line_are_not_success(self):
        for report in ("I couldn’t begin: no Studio session is connected, and no Roblox Studio process is running. Nothing was changed.",
                       "Studio isn’t running, and no Studio session is connected.",
                       "The TV did not reliably turn on. The fix remains unresolved."):
            self.assertEqual(tg.parse_outcome(report)[0], "blocked", report)

    def test_ordinary_reports_are_done(self):
        self.assertEqual(tg.parse_outcome("Added the lobby and tested it. Play checks passed.")[0], "done")
        self.assertEqual(tg.parse_outcome("")[0], "done")

    def test_only_done_is_success(self):
        self.assertTrue(tg.is_success("done"))
        for word in ("partial", "blocked", "failed"):
            self.assertFalse(tg.is_success(word))


if __name__ == "__main__":
    unittest.main()
