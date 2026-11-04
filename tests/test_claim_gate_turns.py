"""The gate working inside a real Brain turn: a false report isn't spoken, and the brain gets to answer again."""
import unittest
from unittest import mock

import jarvis
import truth_guard


class GateInTurnTest(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(jarvis.memory, "record_turn"),
                        mock.patch.object(jarvis.performance, "record_turn"),
                        mock.patch.object(jarvis.router, "choose", return_value=None),
                        mock.patch.object(truth_guard, "LOG", mock.MagicMock())):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.brain = jarvis.Brain()
        self.spoken = []
        self.prompts = []

    def scripted(self, *replies):
        """Each run: record what the model was asked, then 'say' its reply, sometimes after using a tool."""
        replies = iter(replies)

        def run(deliver):
            self.prompts.append(self.brain.messages[-1]["content"])
            for step in next(replies):
                if step == "TOOL":
                    truth_guard.note_tool("home_control", ok=True)
                else:
                    deliver(step)
            self.brain.messages.append({"role": "assistant", "content": "reply"})
        return mock.patch.object(self.brain, "_run", run)

    def ask(self, text):
        self.brain.ask(text, self.spoken.append)

    def test_unbacked_claim_is_never_spoken_and_the_brain_answers_again(self):
        with self.scripted(["Right then.", "I've turned the fan off.", "Sleep well."], ["I haven't touched the fan yet."]):
            self.ask("is the fan off?")
        self.assertEqual(self.spoken, ["Right then.", "I haven't touched the fan yet."])
        self.assertIn("[CLAIM CHECK", self.prompts[1])
        self.assertIn("I've turned the fan off. Sleep well.", self.prompts[1])

    def test_claim_with_a_tool_behind_it_is_spoken_first_time(self):
        with self.scripted(["TOOL", "I've turned the fan off."]):
            self.ask("turn the fan off")
        self.assertEqual(self.spoken, ["I've turned the fan off."])
        self.assertEqual(len(self.prompts), 1)

    def test_tool_used_on_the_retry_lets_the_claim_through(self):
        with self.scripted(["I've turned the fan off."], ["TOOL", "I've turned the fan off."]):
            self.ask("turn the fan off")
        self.assertEqual(self.spoken, ["I've turned the fan off."])

    def test_it_only_retries_once(self):
        with self.scripted(["I've done that."], ["I've definitely done that."], ["never asked"]):
            self.ask("do that")
        self.assertEqual(self.spoken, ["I've definitely done that."])
        self.assertEqual(len(self.prompts), 2)

    def test_system_messages_are_exempt(self):
        with self.scripted(["I've switched the fan off for you."]):
            self.ask("[MORNING WAKE-UP] Wake them.")
        self.assertEqual(self.spoken, ["I've switched the fan off for you."])

    def test_the_phone_counts_as_the_owner(self):
        with self.scripted(["I've turned it off."], ["I can't confirm that."]):
            self.ask("[Via Phone] turn it off")
        self.assertEqual(self.spoken, ["I can't confirm that."])

    def test_history_stays_consistent_for_the_next_turn(self):
        with self.scripted(["I've done it."], ["Actually I haven't."], ["Next answer."]):
            self.ask("do it")
            self.ask("what now?")
        roles = [m["role"] for m in self.brain.messages]
        self.assertEqual(roles, ["user", "assistant", "user", "assistant", "user", "assistant"])

    def test_tools_from_an_earlier_turn_back_nothing(self):
        with self.scripted(["TOOL", "Sent."], ["I've turned it on."], ["Not yet."]):
            self.ask("first")
            self.ask("second")
        self.assertEqual(self.spoken, ["Sent.", "Not yet."])


if __name__ == "__main__":
    unittest.main()
