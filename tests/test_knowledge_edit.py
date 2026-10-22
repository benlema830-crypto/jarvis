"""Phase C2: version-checked, approval-gated edits to existing notes. create() stays create-only."""
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import knowledge
import tools

NOTE = ('---\nstatus: active\nowner: Sam\n---\n# Orion launch tower\nIntro line.\n\n## Status\nBolts torqued.\n'
        'Paint pending.\n\n## Risks\n- Wind loads\n\n```\n## Status\nnot a heading (code)\n```\n\n## Log\nDay one.\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class KnowledgeEditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'vault'
        self.root.mkdir()
        patcher = mock.patch.object(knowledge, 'VAULT', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = self.root / 'Projects' / 'Orion.md'
        self.path.parent.mkdir()
        self.path.write_bytes(NOTE.encode('utf-8'))

    def edit(self, action='replace_section', target='Status', content='Paint finished.', expected=None):
        return knowledge.plan_edit('Projects/Orion.md', action, target, content,
                                   sha(self.path) if expected is None else expected)

    def test_read_reports_hash_for_version_checks(self):
        self.assertEqual(knowledge.read('Projects/Orion.md')['sha256'], sha(self.path))

    def test_replace_changes_only_the_target_section(self):
        plan = self.edit()
        self.assertIn('-Bolts torqued.', plan['diff'])
        self.assertIn('+Paint finished.', plan['diff'])
        knowledge.apply_edit(plan)
        text = self.path.read_text(encoding='utf-8')
        self.assertEqual(text, NOTE.replace('Bolts torqued.\nPaint pending.\n', 'Paint finished.\n'))
        self.assertIn('not a heading (code)', text)  # the fenced fake heading was never a target

    def test_append_and_frontmatter_preserve_everything_else(self):
        knowledge.apply_edit(self.edit('append_to_section', 'Risks', '- Lightning'))
        knowledge.apply_edit(self.edit('set_frontmatter', 'status', 'superseded'))
        text = self.path.read_text(encoding='utf-8')
        # The Risks section runs to "## Log" (the fenced "## Status" is code); appends go after its last line.
        expected = NOTE.replace('```\n\n## Log', '```\n- Lightning\n\n## Log').replace('status: active', 'status: superseded')
        self.assertEqual(text, expected)

    def test_frontmatter_is_added_when_missing(self):
        self.path.write_text('# Plain\nBody.\n', encoding='utf-8')
        knowledge.apply_edit(self.edit('set_frontmatter', 'status', 'superseded'))
        self.assertEqual(self.path.read_text(encoding='utf-8'), '---\nstatus: superseded\n---\n# Plain\nBody.\n')

    def test_stale_hash_is_rejected_without_writing(self):
        with self.assertRaisesRegex(ValueError, 'changed since'):
            self.edit(expected='0' * 64)
        self.assertEqual(self.path.read_bytes(), NOTE.encode('utf-8'))

    def test_change_during_approval_is_a_conflict_not_an_overwrite(self):
        plan = self.edit()
        self.path.write_text(NOTE + 'Typed in Obsidian meanwhile.\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed since'):
            knowledge.apply_edit(plan)
        self.assertIn('Typed in Obsidian meanwhile.', self.path.read_text(encoding='utf-8'))

    def test_note_deleted_before_write_is_not_recreated(self):
        plan = self.edit()
        self.path.unlink()
        with self.assertRaises(ValueError):
            knowledge.apply_edit(plan)
        self.assertFalse(self.path.exists())

    def test_ambiguous_missing_and_invalid_targets(self):
        self.path.write_text('# A\n## Notes\none\n## Notes\ntwo\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Several'):
            self.edit(target='Notes')
        with self.assertRaisesRegex(ValueError, 'No heading'):
            self.edit(target='Missing')
        with self.assertRaises(ValueError):
            self.edit(action='set_frontmatter', target='bad key!', content='x')
        with self.assertRaises(ValueError):
            self.edit(action='set_frontmatter', target='status', content='two\nlines')
        with self.assertRaises(ValueError):
            self.edit(action='delete_note')

    def test_path_security_matches_reads(self):
        (self.root / '.obsidian').mkdir()
        (self.root / '.obsidian' / 'x.md').write_text('# x', encoding='utf-8')
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'Target.md').write_text('# Target\n## Status\nkeep\n', encoding='utf-8')
        linked = False
        try:
            import _winapi
            _winapi.CreateJunction(str(outside), str(self.root / 'Linked'))
            linked = True
        except (ImportError, OSError):
            pass
        for path in ['../outside/Target.md', '.obsidian/x.md', 'Projects/Orion.txt', 'Missing.md',
                     *(['Linked/Target.md'] if linked else [])]:
            with self.assertRaises(ValueError, msg=path):
                knowledge.plan_edit(path, 'replace_section', 'Status', 'x', '0' * 64)
        self.assertEqual((outside / 'Target.md').read_text(encoding='utf-8'), '# Target\n## Status\nkeep\n')

    def test_oversized_results_and_files_are_refused(self):
        with self.assertRaises(ValueError):
            self.edit(content='x' * (knowledge.MAX_BYTES + 10))

    def test_crlf_and_bom_are_preserved(self):
        self.path.write_bytes(b'\xef\xbb\xbf# T\r\n## Status\r\nold\r\n## Next\r\nkeep\r\n')
        knowledge.apply_edit(self.edit(content='new\nlines'))
        self.assertEqual(self.path.read_bytes(), b'\xef\xbb\xbf# T\r\n## Status\r\nnew\r\nlines\r\n## Next\r\nkeep\r\n')

    def test_concurrent_applies_cannot_both_win(self):
        plans = [self.edit(content='first'), self.edit(content='second')]
        outcomes = []

        def run(plan):
            try:
                knowledge.apply_edit(plan)
                outcomes.append('ok')
            except ValueError:
                outcomes.append('conflict')
        threads = [threading.Thread(target=run, args=(p,)) for p in plans]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes), ['conflict', 'ok'])

    def test_create_still_never_overwrites(self):
        with self.assertRaises(ValueError):
            knowledge.create('Projects/Orion.md', '# Replacement')
        self.assertEqual(self.path.read_bytes(), NOTE.encode('utf-8'))

    def test_tool_requires_spoken_approval(self):
        call = tools.TOOLS_BY_NAME['update_knowledge_note'].call
        args = {'path': 'Projects/Orion.md', 'action': 'replace_section', 'target': 'Status',
                'content': 'Paint finished.', 'expected_sha256': sha(self.path)}
        import queue
        commands = queue.Queue()
        with mock.patch.object(tools.hud, 'commands', commands):
            with mock.patch('approvals.ask', return_value=(False, 'no')) as ask:
                self.assertIn('confirmation', call(args))
                self.assertIn('not approved', commands.get(timeout=5)['say'])
            self.assertIn('Projects/Orion.md', ask.call_args.args[0])
            self.assertEqual(self.path.read_bytes(), NOTE.encode('utf-8'))
            with mock.patch('approvals.ask', return_value=(True, 'yes')):
                call(args)
                report = commands.get(timeout=5)
        self.assertIn(sha(self.path), report['note'])  # follow-up edits can use the new version
        self.assertIn('Paint finished.', self.path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
