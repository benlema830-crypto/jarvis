"""2026-11-15: Jarvis said "check that Claude Code is signed in", forgot it, then denied saying it."""
import threading
import unittest
from unittest import mock

import claude_code_brain
import jarvis
import model_provider


def failing_brain(error, says_first=()):
    brain = jarvis.Brain.__new__(jarvis.Brain)
    brain.config = {"provider": "claude_code", "model": "m"}
    brain.selection = mock.Mock(begin=mock.Mock(return_value=brain.config))
    brain.messages, brain.cancel = [], threading.Event()
    brain._speech_lock, brain._turn_privacy = threading.Lock(), None
    brain._refresh_context = mock.Mock()
    brain._working_state = mock.Mock(return_value="")

    def run(deliver):
        for sentence in says_first:
            deliver(sentence)
        brain.messages.append({"role": "assistant", "content": [{"type": "tool_use", "id": "x"}]})
        raise error
    brain._run = run
    return brain


class SpokenErrorIsRememberedTest(unittest.TestCase):
    def ask(self, brain, text="Watch that video"):
        heard = []
        with mock.patch.object(jarvis.memory, "record_turn") as record, \
                mock.patch.object(jarvis.performance, "record_turn"), mock.patch.object(jarvis, "hud"):
            outcome = jarvis.respond(brain, mock.Mock(), text, heard.append)
        return outcome, heard, record

    def test_a_provider_error_he_says_stays_in_his_history(self):
        error = model_provider.ProviderError("My Claude brain broke partway through that, sir.")
        brain = failing_brain(error, says_first=["I'm pulling up your history."])
        outcome, heard, record = self.ask(brain)
        self.assertEqual(outcome, "failed")
        self.assertEqual(heard, ["I'm pulling up your history.", str(error)])
        self.assertEqual([m["role"] for m in brain.messages], ["user", "assistant"])  # no stray tool_use
        last = brain.messages[-1]["content"]
        self.assertIn("I'm pulling up your history.", last)
        self.assertIn(str(error), last)
        record.assert_not_called()  # a failed turn still isn't saved for later launches (test_recent_memory)

    def test_an_unexpected_error_keeps_the_apology_he_said(self):
        brain = failing_brain(ValueError("boom"))
        with mock.patch("builtins.print"):
            _, heard, _ = self.ask(brain)
        self.assertEqual(heard, [jarvis.LOST_TRAIN])
        self.assertIn(jarvis.LOST_TRAIN, brain.messages[-1]["content"])

    def test_the_next_turn_sees_it(self):
        brain = failing_brain(model_provider.ProviderError("Claude Code says its sign-in failed."))
        self.ask(brain)
        rendered = claude_code_brain.render(model_provider.text_history(
            brain.messages + [{"role": "user", "content": "Where do I fix that?"}]))
        self.assertIn("You said: ", rendered)
        self.assertIn("sign-in failed", rendered)


class HonestCauseTest(unittest.TestCase):
    def run_claude(self, error):
        brain = jarvis.Brain.__new__(jarvis.Brain)
        brain.config, brain.system, brain.messages = {"provider": "claude_code", "model": "m"}, "", []
        brain.cancel, brain._tool = threading.Event(), None
        brain._claude_code_brain = mock.Mock(ask=mock.Mock(side_effect=error))
        with self.assertRaises(model_provider.ProviderError) as caught, mock.patch("builtins.print"):
            brain._run_claude_code(lambda s: None)
        return str(caught.exception)

    def test_a_broken_turn_does_not_blame_the_sign_in(self):
        said = self.run_claude(RuntimeError("JSON message exceeded maximum buffer size of 1048576 bytes"))
        self.assertNotIn("sign", said.lower())

    def test_a_real_sign_in_failure_says_how_to_fix_it(self):
        said = self.run_claude(claude_code_brain.SignedOut("authentication_failed"))
        self.assertIn("/login", said)

    def test_big_tool_results_fit(self):
        self.assertGreaterEqual(claude_code_brain.MAX_MESSAGE_BYTES, 32 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()


class FinalTextTest(unittest.TestCase):
    """The screen agent's report is the text after its last tool call, judged in stream order (2026-11-15: its
    notes to itself were read out as the report, because a tool call can run before the note before it arrives)."""

    def test_only_text_after_the_last_tool_call_is_final(self):
        import asyncio
        from claude_agent_sdk import ResultMessage, StreamEvent

        def text(t):
            return StreamEvent(uuid="u", session_id="s", parent_tool_use_id=None,
                               event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": t}})

        def block(kind, name=""):
            return StreamEvent(uuid="u", session_id="s", parent_tool_use_id=None,
                               event={"type": "content_block_start", "content_block": {"type": kind, "name": name}})
        stream = [block("text"), text("Menu is animating; look again."), block("tool_use", "mcp__jarvis__computer"),
                  block("text"), text("Copy link at zoom (505,212)."), block("tool_use", "mcp__jarvis__computer"),
                  block("text"), text("The video is "), text("a JARVIS that actually works."),
                  ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=3,
                                session_id="s")]

        class Client:
            async def query(self, prompt):
                pass

            async def receive_response(self):
                for message in stream:
                    yield message
        brain = claude_code_brain.ClaudeCodeBrain.__new__(claude_code_brain.ClaudeCodeBrain)
        brain.client = Client()
        whole = asyncio.run(brain._turn("go", lambda t: None, threading.Event()))
        self.assertIn("Menu is animating", whole)
        self.assertEqual("".join(brain.final_text), "The video is a JARVIS that actually works.")
