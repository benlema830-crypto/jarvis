"""Phase B2: incremental scanning/indexing that never trades correctness for speed."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

import knowledge
import privacy
import semantic_search as search
import retrieval_fixture as fixture
from test_hybrid_search import fake_embed


class SearchIndexTest(unittest.TestCase):
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
        self.embedded = []

        def embed(texts):
            self.embedded.extend(texts)
            return fake_embed(texts)
        for patcher in (mock.patch.object(search, 'identity', return_value='local:test'),
                        mock.patch.object(search, 'embed', side_effect=embed)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(search.reset_cache)

    def rows(self):
        with closing(sqlite3.connect(search.STORE)) as db:
            return db.execute('SELECT COUNT(*) FROM vectors').fetchone()[0]

    def test_unchanged_vault_reembeds_only_the_query(self):
        search.search('relief valve')
        self.embedded.clear()
        search.search('relief valve')
        self.assertEqual(self.embedded, ['relief valve'])

    def test_editing_one_note_reembeds_only_that_note(self):
        search.search('relief valve')
        self.embedded.clear()
        (self.vault / 'Parts/Relief valve.md').write_text('# Relief valve\nNow opens at 4 bar.\n', encoding='utf-8')
        result = search.search('relief valve')
        self.assertEqual(len(self.embedded), 2)  # the edited chunk and the query
        self.assertIn('4 bar', next(r for r in result['results'] if r['path'] == 'Parts/Relief valve.md')['excerpt'])

    def test_unchanged_files_are_not_reread(self):
        knowledge.notes()
        with mock.patch.object(knowledge, 'read', wraps=knowledge.read) as read:
            knowledge.notes()
            self.assertEqual(read.call_count, 0)
            (self.vault / 'Garden/Tomatoes.md').write_text('# Tomatoes\nWater daily in heatwaves.\n', encoding='utf-8')
            (self.vault / 'Garden/Basil.md').write_text('# Basil\nPinch the flowers.\n', encoding='utf-8')
            found, _ = knowledge.notes()
            self.assertEqual(sorted(c.args[0] for c in read.call_args_list), ['Garden/Basil.md', 'Garden/Tomatoes.md'])
        self.assertIn('Water daily', next(n for n in found if n['path'] == 'Garden/Tomatoes.md')['content'])

    def test_scan_cache_keeps_path_security(self):
        knowledge.notes()
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'Secret.md').write_text('# Secret\noutside the vault', encoding='utf-8')
        try:
            (self.vault / 'Linked').symlink_to(outside, target_is_directory=True)
        except OSError:
            try:  # junctions need no special rights on Windows
                import _winapi
                _winapi.CreateJunction(str(outside), str(self.vault / 'Linked'))
            except (ImportError, OSError):
                self.skipTest('Cannot create a symlink or junction here.')
        self.assertNotIn('Linked/Secret.md', [n['path'] for n in knowledge.notes()[0]])
        self.assertNotIn('outside the vault', str(search.search('Secret outside')['results']))

    def test_deleted_note_vectors_are_purged_and_never_returned(self):
        search.search('Zephyr codename')
        before = self.rows()
        fixture.delete_and_edit(self.vault)
        result = search.search('Zephyr codename cancelled')
        self.assertNotIn('Old/Retired plan.md', [r['path'] for r in result['results']])
        self.assertEqual(self.rows(), before - 1)  # deleted note purged; edited note replaced, not duplicated

    def test_restart_reuses_saved_vectors(self):
        search.search('relief valve')
        search.reset_cache()  # a fresh process
        self.embedded.clear()
        search.search('relief valve')
        self.assertEqual(self.embedded, ['relief valve'])

    def test_concurrent_searches_are_safe_and_consistent(self):
        outputs, errors = [], []

        def run():
            try:
                outputs.append([r['path'] for r in search.search('PN-4471-B bracket')['results']])
            except Exception as error:  # pragma: no cover - reported below
                errors.append(error)
        threads = [threading.Thread(target=run) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertTrue(all(out == outputs[0] for out in outputs))
        self.assertEqual(outputs[0][0], 'Parts/Mounting bracket.md')

    def test_large_first_index_is_bounded_and_backfilled(self):
        for i in range(120):
            (self.vault / f'Bulk/Note {i:03d}.md').parent.mkdir(exist_ok=True)
            (self.vault / f'Bulk/Note {i:03d}.md').write_text(f'# Bulk {i}\nfiller about pumps {i}\n', encoding='utf-8')
        with mock.patch.object(search, 'EMBED_BUDGET', 0):
            first = search.search('PN-4417 relief valve')
            self.assertGreater(first['diagnostics']['pending_chunks'], 0)
            self.assertEqual(first['results'][0]['path'], 'Parts/Relief valve.md')  # keyword still answers
            search.wait_for_backfill(10)
            self.embedded.clear()
            second = search.search('PN-4417 relief valve')
        self.assertEqual(second['diagnostics']['pending_chunks'], 0)
        self.assertEqual(self.embedded, ['PN-4417 relief valve'])

    def test_corrupt_index_is_set_aside_and_rebuilt(self):
        search.STORE.write_bytes(b'not a database' * 200)
        first = search.search('relief valve')
        self.assertEqual(first['results'][0]['path'], 'Parts/Relief valve.md')
        self.assertTrue(list(search.STORE.parent.glob('vectors.sqlite3.corrupt-*')))
        self.assertEqual(search.search('relief valve')['mode'], 'hybrid')

    def test_graph_index_still_reports_links(self):
        data = knowledge.index()
        self.assertIn({'source': 'Projects/Orion launch tower.md', 'target': 'Parts/Mounting bracket.md'}, data['links'])


if __name__ == '__main__':
    unittest.main()
