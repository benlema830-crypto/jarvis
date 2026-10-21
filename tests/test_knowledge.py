from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import knowledge


class KnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        p = patch.object(knowledge, 'VAULT', self.root)
        p.start(); self.addCleanup(p.stop)

    def test_wikilinks_alias_anchor_markdown_and_source_uri(self):
        knowledge.create('Home.md', '# Home\n[[Projects/Alpha|Project]]\n[[Projects/Alpha#Details]]\n[Other](Projects/Beta.md)\n`[[Not a link]]`')
        knowledge.create('Projects/Alpha.md', '# Alpha\n[[Beta]]')
        knowledge.create('Projects/Beta.md', '# Beta\n[Home](../Home.md)')
        data = knowledge.index()
        self.assertEqual(len(data['notes']), 3)
        self.assertEqual(len(data['links']), 4)
        self.assertEqual(data['unresolved'], 0)
        result = knowledge.search('Alpha')[0]
        self.assertEqual(result['path'], 'Projects/Alpha.md')
        self.assertTrue(result['uri'].startswith('obsidian://open?path='))

    def test_live_edits_and_removal(self):
        knowledge.create('One.md', '# One\noldterm')
        self.assertEqual(len(knowledge.search('oldterm')), 1)
        (self.root / 'One.md').write_text('# One\nnewterm', encoding='utf-8')
        self.assertEqual(knowledge.search('oldterm'), [])
        self.assertEqual(len(knowledge.search('newterm')), 1)
        (self.root / 'One.md').unlink()
        self.assertEqual(knowledge.index()['notes'], [])

    def test_no_overwrite_or_escape_or_hidden_reads(self):
        knowledge.create('Keep.md', '# Original')
        with self.assertRaises(ValueError):
            knowledge.create('Keep.md', '# Replacement')
        self.assertEqual(knowledge.read('Keep.md')['content'], '# Original\n')
        for path in ['../outside.md', 'C:/outside.md', '.obsidian/secret.md', 'A/../../outside.md', 'NUL.md', '/absolute.md', 'notes.txt']:
            with self.assertRaises(ValueError, msg=path):
                knowledge.create(path, 'no')

    def test_missing_ambiguous_and_external_links(self):
        knowledge.create('A/Name.md', '# A')
        knowledge.create('B/Name.md', '# B')
        knowledge.create('Index.md', '# Index\n[[Name]] [[Missing]] [Web](https://example.com) ![[image.png]]')
        data = knowledge.index()
        self.assertEqual(data['links'], [])
        self.assertEqual(data['unresolved'], 2)

    def test_hidden_and_oversized_excluded(self):
        (self.root / '.obsidian').mkdir()
        (self.root / '.obsidian' / 'secret.md').write_text('secret')
        (self.root / 'Large.md').write_text('x' * (knowledge.MAX_BYTES + 1))
        data = knowledge.index()
        self.assertEqual(data['notes'], [])
        self.assertEqual(data['skipped'], 1)


if __name__ == '__main__':
    unittest.main()
