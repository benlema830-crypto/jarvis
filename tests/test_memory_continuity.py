"""Phase A1: benign memory writes keep the conversation; forget/correct still invalidates it."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import jarvis
import memory
import model_provider
import privacy
import response_settings


class IsolatedMemory(unittest.TestCase):
    """Every memory/privacy file lives in a temporary folder; live data is never touched."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for module, field, value in [(memory, 'PATH', str(root / 'memory.json')),
                                     (memory, 'RECENT_PATH', str(root / 'recent.json')),
                                     (privacy, 'STORE', root / 'privacy.json'),
                                     (response_settings, 'STORE', root / 'response-settings.json')]:
            patcher = mock.patch.object(module, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def brain(self):
        with mock.patch.object(jarvis.anthropic, 'Anthropic'):
            brain = jarvis.Brain()
        brain.config = dict(brain.selection.begin()); brain.selection.end()
        brain.seen, brain.history = [], []

        def run(speak):
            brain.history.append(json.dumps(model_provider.text_history(brain.messages)))
            brain.seen.append(brain.history[-1] + brain.system)
            brain.messages.append({'role': 'assistant', 'content': 'Noted.'})
            speak('Noted.')
        brain._run = run
        return brain


class BenignMemoryKeepsContext(IsolatedMemory):
    def test_follow_up_after_unrelated_remember_still_sees_project(self):
        brain = self.brain()
        brain.ask('We are designing the Orion launch tower in the Rocket Frontier project.', mock.Mock())
        memory.remember('The user prefers tea in the afternoon.')
        codex = brain._codex_brain = mock.Mock()
        brain.ask('What colour should that tower be?', mock.Mock())
        # Working history itself (not only the restart excerpt) still holds the project turn.
        self.assertIn('Orion launch tower', brain.history[-1])
        self.assertIn('prefers tea', brain.system)
        # Persistent Codex threads keep running (a restart made the next reply slow); the new
        # fact reaches them through the working-memory brief in the turn instead.
        codex.close.assert_not_called()
        latest = [m['content'] for m in brain.messages if m['role'] == 'user'][-1]
        self.assertIn('prefers tea', latest)

    def test_duplicate_remember_causes_no_disruption(self):
        memory.remember('The user likes orange.')
        brain = self.brain()
        brain.ask('Remember the Orion tower.', mock.Mock())
        codex = brain._codex_brain = mock.Mock()
        self.assertEqual(memory.remember('the user likes orange'), 'Already remembered.')
        self.assertEqual(memory.remember('The user likes orange'), 'Already remembered.')
        before = list(brain.messages)
        brain.ask('And the colour?', mock.Mock())
        self.assertEqual(brain.messages[:len(before)], before)
        codex.close.assert_not_called()

    def test_claude_tool_pairs_survive_benign_refresh_intact(self):
        brain = self.brain()
        brain.config = {'provider': 'anthropic', 'model': 'claude-test'}
        patcher = mock.patch.object(brain.selection, 'active', dict(brain.config))
        patcher.start(); self.addCleanup(patcher.stop)
        brain.messages = [{'role': 'user', 'content': '[t] find Orion'},
                          {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'call1', 'name': 'search_knowledge', 'input': {}}]},
                          {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call1', 'content': 'Orion note'}]},
                          {'role': 'assistant', 'content': 'Found the Orion note.'}]
        memory.remember('The user likes orange.')
        brain.ask('Summarise it.', mock.Mock())
        self.assertEqual(brain.messages[2]['content'][0]['tool_use_id'], 'call1')

    def test_repeated_refreshes_do_not_duplicate_recent_history(self):
        memory.record_turn('Earlier launch: we picked Kestrel as the codename.', 'Kestrel it is.')
        brain = self.brain()
        for i in range(4):
            brain.ask(f'Turn {i} about the tower.', mock.Mock())
            memory.remember(f'Harmless fact number {i}.')
        brain.ask('Final turn.', mock.Mock())
        self.assertEqual(brain.system.count('Kestrel it is.'), 1)
        # Current-session turns are in working history, not re-injected as "previous launches".
        self.assertNotIn('Turn 0 about the tower', brain.system)
        self.assertIn('Turn 0 about the tower', brain.seen[-1])


