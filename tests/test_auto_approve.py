"""What still waits for the owner's yes. Their decision, 2026-11-11: "there should be little to no rules"."""
import threading
import time
import unittest
from unittest import mock

import approvals


class AutoApproveTest(unittest.TestCase):
    def mode(self, value):
        patcher = mock.patch.object(approvals.preferences, 'read', return_value={'auto_approve': value} if value else {})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_nearly_everything_runs_without_a_question(self):
        self.mode(None)  # the default
        for question, kind in [('Jarvis Tasks needs approval: install. Command: winget install Git.Git', 'install'),
                               ('delete the old logs. Command: Remove-Item logs -Recurse', 'delete'),
                               ('git push --force', 'destructive git'),
                               ('add Jarvis to startup', 'change startup, credential or agent settings'),
                               ('requests broader access: network', 'broader access'),
                               ('requests a file change: remove the token from the order form', 'file edit'),
                               ('MCP server: Zapier\nTool: find_row\nArguments: {"share": "password"}', 'mcp tool'),
                               ('run a command outside normal access', 'command')]:
            self.assertTrue(approvals.auto_approved(question, kind), question)
        with mock.patch.object(approvals, 'on_question') as spoken:
            self.assertEqual(approvals.ask('Remove-Item logs -Recurse', kind='delete'),
                             (True, '(auto-approved by your settings)'))
        spoken.assert_not_called()

    def test_money_and_messages_to_other_people_still_ask(self):
        self.mode('routine')
        for question, kind in [('needs approval: message other people. Command: gh pr comment 5', approvals.MESSAGE),
                               ('Send this email?\nTo: sam@example.com', approvals.MESSAGE),
                               ('MCP server: Shop\nTool: checkout', approvals.MONEY),
                               ('May I click Buy now for the cable?', None),      # a question an agent chose to ask
                               ('May I post this reply for you?', None)]:
            self.assertFalse(approvals.auto_approved(question, kind), question)

    def test_an_outside_tool_is_judged_by_its_name_alone(self):
        for name, kind in [('gmail_send_email', approvals.MESSAGE), ('createPost', approvals.MESSAGE),
                           ('reply-to-thread', approvals.MESSAGE), ('checkout', approvals.MONEY),
                           ('place_order', approvals.MONEY), ('buyNow', approvals.MONEY),
                           # reading about messages and orders is not sending or buying
                           ('get_posts', None), ('search_messages', None), ('list_orders', None),
                           ('read_email', None),
                           # and these words used to trip the old list
                           ('removeBackground', None), ('share_file', None), ('format_text', None),
                           ('spotify_play', None), ('delete_row', None), ('', None)]:
            self.assertEqual(approvals.tool_kind(name), kind, name)

    def test_the_setting_can_ask_for_everything_or_nothing(self):
        self.mode('none')
        self.assertFalse(approvals.auto_approved('winget install Git.Git', 'install'))
        self.mode('all')
        self.assertTrue(approvals.auto_approved('Send this email?', approvals.MESSAGE))


class AnswerTest(unittest.TestCase):
    """A question is spoken and texted, and the owner gets longer to answer when they are out."""

    def ask(self, limit_name, limit, **kwargs):
        texts, result = [], {}
        with mock.patch.object(approvals, 'on_question', lambda speech: None), \
                mock.patch.object(approvals, 'on_text', lambda *args: texts.append(args)), \
                mock.patch.object(approvals, limit_name, limit), \
                mock.patch.object(approvals.preferences, 'read', return_value={}):
            asker = threading.Thread(target=lambda: result.update(answer=approvals.ask('May I email Sam?', **kwargs)))
            asker.start()
            asker.join(5)
        return result['answer'], texts

    def test_the_question_is_texted_as_well_as_spoken(self):
        answer, texts = self.ask('TIMEOUT', 0.5)
        self.assertEqual(answer, (False, '(no answer within two minutes)'))
        self.assertEqual(texts, [('May I email Sam?', 'May I email Sam?', False)])

    def test_an_away_question_waits_ten_minutes_not_two(self):
        with mock.patch.object(approvals, 'TIMEOUT', 3600):          # would hang the test if it were used
            answer, _ = self.ask('AWAY_TIMEOUT', 0.5, away=True)
        self.assertEqual(answer, (False, '(no answer within ten minutes)'))
        with mock.patch.object(approvals, 'TIMEOUT', 3600), mock.patch.object(approvals, 'is_away', lambda: True):
            answer, _ = self.ask('AWAY_TIMEOUT', 0.5)                 # nobody has touched the PC for a while
        self.assertEqual(answer, (False, '(no answer within ten minutes)'))

    def test_a_text_that_cant_be_sent_doesnt_cost_the_question(self):
        result = {}
        with mock.patch.object(approvals, 'on_question', lambda speech: None), \
                mock.patch.object(approvals, 'on_text', mock.Mock(side_effect=RuntimeError('no signal'))), \
                mock.patch.object(approvals.preferences, 'read', return_value={}):
            asker = threading.Thread(target=lambda: result.update(answer=approvals.ask('May I email Sam?')))
            asker.start()
            while not approvals.waiting():
                time.sleep(0.01)
            approvals.answer('yes')
            asker.join(5)
        self.assertEqual(result['answer'], (True, 'yes'))


if __name__ == '__main__':
    unittest.main()
