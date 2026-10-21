import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import knowledge
import project_memory as memory
import routines
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
                (memory, 'PROJECTS', {'Jarvis': self.root, 'Rocket Frontier': self.root}),
                (routines, 'STORE', self.root / 'routines.json'), (routines, 'REVIEWS', {})]:
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

    def test_review_has_no_effect_and_token_is_one_use(self):
        with patch.object(routines, 'execute_step', return_value={'ok': True}) as effect:
            review = routines.preview('Development mode')
            effect.assert_not_called()
            result = routines.run(review['token'])
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(effect.call_count, 4)
            with self.assertRaises(ValueError): routines.run(review['token'])

    def test_expired_or_modified_review_does_not_run(self):
        with patch.object(routines, 'execute_step') as effect:
            review = routines.preview('Wrap up')
            routines.REVIEWS[review['token']]['expires'] = time.monotonic()-1
            with self.assertRaises(ValueError): routines.run(review['token'])
            review = routines.preview('Wrap up')
            routines.save('Wrap up', {'project':'Jarvis', 'steps':[{'action':'tasks'}]})
            with self.assertRaises(ValueError): routines.run(review['token'])
            effect.assert_not_called()

    def test_failure_stops_remaining_steps_no_automatic_retry(self):
        with patch.object(routines, 'execute_step', side_effect=[{'ok':True}, OSError('injected')]) as effect:
            review = routines.preview('Development mode')
            result = routines.run(review['token'])
            self.assertEqual(result['status'], 'stopped')
            self.assertEqual(effect.call_count, 2)
            self.assertEqual([s['status'] for s in result['steps']], ['completed', 'failed'])

    def test_routines_reject_arbitrary_commands_and_extra_fields(self):
        for step in [{'action':'shell', 'command':'anything'}, {'action':'tasks', 'command':'anything'},
                     {'action':'focus', 'app':'Code.exe', 'minutes':True},
                     {'action':'focus', 'app':'../Code.exe', 'minutes':30}]:
            with self.assertRaises(ValueError): routines.save('No', {'project':'Jarvis','steps':[step]})

    def test_semantic_cache_changes_deletions_and_vault_scope(self):
        knowledge.create('Save.md', '# Persistence\nStore the game state after disconnect.')
        knowledge.create('Food.md', '# Lunch\nSandwiches and tea.')
        calls = []
        def embed(texts):
            calls.append(list(texts))
            return [[1.,0.] if ('Persistence' in text or 'player' in text) else [0.,1.] for text in texts]
        with patch.object(search, 'identity', return_value='local:test'), patch.object(search, 'embed', side_effect=embed):
            result = search.search('player progress')
            self.assertEqual(result['mode'], 'semantic')
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

    def test_cancel_stops_between_steps(self):
        def first(*args):
            routines.cancel()
            return {'done': True}
        with patch.object(routines, 'execute_step', side_effect=first) as effect:
            result = routines.run(routines.preview('Development mode')['token'])
            self.assertEqual(result['status'], 'cancelled')
            self.assertEqual(effect.call_count, 1)

    def test_voice_decline_never_runs_routine(self):
        import tools
        import approvals
        review = {'project':'Jarvis', 'descriptions':['Open folder'], 'token':'token'}
        with patch.object(tools, '_brain', return_value=review) as brain, \
                patch.object(approvals, 'ask', return_value=(False, 'no')):
            result = tools.named_routine.call({'action':'run', 'name':'Development mode'})
            self.assertIn('not approved', result)
            self.assertEqual(brain.call_count, 1)


if __name__ == '__main__':
    unittest.main()
