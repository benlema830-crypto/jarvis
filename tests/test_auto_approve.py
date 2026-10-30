import unittest
from unittest import mock

import approvals


class AutoApproveTest(unittest.TestCase):
    def mode(self, value):
        patcher = mock.patch.object(approvals.preferences, 'read', return_value={'auto_approve': value} if value else {})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_routine_work_is_automatic(self):
        self.mode('routine')
        for question, kind in [('Jarvis Tasks needs approval: install. Command: winget install Git.Git', 'install'),
                               ('Change the power plan to High performance', 'system settings'),
                               ('requests broader access: network', 'broader access'),
                               ('requests a file change: add notes.md', 'file edit'),
                               ('MCP server: Zapier\nTool: find_row\nArguments: {}', 'mcp tool'),
                               ('Open Paint and draw a box', None)]:
            self.assertTrue(approvals.auto_approved(question, kind), question)
        with mock.patch.object(approvals, 'on_question') as spoken:
            self.assertEqual(approvals.ask('winget install Git.Git', kind='install'),
                             (True, '(auto-approved by your settings)'))
        spoken.assert_not_called()

    def test_irreversible_or_outward_actions_still_ask(self):
        self.mode('routine')
        for question, kind in [('delete the old logs. Command: Remove-Item logs -Recurse', 'delete'),
                               ('git push --force', 'destructive git'),
                               ('needs approval: publish or external message', 'publish or external message'),
                               ('run an encoded command', 'hidden or encoded command'),
                               ('add Jarvis to startup', 'change startup, credential or agent settings'),
                               ('install a tool. Command: Remove-Item C:/temp/x', 'install'),   # sneaks a delete in
                               ('MCP server: Zapier\nTool: gmail_send_email\nArguments: {}', 'mcp tool'),
                               ('Click Buy now to purchase the cable', None),
                               ('Send the report to my boss by email', None),
                               ('Type my password into the login page', None)]:
            self.assertFalse(approvals.auto_approved(question, kind), question)

    def test_default_asks_everything_and_all_asks_nothing(self):
        self.mode(None)
        self.assertFalse(approvals.auto_approved('winget install Git.Git', 'install'))
        self.mode('all')
        self.assertTrue(approvals.auto_approved('delete everything', 'delete'))


if __name__ == '__main__':
    unittest.main()
