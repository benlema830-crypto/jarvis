import unittest
from unittest import mock

import claude_code_brain
import jarvis
import model_provider


class RenderTest(unittest.TestCase):
    def test_single_message_is_sent_as_is(self):
        self.assertEqual(claude_code_brain.render([{"role": "user", "content": "Hi"}]), "Hi")

    def test_history_becomes_context_then_the_new_request(self):
        text = claude_code_brain.render([{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"},
                                         {"role": "user", "content": "C"}])
        self.assertIn("User: A", text)
        self.assertIn("You said: B", text)
        self.assertTrue(text.endswith("The user now says: C"))

    def test_tool_images_and_text_become_mcp_blocks(self):
        blocks = claude_code_brain._mcp_content([
            {"type": "text", "text": "hello"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}])
        self.assertEqual(blocks, [{"type": "text", "text": "hello"},
                                  {"type": "image", "data": "QUJD", "mimeType": "image/jpeg"}])


class FallbackTest(unittest.TestCase):
    def brain(self, error):
        b = jarvis.Brain.__new__(jarvis.Brain)
        b.config = {"provider": "claude_code", "model": "claude-opus-5-5"}
        b.system, b.messages, b.cancel, b._limit_notice = "sys", [{"role": "user", "content": "hi"}], mock.Mock(), 0.0
        b.cancel.is_set.return_value = False
        b._claude_code_brain = mock.Mock()
        b._claude_code_brain.ask.side_effect = error
        return b

    def test_plan_limit_stops_and_says_so_whatever_the_settings(self):
        for settings in ({}, {"subscription_only": False}, {"subscription_only": True}):
            b = self.brain(claude_code_brain.LimitReached("limit"))
            b._run = mock.Mock()
            with mock.patch.object(jarvis.preferences, "read", return_value=settings):
                with self.assertRaisesRegex(model_provider.ProviderError, "usage limit"):
                    b._run_claude_code(lambda s: None)
            b._run.assert_not_called()  # there is no other path to fall back to
            self.assertEqual(b.config["provider"], "claude_code")

    def test_no_api_client_exists_in_the_main_loop(self):
        self.assertFalse(hasattr(jarvis, "anthropic"))
        self.assertFalse(hasattr(jarvis.Brain, "_run_openai"))
        b = jarvis.Brain.__new__(jarvis.Brain)
        b.config = {"provider": "anthropic", "model": "claude-opus-5-5"}
        with self.assertRaises(model_provider.ProviderError):
            b._run(lambda s: None)

    def test_api_key_in_use_stops_instead_of_billing(self):
        b = self.brain(claude_code_brain.WouldBillAPI("ANTHROPIC_API_KEY"))
        b._run = mock.Mock()
        with self.assertRaises(model_provider.ProviderError):
            b._run_claude_code(lambda s: None)
        b._run.assert_not_called()


class CatalogTest(unittest.TestCase):
    def test_plan_models_are_listed_and_count_as_subscription(self):
        self.assertIn("claude-opus-5-5", model_provider.catalog()["claude_code"])
        self.assertIn("claude_code", model_provider.SUBSCRIPTION_PROVIDERS)


if __name__ == "__main__":
    unittest.main()
