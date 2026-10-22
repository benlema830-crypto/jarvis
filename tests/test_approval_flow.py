"""Tools that need the user's spoken OK must not block the turn that asked for it.

jarvis.main() is one loop: it speaks queued questions and routes the user's next words to
approvals.answer(). A tool that waited for approval inside that loop's own turn would never let
the question be spoken or answered (it timed out to "no" after two minutes)."""
import hashlib
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest import mock

import approvals
import hud
import knowledge
import tools


class LoopHarness(unittest.TestCase):
    def setUp(self):
        self.commands = queue.Queue()
        for patcher in (mock.patch.object(hud, 'commands', self.commands),
                        mock.patch.object(approvals, 'on_question',
                                          lambda text: self.commands.put({'label': 'Needs your OK', 'say': text}))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: approvals.answer('no') if approvals.waiting() else None)

    def call_in_turn(self, tool, args):
        """Run the tool as the main loop would, and require it to hand control back promptly."""
        result = []
        turn = threading.Thread(target=lambda: result.append(tools.TOOLS_BY_NAME[tool].call(args)))
        turn.start()
        turn.join(3)
        self.assertFalse(turn.is_alive(), 'The tool blocked the conversation turn while waiting for approval.')
        return result[0]

    def next_item(self):
        return self.commands.get(timeout=5)


class NoteEditApprovalTest(LoopHarness):
    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        patcher = mock.patch.object(knowledge, 'VAULT', self.vault)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.note = self.vault / 'Orion.md'
        self.note.write_text('# Orion\n## Status\nold\n', encoding='utf-8')
        self.args = {'path': 'Orion.md', 'action': 'replace_section', 'target': 'Status', 'content': 'new',
                     'expected_sha256': hashlib.sha256(self.note.read_bytes()).hexdigest()}

    def test_question_is_spoken_and_yes_applies_the_edit(self):
        self.assertIn('confirmation', self.call_in_turn('update_knowledge_note', self.args))
        self.assertIn('Status', self.next_item()['say'])
        self.assertEqual(self.note.read_text(encoding='utf-8'), '# Orion\n## Status\nold\n')  # nothing yet
        self.assertTrue(approvals.answer('yes'))
        report = self.next_item()
        self.assertIn('Updated', report['say'])
        self.assertEqual(self.note.read_text(encoding='utf-8'), '# Orion\n## Status\nnew\n')

    def test_no_leaves_the_note_untouched(self):
        self.call_in_turn('update_knowledge_note', self.args)
        self.next_item()
        approvals.answer('no')
        self.assertIn('not changed', self.next_item()['say'])
        self.assertEqual(self.note.read_text(encoding='utf-8'), '# Orion\n## Status\nold\n')

    def test_edit_in_obsidian_while_waiting_is_a_conflict(self):
        self.call_in_turn('update_knowledge_note', self.args)
        self.next_item()
        self.note.write_text('# Orion\n## Status\nchanged by hand\n', encoding='utf-8')
        approvals.answer('yes')
        self.assertIn('changed since', self.next_item()['say'])
        self.assertIn('changed by hand', self.note.read_text(encoding='utf-8'))

    def test_invalid_edit_fails_immediately_without_asking(self):
        with self.assertRaises(ValueError):
            tools.TOOLS_BY_NAME['update_knowledge_note'].call(dict(self.args, expected_sha256='0' * 64))
        self.assertTrue(self.commands.empty())


class RoutineApprovalTest(LoopHarness):
    def test_routine_run_asks_without_blocking_and_runs_after_yes(self):
        review = {'project': 'Jarvis', 'descriptions': ['Open folder'], 'token': 'token'}
        with mock.patch.object(tools, '_brain', side_effect=[review, {'ok': True, 'steps': ['Opened']}]) as brain:
            self.assertIn('confirmation', self.call_in_turn('named_routine', {'action': 'run', 'name': 'Dev'}))
            self.assertIn('Run Dev', self.next_item()['say'])
            self.assertEqual(brain.call_count, 1)  # nothing ran before the answer
            approvals.answer('yes')
            report = self.next_item()
        self.assertIn('ROUTINE RESULT', report['prompt'])
        self.assertEqual(brain.call_args.args[1], {'action': 'run', 'token': 'token'})

    def test_routine_decline_never_runs(self):
        review = {'project': 'Jarvis', 'descriptions': ['Open folder'], 'token': 'token'}
        with mock.patch.object(tools, '_brain', return_value=review) as brain:
            self.call_in_turn('named_routine', {'action': 'run', 'name': 'Dev'})
            self.next_item()
            approvals.answer('no')
            self.assertIn('not approved', self.next_item()['say'])
        self.assertEqual(brain.call_count, 1)


if __name__ == '__main__':
    unittest.main()
