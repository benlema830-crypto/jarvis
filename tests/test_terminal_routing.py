"""Terminal tasks run in a sandboxed Codex session by default, whether or not paid APIs are enabled."""
import unittest
from unittest import mock

import tools


class TerminalRoutingTest(unittest.TestCase):
    def setUp(self):
        self.prefs = {}
        for patcher in (mock.patch('preferences.read', side_effect=lambda: dict(self.prefs)),
                        mock.patch.object(tools.SESSIONS, 'open', return_value='ready'),
                        mock.patch.object(tools.SESSIONS, 'start', return_value='Jarvis Tasks started.'),
                        mock.patch.object(tools.TERMINAL, 'start', return_value='Started.')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.running = mock.patch.object(type(tools.SESSIONS), 'running', new_callable=mock.PropertyMock, return_value=False)
        self.running.start()
        self.addCleanup(self.running.stop)

    def run_task(self):
        from types import SimpleNamespace
        return tools.run_tool(SimpleNamespace(name='terminal_task', id='t', input={'task': 'tidy Downloads'}))['content']

    def assert_codex(self):
        tools.SESSIONS.open.assert_called_with(name='Jarvis Tasks', project='Jarvis', provider='codex')
        tools.SESSIONS.start.assert_called_with('tidy Downloads', name='Jarvis Tasks', mode='work')
        tools.TERMINAL.start.assert_not_called()

    def test_paid_apis_enabled_still_uses_codex(self):
        self.prefs = {'subscription_only': False}
        self.assertIn('started', self.run_task())
        self.assert_codex()

    def test_subscription_only_uses_codex(self):
        self.prefs = {'subscription_only': True}
        self.run_task()
        self.assert_codex()

    def test_claude_code_only_by_explicit_choice_and_never_in_subscription_only(self):
        self.prefs = {'subscription_only': False, 'terminal_provider': 'claude'}
        self.run_task()
        tools.TERMINAL.start.assert_called_once()
        tools.TERMINAL.start.reset_mock()
        self.prefs = {'subscription_only': True, 'terminal_provider': 'claude'}
        self.run_task()
        self.assert_codex()

    def test_status_and_stop_follow_the_codex_task(self):
        self.prefs = {'subscription_only': False}
        self.running.stop()
        with mock.patch.object(type(tools.SESSIONS), 'running', new_callable=mock.PropertyMock, return_value=True), \
                mock.patch.object(tools.SESSIONS, 'status', return_value='{"status": "running"}') as status, \
                mock.patch.object(tools.SESSIONS, 'cancel') as cancel, \
                mock.patch.object(type(tools.TERMINAL), 'running', new_callable=mock.PropertyMock, return_value=False):
            self.assertIn('running', tools.terminal_status.call({}))
            status.assert_called_with('Jarvis Tasks')
            self.assertEqual(tools.stop_terminal_task.call({}), 'Stopping.')
            cancel.assert_called_once()
        self.running.start()

    def test_paid_tools_are_not_gated_when_subscription_only_is_off(self):
        self.prefs = {'subscription_only': False}
        from types import SimpleNamespace
        with mock.patch.object(tools.AGENT, 'start', return_value='Started.') as start:
            result = tools.run_tool(SimpleNamespace(name='do_on_computer', id='d', input={'task': 'open settings'}))
        self.assertNotIn('disabled', result['content'])
        start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
