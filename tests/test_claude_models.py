import unittest

import jarvis
import model_provider


class ClaudeModelsTest(unittest.TestCase):
    def test_sonnet_opus_and_fable_are_selectable(self):
        for model in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"):
            self.assertIn(model, model_provider.catalog()["anthropic"])

    def test_refusal_fallbacks_only_on_models_that_support_them(self):
        self.assertIn("claude-opus-5-5", jarvis.FALLBACK_MODELS)
        self.assertNotIn("claude-haiku-5-5", jarvis.FALLBACK_MODELS)


if __name__ == "__main__":
    unittest.main()
