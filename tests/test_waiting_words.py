"""A slow tool gets a few spoken words; a fast one, a system turn or a phone message does not."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import jarvis


def brain():
    b = jarvis.Brain.__new__(jarvis.Brain)
    b._tool_wait = None
    return b


class ToolWrapper(unittest.TestCase):
    def test_slow_tool_calls_the_notifier_with_its_name(self):
        b, seen = brain(), []
        b._tool_wait = seen.append
        with mock.patch.object(jarvis, "WAIT_BEFORE_WORDS", 0.02), \
                mock.patch.object(jarvis, "run_tool", side_effect=lambda block: time.sleep(0.15) or {"content": "ok"}):
            result = b._tool(SimpleNamespace(name="look_at_screen"))
        self.assertEqual(result, {"content": "ok"})
        self.assertEqual(seen, ["look_at_screen"])

    def test_fast_tool_stays_silent(self):
        b, seen = brain(), []
        b._tool_wait = seen.append
        with mock.patch.object(jarvis, "WAIT_BEFORE_WORDS", 0.2), \
                mock.patch.object(jarvis, "run_tool", return_value={"content": "ok"}):
            b._tool(SimpleNamespace(name="home_status"))
        time.sleep(0.3)
        self.assertEqual(seen, [])

    def test_a_failing_tool_still_cancels_the_timer(self):
        b, seen = brain(), []
        b._tool_wait = seen.append
        with mock.patch.object(jarvis, "WAIT_BEFORE_WORDS", 0.1), \
                mock.patch.object(jarvis, "run_tool", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                b._tool(SimpleNamespace(name="run_command"))
        time.sleep(0.2)
        self.assertEqual(seen, [])

    def test_without_a_notifier_the_tool_just_runs(self):
        with mock.patch.object(jarvis, "run_tool", return_value={"content": "ok"}) as run:
            self.assertEqual(brain()._tool(SimpleNamespace(name="x")), {"content": "ok"})
        run.assert_called_once()


class WholeTurn(unittest.TestCase):
    def ask(self, text, tool_seconds, then_say="The screen shows your editor."):
        b = jarvis.Brain.__new__(jarvis.Brain)
        b.selection = mock.Mock()
        b.selection.begin.return_value = {"provider": "claude_code", "model": "m"}
        b.config = {"provider": "claude_code", "model": "m"}
        b.messages, b._state, b._local, b._turn_privacy = [], "", None, None
        b.cancel, b._speech_lock = threading.Event(), threading.Lock()
        b._refresh_context = lambda: None
        b._working_state = lambda: ""
        b._save_turn = lambda *a, **k: None

        def run(speak):
            b._tool(SimpleNamespace(name="look_at_screen"))
            speak(then_say)
        b._run = run
        said = []
        with mock.patch.object(jarvis, "WAIT_BEFORE_WORDS", 0.05), \
                mock.patch.object(jarvis, "run_tool", side_effect=lambda block: time.sleep(tool_seconds) or {"content": "ok"}), \
                mock.patch.object(jarvis, "NO_REPLY", jarvis.NO_REPLY), \
                mock.patch.object(jarvis.performance, "record_turn"), mock.patch.object(jarvis.hud, "emit"):
            b.ask(text, said.append)
        return said

    def test_slow_tool_is_announced_before_the_answer(self):
        self.assertEqual(self.ask("what's on my screen", 0.25), ["Taking a look.", "The screen shows your editor."])

    def test_fast_tool_gets_only_the_answer(self):
        self.assertEqual(self.ask("what's on my screen", 0.0), ["The screen shows your editor."])

    def test_system_turns_never_get_waiting_words(self):
        self.assertEqual(self.ask("[REMINDER DUE] tell them", 0.25), ["The screen shows your editor."])

    def test_phone_and_telegram_replies_never_get_waiting_words(self):
        self.assertEqual(self.ask("[Via Telegram] what's on my screen", 0.25), ["The screen shows your editor."])

    def test_waiting_words_never_claim_a_result(self):
        import truth_guard
        for sentence in [*jarvis.WAITING_WORDS.values(), "One moment."]:
            self.assertFalse(truth_guard.claims_action(sentence), sentence)


class FactsDoNotRestartTheSession(unittest.TestCase):
    def test_a_changed_prompt_reuses_the_connected_claude_session(self):
        import claude_code_brain
        b = claude_code_brain.ClaudeCodeBrain.__new__(claude_code_brain.ClaudeCodeBrain)
        b.client, b.model, b.system, b.sent_messages = object(), "m", "old prompt", 0
        connects = []
        b._connect = lambda *a: connects.append(a)

        def sync(coroutine, timeout=None):
            coroutine.close()
            return "answer"
        b._sync = sync
        messages = [{"role": "user", "content": "hi"}]
        self.assertEqual(b.ask("m", "new prompt with one more fact", messages, [], None, lambda t: None,
                               threading.Event()), "answer")
        self.assertEqual(connects, [])

    def test_a_different_model_still_reconnects(self):
        import claude_code_brain
        b = claude_code_brain.ClaudeCodeBrain.__new__(claude_code_brain.ClaudeCodeBrain)
        b.client, b.model, b.system, b.sent_messages = object(), "m", "p", 0
        calls = []

        def sync(coroutine, timeout=None):
            calls.append(coroutine.__name__ if hasattr(coroutine, "__name__") else "c")
            coroutine.close()
            return "answer"
        b._sync = sync
        b.ask("other", "p", [{"role": "user", "content": "hi"}], [], None, lambda t: None, threading.Event())
        self.assertIn("_connect", calls)


if __name__ == "__main__":
    unittest.main()
