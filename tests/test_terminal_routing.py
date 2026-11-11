"""Terminal tasks go to the Jarvis Tasks agent session, on the model Jarvis chose for the job."""
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

    def test_a_task_goes_to_the_jarvis_tasks_session_with_no_model_forced(self):
        self.assertIn('started', self.run_task())
        tools.SESSIONS.open.assert_called_with(name='Jarvis Tasks', project='Jarvis')
        tools.SESSIONS.start.assert_called_with('tidy Downloads', name='Jarvis Tasks', mode='work', model='', effort='', fresh=True)
        tools.TERMINAL.start.assert_not_called()

    def test_old_settings_no_longer_decide_the_model(self):
        for prefs in ({'subscription_only': True}, {'subscription_only': False, 'terminal_provider': 'claude'}):
            self.prefs = prefs
            self.run_task()
            tools.SESSIONS.start.assert_called_with('tidy Downloads', name='Jarvis Tasks', mode='work', model='', effort='', fresh=True)
        tools.TERMINAL.start.assert_not_called()

    def test_jarvis_choice_of_model_and_effort_is_passed_on(self):
        from types import SimpleNamespace
        tools.run_tool(SimpleNamespace(name='terminal_task', id='t', input={'task': 'rename a file', 'model': 'haiku', 'effort': 'low'}))
        tools.SESSIONS.start.assert_called_with('rename a file', name='Jarvis Tasks', mode='work', model='haiku', effort='low', fresh=True)
        with mock.patch.object(type(tools.TERMINAL), 'running', new_callable=mock.PropertyMock, return_value=False):
            tools.run_tool(SimpleNamespace(name='send_agent_task', id='t', input={'task': 'big refactor', 'name': 'Giant Builder', 'mode': 'work', 'model': 'opus', 'effort': 'high'}))
        tools.SESSIONS.start.assert_called_with('big refactor', 'Giant Builder', 'work', model='opus', effort='high')

    def test_status_and_stop_follow_the_codex_task(self):
        self.prefs = {'subscription_only': False}
        with mock.patch.dict(tools.SESSIONS.workers, {'jarvis tasks': object()}), \
                mock.patch.object(tools.SESSIONS, 'status', return_value='Jarvis Tasks: running') as status, \
                mock.patch.object(tools.SESSIONS, 'cancel') as cancel, \
                mock.patch.object(type(tools.TERMINAL), 'running', new_callable=mock.PropertyMock, return_value=False):
            self.assertIn('running', tools.terminal_status.call({}))
            status.assert_called_with('Jarvis Tasks')
            self.assertEqual(tools.stop_terminal_task.call({}), 'Stopping.')
            cancel.assert_called_once_with('Jarvis Tasks')

    def test_stopping_the_terminal_task_leaves_project_agents_alone(self):
        with mock.patch.dict(tools.SESSIONS.workers, {'giant builder': object()}), \
                mock.patch.object(tools.SESSIONS, 'cancel') as cancel, \
                mock.patch.object(type(tools.TERMINAL), 'running', new_callable=mock.PropertyMock, return_value=False):
            self.assertIn('No terminal task', tools.stop_terminal_task.call({}))
            cancel.assert_not_called()

    def test_followups_continue_the_conversation_and_folder_is_passed_on(self):
        from types import SimpleNamespace
        tools.run_tool(SimpleNamespace(name='terminal_task', id='t', input={'task': 'and also that', 'continue_previous': True}))
        tools.SESSIONS.start.assert_called_with('and also that', name='Jarvis Tasks', mode='work', model='', effort='')
        tools.run_tool(SimpleNamespace(name='terminal_task', id='t', input={'task': 'build', 'folder': 'C:/Work'}))
        tools.SESSIONS.start.assert_called_with('build', name='Jarvis Tasks', mode='work', model='', effort='', fresh=True, folder='C:/Work')

    def test_sending_a_task_to_a_running_session_delivers_it_as_a_message(self):
        from types import SimpleNamespace
        with mock.patch.dict(tools.SESSIONS.workers, {'giant builder': object()}), \
                mock.patch.object(tools.SESSIONS, 'message', return_value='Delivered') as message, \
                mock.patch.object(type(tools.TERMINAL), 'running', new_callable=mock.PropertyMock, return_value=False):
            result = tools.run_tool(SimpleNamespace(name='send_agent_task', id='t', input={'task': 'also this', 'name': 'Giant Builder', 'mode': 'work'}))
        self.assertEqual(result['content'], 'Delivered')
        message.assert_called_once_with('also this', 'Giant Builder')

    def test_paid_tools_are_not_gated_when_subscription_only_is_off(self):
        self.prefs = {'subscription_only': False}
        from types import SimpleNamespace
        with mock.patch.object(tools.AGENT, 'start', return_value='Started.') as start:
            result = tools.run_tool(SimpleNamespace(name='do_on_computer', id='d', input={'task': 'open settings'}))
        self.assertNotIn('disabled', result['content'])
        start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
