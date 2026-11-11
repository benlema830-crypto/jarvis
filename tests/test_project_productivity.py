from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge
import project_memory as memory
import semantic_search as search


class ProductivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        for module, field, value in [(knowledge, 'VAULT', self.vault),
                (search, 'STORE', self.root / 'vectors.sqlite'), (memory, 'ROOT', self.root),
                (memory, 'STORE', self.root / 'handoffs'),
                (memory, 'PROJECTS', {'Jarvis': self.root, 'Rocket Frontier': self.root})]:
            p = patch.object(module, field, value); p.start(); self.addCleanup(p.stop)

    def test_handoff_evidence_and_claims_do_not_nest_history(self):
        (self.root / 'PROJECT-HANDOFF.txt').write_text('Unverified claim: all tests passed.')
        with patch.object(memory, '_git', return_value='commit evidence'):
            first = memory.handoff('Jarvis', summary='Reported progress', next_action='Run acceptance tests')
            second = memory.handoff('Jarvis', unresolved='Not tested')
            status = memory.status('Jarvis')
        self.assertEqual(second['previous'], first['id'])
        self.assertNotIn('last_handoff', second['evidence'])
        self.assertEqual(status['last_handoff']['id'], second['id'])
        self.assertIn('Unverified claim', status['reference_notes'][0]['text'])
        self.assertEqual(status['verified'][0]['text'], 'commit evidence')
        self.assertIn('not correctness', status['interpretation'])
        self.assertEqual(len(list((memory.STORE / 'Jarvis').glob('*.json'))), 2)

    def test_project_scope_and_handoff_limits(self):
        for name in ['../Jarvis', 'C:/', 'Unknown']:
            with self.assertRaises(ValueError): memory.status(name)
        with self.assertRaises(ValueError): memory.handoff('Jarvis', summary='x'*6001)

    def test_semantic_cache_changes_deletions_and_vault_scope(self):
        knowledge.create('Save.md', '# Persistence\nStore the game state after disconnect.')
        knowledge.create('Food.md', '# Lunch\nSandwiches and tea.')
        calls = []
        def embed(texts):
            calls.append(list(texts))
            return [[1.,0.] if ('Persistence' in text or 'player' in text) else [0.,1.] for text in texts]
        with patch.object(search, 'identity', return_value='local:test'), patch.object(search, 'embed', side_effect=embed):
            result = search.search('player progress')
            self.assertEqual(result['mode'], 'hybrid')
            self.assertEqual(result['results'][0]['path'], 'Save.md')
            calls.clear(); search.search('player progress')
            self.assertEqual(calls, [['player progress']])
            (self.vault / 'Save.md').unlink()
            self.assertEqual(search.search('player progress')['results'], [])
            (self.vault / 'Food.md').write_text('# Changed\nPersistence')
            self.assertEqual(search.search('player progress')['results'][0]['title'], 'Changed')
            other = self.root / 'other'; other.mkdir()
            with patch.object(knowledge, 'VAULT', other):
                self.assertEqual(search.search('player progress')['results'], [])

    def test_unavailable_semantics_falls_back_honestly(self):
        knowledge.create('Save.md', '# Persistence\nSaved state')
        with patch.object(search, 'identity', side_effect=ValueError('offline')):
            result = search.search('Persistence')
        self.assertEqual(result['mode'], 'keyword')
        self.assertEqual(result['results'][0]['search_mode'], 'keyword')

    def test_semantic_rejects_remote_models(self):
        with patch.dict('os.environ', {'JARVIS_OLLAMA_ENABLED':'1'}), patch.object(search, '_request', side_effect=[{'models':[{'name':search.MODEL,'digest':'d'}]},
                {'capabilities':['embedding'], 'remote_host':'external'}]):
            with self.assertRaises(ValueError): search.identity()

if __name__ == '__main__':
    unittest.main()
