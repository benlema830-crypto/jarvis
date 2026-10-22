"""Phase C1: corrections supersede old facts without hidden copies; matching is never a guess."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import memory
import privacy
import tools


class CorrectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for module, field, value in [(memory, 'PATH', str(root / 'memory.json')),
                                     (memory, 'RECENT_PATH', str(root / 'recent.json')),
                                     (privacy, 'STORE', root / 'privacy.json')]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def stored(self):
        return json.loads(Path(memory.PATH).read_text(encoding='utf-8'))

    def test_outdated_priority_is_replaced_everywhere(self):
        memory.remember('The current project priority is Alpha.', core=True)
        hint = memory.remember('The current project priority is Beta.')
        self.assertIn('correct_memory', hint)  # flags the likely contradiction
        before = memory.privacy_revision()
        result = memory.correct('project priority is Alpha', 'The current project priority is Beta.')
        self.assertTrue(result.startswith('Corrected'))
        self.assertEqual(memory.facts(), ['The current project priority is Beta.'])
        self.assertTrue(self.stored()[0].get('core'))       # flags kept
        self.assertIn('updated', self.stored()[0])
        self.assertNotIn('Alpha', Path(memory.PATH).read_text(encoding='utf-8'))
        self.assertNotIn('Alpha', memory.prompt_section())
        self.assertNotIn('Alpha', memory.recall('project priority'))
        self.assertIn('corrected', memory.recall('project priority'))
        self.assertNotEqual(memory.privacy_revision(), before)  # sessions drop the old wording

    def test_similar_but_unrelated_facts_are_both_kept(self):
        memory.remember("The user's sister likes tea.")
        memory.remember("The user's brother likes tea.")
        self.assertEqual(len(memory.facts()), 2)

    def test_correct_without_prior_remember_replaces_in_place(self):
        memory.remember('The user drives a blue car.')
        memory.remember('The user likes tea.')
        memory.correct('blue car', 'The user drives a red car.')
        self.assertEqual(memory.facts(), ['The user drives a red car.', 'The user likes tea.'])

    def test_unknown_or_ambiguous_correction_changes_nothing(self):
        memory.remember("The user's sister likes tea.")
        memory.remember("The user's brother likes tea.")
        before = Path(memory.PATH).read_bytes()
        self.assertIn('No saved fact', memory.correct('passport', 'The passport expires in 2030.'))
        result = memory.correct('likes tea', 'Someone likes coffee.')
        self.assertIn('Several', result)
        self.assertEqual(Path(memory.PATH).read_bytes(), before)

    def test_ambiguous_forget_deletes_nothing(self):
        memory.remember("The user's sister likes tea.")
        memory.remember("The user's brother likes tea.")
        result = memory.forget('tea')
        self.assertIn('Several', result)
        self.assertEqual(len(memory.facts()), 2)
        self.assertTrue(memory.forget("brother likes tea").startswith('Forgot'))
        self.assertEqual(memory.facts(), ["The user's sister likes tea."])

    def test_exact_text_wins_over_longer_substring_matches(self):
        memory.remember('The user likes tea.')
        memory.remember('The user likes tea with honey on Sundays.')
        self.assertTrue(memory.forget('The user likes tea').startswith('Forgot'))
        self.assertEqual(memory.facts(), ['The user likes tea with honey on Sundays.'])

    def test_legacy_records_can_be_corrected_and_recalled(self):
        Path(memory.PATH).write_text(json.dumps([{'fact': 'The user lives in Leeds.', 't': 1700000000.0}]), encoding='utf-8')
        memory.correct('Leeds', 'The user lives in York.')
        self.assertEqual(self.stored()[0]['t'], 1700000000.0)
        self.assertIn('York', memory.recall('lives'))

    def test_correction_respects_privacy_terms(self):
        privacy.configure(['Project Nightjar'])
        memory.remember('The user leads the Orion project.')
        memory.correct('Orion project', 'The user leads Project Nightjar.')
        self.assertNotIn('Nightjar', Path(memory.PATH).read_text(encoding='utf-8'))

    def test_correct_memory_tool_is_registered(self):
        memory.remember('The user drives a blue car.')
        out = tools.TOOLS_BY_NAME['correct_memory'].call({'old': 'blue car', 'new': 'The user drives a green car.'})
        self.assertTrue(out.startswith('Corrected'))


if __name__ == '__main__':
    unittest.main()
