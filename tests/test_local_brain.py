import threading
import unittest
from unittest import mock

import local_brain
import model_provider


def tool(name):
    return {"name": name, "description": name, "input_schema": {"type": "object", "properties": {}}}


class LocalBrainTests(unittest.TestCase):
    def test_models_lists_chat_models_default_first(self):
        tags = {"models": [{"name": "qwen3:4b"}, {"name": "embeddinggemma:300m"}, {"name": "qwen3.5-agent:latest"},
                           {"name": local_brain.DEFAULT_MODEL}]}
        response = mock.Mock(json=mock.Mock(return_value=tags))
        with mock.patch.object(local_brain.requests.Session, "get", return_value=response):
            self.assertEqual(local_brain.models(), [local_brain.DEFAULT_MODEL, "qwen3:4b"])

    def test_models_empty_when_service_down(self):
        with mock.patch.object(local_brain.requests.Session, "get", side_effect=local_brain.requests.ConnectionError):
            self.assertEqual(local_brain.models(), [])

    def test_only_everyday_tools_are_offered(self):
        names = [d["function"]["name"] for d in local_brain.definitions([tool("open_app"), tool("queue_away_job")])]
        self.assertEqual(names, ["open_app"])

    def test_tool_round_then_answer(self):
        rounds = iter([
            [{"message": {"content": "", "tool_calls": [{"function": {"name": "open_app", "arguments": {"name": "x"}}}]}}],
            [{"message": {"content": "Opened."}}, {"done": True}],
        ])
        run_tool = mock.Mock(return_value={"content": "Opened x"})
        spoken = []
        with mock.patch.object(local_brain, "chat", side_effect=lambda payload, cancel: next(rounds)):
            answer = local_brain.Conversation().ask("m", "sys", [{"role": "user", "content": "open x"}],
                                                    [tool("open_app")], run_tool, spoken.append, threading.Event())
        self.assertEqual(answer, "Opened.")
        self.assertEqual(spoken, ["Opened."])
        self.assertEqual(run_tool.call_args[0][0].input, {"name": "x"})

    def test_tool_outside_the_set_is_not_run(self):
        rounds = iter([
            [{"message": {"tool_calls": [{"function": {"name": "queue_away_job", "arguments": {}}}]}}],
            [{"message": {"content": "Can't."}}],
        ])
        run_tool = mock.Mock()
        with mock.patch.object(local_brain, "chat", side_effect=lambda payload, cancel: next(rounds)):
            local_brain.Conversation().ask("m", "sys", [{"role": "user", "content": "hi"}], [tool("queue_away_job")],
                                           run_tool, lambda s: None, threading.Event())
        run_tool.assert_not_called()

    def test_history_keeps_the_owner_side_and_a_last_question(self):
        messages = [{"role": "user", "content": "build a lamp"},
                    {"role": "assistant", "content": "The workshop is building it now."},
                    {"role": "user", "content": "make it red"},
                    {"role": "assistant", "content": "Red it is. Shall I add a shade?"},
                    {"role": "user", "content": "yes"}]
        self.assertEqual(local_brain.history(messages), [
            {"role": "user", "content": "build a lamp"}, {"role": "user", "content": "make it red"},
            {"role": "assistant", "content": "Shall I add a shade?"}, {"role": "user", "content": "yes"}])

    def test_history_drops_a_last_reply_that_is_not_a_question(self):
        messages = [{"role": "user", "content": "open it"},
                    {"role": "assistant", "content": "Now you can see it."},
                    {"role": "user", "content": "I can't"}]
        self.assertEqual([m["role"] for m in local_brain.history(messages)], ["user", "user"])

    def test_local_is_a_provider(self):
        self.assertIn("local", model_provider.PROVIDERS)


if __name__ == "__main__":
    unittest.main()