class PrivacyInvalidation(IsolatedMemory):
    SECRET = 'The user\'s locker code is 4471.'

    def test_forget_removes_old_value_from_prompt_history_and_restart(self):
        memory.remember(self.SECRET)
        brain = self.brain()
        self.assertIn('4471', brain.system)
        brain.ask('My locker code is 4471, keep it in mind.', mock.Mock())

        def forgetting_turn(speak):
            memory.forget('locker code')
            brain.messages.append({'role': 'assistant', 'content': 'Forgot the locker code 4471.'})
            speak('Forgot the locker code 4471.')
        brain._run = forgetting_turn
        real = time.strftime
        # The reply finishes (and the turn is saved) a few seconds after the forget was written.
        later = lambda fmt, *args: real(fmt, time.localtime(time.time() + 3))
        with mock.patch.object(memory.time, 'strftime', side_effect=later):
            brain.ask('Forget my locker code 4471.', mock.Mock())
        self.brain_run_plain(brain)
        brain.ask('What were we talking about?', mock.Mock())
        self.assertNotIn('4471', brain.seen[-1])
        self.assertNotIn('4471', json.dumps(model_provider.text_history(brain.messages)))
        restarted = self.brain()
        self.assertNotIn('4471', restarted.system)

    def test_ui_correction_supersedes_old_value_everywhere(self):
        memory.remember('The current project priority is Alpha.')
        brain = self.brain()
        brain.ask('Let us plan around Alpha.', mock.Mock())
        state = memory.snapshot()
        memory.edit('update', state['revision'], state['facts'][0]['id'], 'The current project priority is Beta.')
        brain.ask('What is the priority?', mock.Mock())
        self.assertNotIn('Alpha', brain.seen[-1])
        self.assertIn('Beta', brain.system)
        self.assertNotIn('Alpha', self.brain().system)

    def test_privacy_settings_change_still_resets_conversation(self):
        brain = self.brain()
        brain.ask('Project Nightjar is secret.', mock.Mock())
        privacy.configure(['Project Nightjar'])
        brain.ask('Next.', mock.Mock())
        self.assertNotIn('Nightjar', brain.seen[-1])

    def brain_run_plain(self, brain):
        def run(speak):
            brain.history.append(json.dumps(model_provider.text_history(brain.messages)))
            brain.seen.append(brain.history[-1] + brain.system)
            brain.messages.append({'role': 'assistant', 'content': 'Noted.'})
            speak('Noted.')
        brain._run = run


class SafeTextContinuity(IsolatedMemory):
    def _tool_history(self, brain):
        brain.messages = [{'role': 'user', 'content': '[t] look up Orion'},
                          {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Checking.'},
                                                            {'type': 'tool_use', 'id': 'x', 'name': 'search_knowledge', 'input': {}}]},
                          {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'x', 'content': 'Orion'}]},
                          {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Orion is the tower.'}]}]

    def assert_text_only(self, messages):
        for message in messages:
            self.assertIsInstance(message['content'], str)

    def test_provider_switch_keeps_text_and_drops_tool_pairs(self):
        brain = self.brain()
        self._tool_history(brain)
        brain.config = {'provider': 'anthropic', 'model': 'claude-test'}
        brain.ask('Continue.', mock.Mock())
        self.assert_text_only(brain.messages)
        self.assertIn('Orion is the tower.', brain.seen[-1])

    def test_style_change_keeps_text_and_drops_tool_pairs(self):
        brain = self.brain()
        brain.config = dict(brain.selection.active)
        self._tool_history(brain)
        response_settings.update({'detail': 'detailed'})
        brain.ask('Continue.', mock.Mock())
        self.assert_text_only(brain.messages)
        self.assertIn('Orion is the tower.', brain.seen[-1])


if __name__ == '__main__':
    unittest.main()
