"""Phase A3: the injected memory section is bounded, and every stored fact stays retrievable."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

import memory
import privacy
import tools


class PromptBudgetTest(unittest.TestCase):
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

    def write(self, records):
        Path(memory.PATH).write_text(json.dumps(records), encoding='utf-8')

    def many(self, count=200):
        self.write([{'fact': f'Synthetic fact {i:03d}: the user tracks widget batch WB-{1000 + i} '
                             + 'with a deliberately long description ' * 2, 't': 1_700_000_000 + i}
                    for i in range(count)])

    def test_small_memory_is_injected_in_full(self):
        memory.remember('The user likes tea.')
        memory.remember('The user drives a blue car.')
        self.assertEqual(memory.prompt_section(), '- The user likes tea.\n- The user drives a blue car.')

    def test_large_memory_prompt_is_bounded_and_says_more_exist(self):
        self.many()
        section = memory.prompt_section()
        self.assertLessEqual(len(section), memory.PROMPT_BUDGET + 300)
        self.assertIn('recall_memory', section)
        # Newest facts are preferred; the listing itself stays chronological.
        self.assertIn('WB-1199', section)
        self.assertNotIn('WB-1000 ', section)
        lines = [line for line in section.splitlines() if line.startswith('- ')]
        self.assertEqual(lines, sorted(lines))
        self.assertEqual(section, memory.prompt_section())  # deterministic

    def test_non_injected_fact_is_still_found_on_demand(self):
        self.many()
        self.assertNotIn('WB-1003 ', memory.prompt_section())
        found = memory.recall('widget batch WB-1003')
        self.assertIn('WB-1003 ', found)
        self.assertIn('WB-1003 ', tools.TOOLS_BY_NAME['recall_memory'].call({'query': 'WB-1003'}))

    def test_core_facts_stay_injected_even_when_old(self):
        self.many()
        records = json.loads(Path(memory.PATH).read_text())
        records[0] = {'fact': "The user's name is Sam.", 't': 1_000, 'core': True}
        self.write(records)
        self.assertIn("The user's name is Sam.", memory.prompt_section())

    def test_remember_can_mark_core_and_duplicates_upgrade(self):
        memory.remember("The user's name is Sam.")
        self.assertEqual(memory.remember("The user's name is Sam.", core=True), 'Already remembered.')
        self.assertTrue(json.loads(Path(memory.PATH).read_text())[0].get('core'))

    def test_deleted_facts_neither_injected_nor_recalled(self):
        memory.remember("The user's locker code is 4471.")
        memory.remember('The user likes tea.')
        memory.forget('locker code')
        self.assertNotIn('4471', memory.prompt_section())
        self.assertNotIn('4471', memory.recall('locker code'))
        self.assertIn('No saved fact', memory.recall('locker code'))

    def test_recall_is_redacted_and_bounded(self):
        privacy.configure(['Project Nightjar'])
        self.write([{'fact': 'The user works on Project Nightjar launches.', 't': 1}])
        result = memory.recall('launches')
        self.assertNotIn('Nightjar', result)
        self.many()
        self.assertLessEqual(memory.recall('widget', limit=50).count('\n- '), 20)

    def test_recall_requires_word_match_not_substring_noise(self):
        memory.remember('The user plays the cello.')
        memory.remember('The user likes cellophane art.')
        self.assertEqual(memory.recall('cello').count('\n- '), 1)


if __name__ == '__main__':
    unittest.main()
