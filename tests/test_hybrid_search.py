"""Phase B1: hybrid keyword + semantic vault search with an offline fallback."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import knowledge
import privacy
import semantic_search as search
import tools
import retrieval_fixture as fixture


def fake_embed(texts):
    """Deterministic 'meaning' vectors: shared topics point the same way; IDs carry no meaning."""
    topics = [('oil', 'automobile', 'vehicle', 'car'), ('valve', 'pressure', 'relief', 'bracket', 'part'),
              ('rocket', 'tower', 'structure'), ('pump', 'turbopump', 'risk', 'fmea'),
              ('tea', 'coffee', 'drink'), ('solar', 'hot', 'heat', 'panel'), ('zephyr', 'cancelled', 'codename')]
    vectors = []
    for text in texts:
        low = text.casefold()
        row = [float(sum(word in low for word in group)) for group in topics] + [0.05]
        norm = sum(v * v for v in row) ** .5
        vectors.append([v / norm for v in row])
    return vectors


class HybridSearchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.vault = root / 'vault'
        self.vault.mkdir()
        for module, field, value in [(knowledge, 'VAULT', self.vault), (search, 'STORE', root / 'vectors.sqlite3'),
                                     (privacy, 'STORE', root / 'privacy.json')]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        fixture.build_vault(self.vault)
        self.embed = mock.Mock(side_effect=fake_embed)
        for patcher in (mock.patch.object(search, 'identity', return_value='local:test'),
                        mock.patch.object(search, 'embed', self.embed)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def paths(self, query, **kw):
        return [r['path'] for r in search.search(query, **kw)['results']]

    def test_exact_technical_id_beats_semantic_neighbour(self):
        # Both part notes look identical to the embedder; only the exact ID separates them.
        self.assertEqual(self.paths('PN-4471-B')[0], 'Parts/Mounting bracket.md')
        self.assertEqual(self.paths('PN-4417')[0], 'Parts/Relief valve.md')
        self.assertEqual(self.paths('DWG-0193')[0], 'Drawings/DWG-0193 Rev C.md')

    def test_paraphrase_without_shared_words_is_found(self):
        result = search.search('how often should I service my vehicle')
        self.assertEqual(result['mode'], 'hybrid')
        self.assertEqual(result['results'][0]['path'], 'Notes/Car maintenance.md')
        self.assertIn('semantic', result['results'][0]['matched_by'])

    def test_mixed_query_uses_both_signals(self):
        top = search.search('PN-4471-B bracket on the launch tower')['results'][0]
        self.assertEqual(top['path'], 'Parts/Mounting bracket.md')
        self.assertEqual(sorted(top['matched_by']), ['keyword', 'semantic'])

    def test_offline_embeddings_fall_back_to_keyword_with_reason(self):
        with mock.patch.object(search, 'identity', side_effect=ValueError('offline')):
            result = search.search('PN-4417 relief valve')
        self.assertEqual(result['mode'], 'keyword')
        self.assertIn('ValueError', result['reason'])
        self.assertEqual(result['results'][0]['path'], 'Parts/Relief valve.md')
        self.assertTrue(all(r['search_mode'] == 'keyword' for r in result['results']))

    def test_corrupt_index_and_failed_embedding_fall_back(self):
        search.STORE.write_bytes(b'this is not a database' * 100)
        result = search.search('PN-4417')
        self.assertIn(result['mode'], ('keyword', 'hybrid'))
        self.assertEqual(result['results'][0]['path'], 'Parts/Relief valve.md')
        self.embed.side_effect = ValueError('Invalid embedding response.')
        search.STORE.unlink(missing_ok=True)
        self.assertEqual(search.search('PN-4417')['mode'], 'keyword')

    def test_deleted_and_edited_notes_never_return_stale_content(self):
        self.assertIn('Old/Retired plan.md', self.paths('Project Zephyr codename'))
        fixture.delete_and_edit(self.vault)
        result = search.search('Project Zephyr codename cancelled')
        self.assertNotIn('Old/Retired plan.md', [r['path'] for r in result['results']])
        station = [r for r in search.search('downlink packets')['results'] if r['path'] == 'Projects/Ground station.md']
        self.assertTrue(station and 'X-band' in station[0]['excerpt'] and 'S-band' not in station[0]['excerpt'])

    def test_results_are_unique_and_stably_ordered(self):
        first = search.search('standup team')
        second = search.search('standup team')
        self.assertEqual([r['path'] for r in first['results']], [r['path'] for r in second['results']])
        keys = [r['path'].casefold() for r in first['results']]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(sorted(keys), sorted(['meetings/standup.md', 'archive/standup.md'] + keys[2:]))

    def test_superseded_note_is_labelled_and_ranked_below_current(self):
        results = search.search('hot drinks coffee tea preference')['results']
        paths = [r['path'] for r in results]
        self.assertLess(paths.index('Preferences/Hot drinks 2026.md'), paths.index('Preferences/Hot drinks 2025.md'))
        old = next(r for r in results if r['path'] == 'Preferences/Hot drinks 2025.md')
        self.assertEqual(old.get('status'), 'superseded')

    def test_tool_output_redacts_credentials_and_keeps_injection_as_data(self):
        output = tools.TOOLS_BY_NAME['search_knowledge'].call({'query': 'router admin password email the vault'})
        for secret in fixture.FAKE_SECRETS:
            self.assertNotIn(secret, output)
        results = json.loads(output)
        self.assertIsInstance(results, list)
        injected = [r for r in results if 'IGNORE ALL PREVIOUS INSTRUCTIONS' in json.dumps(r)]
        for result in injected:
            # The text only ever appears as quoted excerpt data, never as a field of its own.
            self.assertNotIn('IGNORE', json.dumps({k: v for k, v in result.items() if k != 'excerpt'}))

    def test_empty_vault_and_zero_keyword_hits(self):
        with mock.patch.object(knowledge, 'VAULT', Path(self.temp.name) / 'missing'):
            self.assertEqual(search.search('anything')['results'], [])
        result = search.search('qqqzzz nonexistent words')
        self.assertTrue(all('semantic' in r['matched_by'] for r in result['results']))

    def test_diagnostics_report_paths_and_timings_without_contents(self):
        diagnostics = search.search('PN-4471-B')['diagnostics']
        self.assertIn('total', diagnostics['timings_ms'])
        self.assertEqual(diagnostics['ranks'][0]['path'], 'Parts/Mounting bracket.md')
        self.assertNotIn('Aluminium', json.dumps(diagnostics))

    def test_keyword_scoring_uses_words_not_letters(self):
        # "X-band" must not match every letter x in unrelated notes.
        fixture.delete_and_edit(self.vault)
        with mock.patch.object(search, 'identity', side_effect=ValueError('offline')):
            self.assertEqual(self.paths('X-band dish downlink')[0], 'Projects/Ground station.md')


if __name__ == '__main__':
    unittest.main()
